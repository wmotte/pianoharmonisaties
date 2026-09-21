"""Optional Aria scoring and local MLX LoRA training. No cloud services."""

import argparse
import json
import math
import random
import tempfile
import time
from pathlib import Path

import numpy as np

from .annotations import (
    segment_group,
    segment_split,
    validate_reviewed,
    validate_splits,
)
from .corpus import crop_midi, digest
from .model import write_json


def dependencies():
    try:
        import mlx.core as mx
        from aria.config import load_model_config
        from aria.inference.model_mlx import TransformerLM, apply_rotary_emb_mlx
        from aria.model import ModelConfig
        from ariautils.midi import MidiDict
        from ariautils.tokenizer import AbsTokenizer
        from mlx import nn
        from mlx.utils import tree_flatten, tree_map
    except ImportError as e:
        raise RuntimeError(
            "Installeer requirements-harmonizer-ml.txt in een Python 3.12-omgeving op Apple Silicon."
        ) from e
    return (
        mx,
        nn,
        tree_flatten,
        tree_map,
        ModelConfig,
        load_model_config,
        TransformerLM,
        apply_rotary_emb_mlx,
        AbsTokenizer,
        MidiDict,
    )


def make_model(checkpoint=None, rank=0, tiny=False):
    mx, nn, _, _, ModelConfig, load_config, Parent, rope, Tokenizer, _ = dependencies()

    class TrainableAria(Parent):
        def __call__(self, ids):
            # Full causal teacher forcing avoids the upstream mutable inference cache.
            x = self.model.tok_embeddings(ids)
            length = ids.shape[1]
            mask = mx.tril(mx.ones((length, length), dtype=mx.bool_))

            def block(layer, x):
                z = layer.norm1(x)
                q, k, v = layer.mixed_qkv(z).split(3, axis=-1)
                shape = (ids.shape[0], length, layer.n_heads, layer.d_head)
                q = rope(q.reshape(shape)).transpose(0, 2, 1, 3)
                k = rope(k.reshape(shape)).transpose(0, 2, 1, 3)
                v = v.reshape(shape).transpose(0, 2, 1, 3)
                y = mx.fast.scaled_dot_product_attention(
                    q, k, v, scale=layer.scale, mask=mask
                )
                x = x + layer.att_proj_linear(
                    y.transpose(0, 2, 1, 3).reshape(ids.shape[0], length, -1)
                )
                z = layer.norm2(x)
                return x + layer.ff_down_proj(
                    nn.silu(layer.ff_gate_proj(z)) * layer.ff_up_proj(z)
                )

            for layer in self.model.encode_layers:
                x = block(layer, x)
            return self.lm_head(self.model.out_layer_norm(x))

    class LoRALinear(nn.Module):
        def __init__(self, base, rank):
            super().__init__()
            self.base = base
            self.rank = rank
            self.lora_a = mx.random.normal((base.weight.shape[1], rank)) * 0.01
            self.lora_b = mx.zeros((rank, base.weight.shape[0]))

        def __call__(self, x):
            return self.base(x) + (
                x @ self.lora_a.astype(x.dtype) @ self.lora_b.astype(x.dtype)
            ) * (16 / self.rank)

    tokenizer = Tokenizer()
    cfg = (
        load_config("medium")
        if not tiny
        else {
            "d_model": 64,
            "n_heads": 4,
            "n_layers": 2,
            "ff_mult": 2,
            "drop_p": 0.0,
            "max_seq_len": 128,
            "vocab_size": tokenizer.vocab_size,
            "grad_checkpoint": False,
        }
    )
    config = ModelConfig(**cfg)
    config.set_vocab_size(tokenizer.vocab_size)
    model = TrainableAria(config)
    if checkpoint:
        # Base checkpoints also include non-inference rotary buffers in some releases.
        weights = mx.load(str(checkpoint))
        expected = dict(dependencies()[2](model.parameters()))
        missing = set(expected) - set(weights)
        if missing:
            raise ValueError(
                f"Aria-checkpoint mist modelgewichten: {sorted(missing)[:3]}"
            )
        model.load_weights([(k, weights[k]) for k in expected], strict=True)
    model.set_dtype(mx.float32 if tiny else mx.float16)
    model.freeze()
    if rank:
        for layer in model.model.encode_layers:
            for name in ("mixed_qkv", "att_proj_linear"):
                wrapper = LoRALinear(getattr(layer, name), rank)
                wrapper.freeze()
                wrapper.unfreeze(keys=["lora_a", "lora_b"], recurse=False)
                setattr(layer, name, wrapper)
    mx.eval(model.parameters())
    return model, tokenizer


def tokenize(path, tokenizer):
    MidiDict = dependencies()[-1]
    # Use the checkpoint's original treatment of pedal-expanded note durations.
    tokens = tokenizer.tokenize(MidiDict.from_midi(str(path)), add_dim_tok=False)
    return tokenizer.encode(tokens)


def sequence_loss(model, ids):
    mx, nn, *_ = dependencies()
    arr = mx.array(ids, dtype=mx.int32)[None, :]
    logits = model(arr[:, :-1]).astype(mx.float32)
    return nn.losses.cross_entropy(logits, arr[:, 1:], reduction="mean")


def score_sequence(model, ids, context=1024):
    # Weight windows by predicted tokens, including the short final window.
    model.eval()
    total, count = 0.0, 0
    for start in range(0, len(ids) - 1, context):
        chunk = ids[start : start + context + 1]
        if len(chunk) > 1:
            total += float(sequence_loss(model, chunk).item()) * (len(chunk) - 1)
            count += len(chunk) - 1
    if not count:
        raise ValueError("Geen scoorbare MIDI-tokens.")
    return total / count


def load_adapter(model, adapter, checkpoint):
    metadata = json.loads(Path(adapter).with_suffix(".json").read_text())
    if metadata["base_sha256"] != digest(checkpoint):
        raise ValueError("Adapter hoort bij een ander basischeckpoint.")
    if metadata.get("status") != "trained_reviewed":
        raise ValueError(
            "Alleen adapters op gecontroleerde data mogen kandidaten rangschikken."
        )
    model.load_weights(str(adapter), strict=False)
    return metadata


def rank_candidates(output, candidates, settings):
    checkpoint = Path(settings["checkpoint"])
    adapter = settings.get("adapter")
    context = int(settings.get("context", 1024))
    weight = float(settings.get("weight", 0.2))
    if not 32 <= context <= 4096 or not 0 <= weight <= 1:
        raise ValueError("Ongeldige Aria-context of weging.")
    rank = (
        json.loads(Path(adapter).with_suffix(".json").read_text())["rank"]
        if adapter
        else 0
    )
    model, tokenizer = make_model(checkpoint, rank)
    if adapter:
        load_adapter(model, adapter, checkpoint)
    for c in candidates:
        c["aria_nll"] = score_sequence(
            model, tokenize(Path(output) / c["performance_midi"], tokenizer), context
        )
    # Normalization keeps the explicit weight interpretable on this candidate set.
    for c in candidates:
        combined = 0
        for key, w in (("score", 1 - weight), ("aria_nll", weight)):
            values = [x[key] for x in candidates]
            combined += (
                w * (c[key] - np.mean(values)) / max(float(np.std(values)), 1e-6)
            )
        c["combined_score"] = float(combined)
    return {
        "base_sha256": digest(checkpoint),
        "adapter_sha256": digest(adapter) if adapter else None,
        "weight": weight,
        "context": context,
        "weight_status": "must be selected on validation listening",
    }


def prepare_dataset(manifest_path, annotation_path, output):
    _, _, _, _, _, _, _, _, Tokenizer, _ = dependencies()
    manifest = json.loads(Path(manifest_path).read_text())
    annotations = json.loads(Path(annotation_path).read_text())
    by_id = {s["id"]: s for s in manifest["sources"]}
    validate_splits(by_id)
    selected = []
    for segment in annotations["segments"]:
        source = by_id[segment["source_id"]]
        if (
            not segment.get("reviewed")
            or segment.get("exclude")
            or segment.get("duplicate_of")
        ):
            continue
        validate_reviewed(segment, source)
        split = segment_split(segment, source, by_id)
        if split in ("train", "validation"):
            selected.append((segment, source, split))
    if {split for _, _, split in selected} != {"train", "validation"}:
        raise ValueError(
            "Finetuning vereist gecontroleerde trainings- én validatiesegmenten. Er wordt niet op proefannotaties getraind."
        )
    tokenizer, rows = Tokenizer(), []
    with tempfile.TemporaryDirectory() as temporary:
        for i, (seg, src, split) in enumerate(selected):
            if digest(src["midi"]) != src["midi_sha256"]:
                raise ValueError(
                    "Dataset wijkt af van de vastgelegde splits of MIDI-hashes."
                )
            crop = Path(temporary) / f"{i}.mid"
            crop_midi(src["midi"], crop, seg["start"], seg["end"])
            # Explicit transposition after splitting, never across validation/test.
            import pretty_midi

            for shift in (-2, 0, 2) if split == "train" else (0,):
                pm = pretty_midi.PrettyMIDI(str(crop))
                ns = [n for ins in pm.instruments for n in ins.notes]
                if (
                    not ns
                    or min(n.pitch for n in ns) + shift < 21
                    or max(n.pitch for n in ns) + shift > 108
                ):
                    continue
                for n in ns:
                    n.pitch += shift
                augmented = Path(temporary) / "augmented.mid"
                pm.write(str(augmented))
                rows.append(
                    {
                        "source_id": src["id"],
                        "tune": seg["tune"],
                        "group": segment_group(seg, src, by_id),
                        "split": split,
                        "shift": shift,
                        "tokens": tokenize(augmented, tokenizer),
                    }
                )
    write_json(
        output,
        {
            "status": "reviewed",
            "manifest_sha256": digest(manifest_path),
            "annotations_sha256": digest(annotation_path),
            "rows": rows,
        },
    )


def train(
    checkpoint,
    dataset,
    output,
    rank=8,
    context=1024,
    epochs=3,
    accumulation=4,
    smoke=False,
    max_steps=None,
):
    mx, nn, flatten, tree_map, *_ = dependencies()
    import mlx.optimizers as optim

    random.seed(0)
    mx.random.seed(0)
    if not 1 <= epochs <= 3 or not 1 <= rank <= 64 or context < 16 or accumulation < 1:
        raise ValueError("Ongeldige trainingsinstellingen.")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Trainingsuitvoer bestaat al. Gebruik een nieuwe map.")
    if smoke:
        model, _tokenizer = make_model(rank=rank, tiny=True)
        context = min(context, 64)
        rows = [
            {
                "split": split,
                "tokens": [
                    i % 50 + 10 for i in range(25701 if split == "train" else 129)
                ],
                "group": split,
            }
            for split in ("train", "validation")
        ]
        max_steps = max_steps or 100
    else:
        data = json.loads(Path(dataset).read_text())
        if data.get("status") != "reviewed":
            raise ValueError("Dataset is niet gecontroleerd.")
        rows = data["rows"]
        groups = {
            s: {r["group"] for r in rows if r["split"] == s}
            for s in ("train", "validation")
        }
        if (
            not groups["train"]
            or not groups["validation"]
            or groups["train"] & groups["validation"]
        ):
            raise ValueError("Lege of overlappende trainings- en validatiegroepen.")
        if any(r["split"] not in groups for r in rows):
            raise ValueError(
                "Eindtoetsmateriaal mag niet in het trainingsbestand staan."
            )
        model, _tokenizer = make_model(checkpoint, rank)
    chunks = {
        s: [
            r["tokens"][j : j + context + 1]
            for r in rows
            if r["split"] == s
            for j in range(0, len(r["tokens"]) - 1, context)
            if len(r["tokens"][j : j + context + 1]) > 8
        ]
        for s in ("train", "validation")
    }
    if not all(chunks.values()):
        raise ValueError("Te weinig tokens om te trainen en valideren.")
    output.mkdir(parents=True, exist_ok=True)
    optimizer = optim.AdamW(learning_rate=1e-4, weight_decay=0.01)
    value_and_grad = nn.value_and_grad(model, sequence_loss)
    best, stale, step, history, started = math.inf, 0, 0, [], time.monotonic()
    model.eval()
    initial = sum(
        score_sequence(model, c, context) for c in chunks["validation"]
    ) / len(chunks["validation"])
    best = initial
    initial_trainable = {
        k: np.asarray(v).copy() for k, v in flatten(model.trainable_parameters())
    }
    base_hash = digest(checkpoint) if checkpoint else "synthetic_smoke_model"

    def save(name, status):
        # Save ONLY adapters, never the large frozen weights.
        mx.save_safetensors(
            str(output / name), dict(flatten(model.trainable_parameters()))
        )
        write_json(
            (output / name).with_suffix(".json"),
            {
                "rank": rank,
                "base_sha256": base_hash,
                "context": context,
                "status": status,
                "dataset_sha256": digest(dataset) if dataset else None,
            },
        )

    # Preserve baseline adapter even if every trained checkpoint is worse.
    save("initial.safetensors", "smoke_only" if smoke else "trained_reviewed")
    for epoch in range(epochs):
        random.shuffle(chunks["train"])
        model.train()
        for start in range(0, len(chunks["train"]), accumulation):
            pending, losses = None, []
            batch = chunks["train"][start : start + accumulation]
            for ids in batch:
                loss, grad = value_and_grad(model, ids)
                if not math.isfinite(loss.item()):
                    raise ValueError(
                        "Niet-eindig trainingsverlies. Training afgebroken."
                    )
                losses.append(loss.item())
                pending = (
                    grad
                    if pending is None
                    else tree_map(lambda a, b: a + b, pending, grad)
                )
                mx.eval(pending)
            batch_count = len(batch)
            pending = tree_map(lambda a, count=batch_count: a / count, pending)
            pending, _norm = optim.clip_grad_norm(pending, max_norm=1.0)
            optimizer.update(model, pending)
            mx.eval(model.parameters(), optimizer.state)
            step += 1
            if step % 10 == 0:
                print(f"step={step} loss={sum(losses) / len(losses):.4f}", flush=True)
            if max_steps and step >= max_steps:
                break
        model.eval()
        validation = sum(
            score_sequence(model, c, context) for c in chunks["validation"]
        ) / len(chunks["validation"])
        history.append(
            {"epoch": epoch + 1, "steps": step, "validation_loss": validation}
        )
        if validation < best - 1e-4:
            best, stale = validation, 0
            save("best.safetensors", "smoke_only" if smoke else "trained_reviewed")
        else:
            stale += 1
        if stale >= 1 or (max_steps and step >= max_steps):
            break
    changed = any(
        not np.array_equal(initial_trainable[k], np.asarray(v))
        for k, v in flatten(model.trainable_parameters())
    )
    if not changed:
        raise AssertionError("Geen adaptergewicht veranderd tijdens training.")
    # Check serialization fidelity without allocating another full base model.
    last_path = output / "roundtrip.safetensors"
    mx.save_safetensors(str(last_path), dict(flatten(model.trainable_parameters())))
    before = score_sequence(model, chunks["validation"][0], context)
    model.load_weights(str(last_path), strict=False)
    after = score_sequence(model, chunks["validation"][0], context)
    if abs(before - after) > 1e-6:
        raise AssertionError("Adapter verandert bij opslaan/herladen.")
    last_path.unlink()
    result = {
        "status": "smoke_passed" if smoke else "awaiting_listening",
        "steps": step,
        "initial_validation_loss": initial,
        "best_validation_loss": best,
        "history": history,
        "seconds": time.monotonic() - started,
        "peak_memory_gb": mx.get_peak_memory() / 1e9,
        "adapter_changed": changed,
        "roundtrip_identical": True,
        "trainable_parameters": sum(
            v.size for _, v in flatten(model.trainable_parameters())
        ),
        "quality_claim": "none; listener evaluation required",
    }
    write_json(output / "training_report.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument(
        "--manifest",
        type=Path,
        default=Path("private_data/harmonizer/corpus/manifest.json"),
    )
    prep.add_argument(
        "--annotations",
        type=Path,
        default=Path("private_data/harmonizer/corpus/annotations.json"),
    )
    prep.add_argument("--output", type=Path, required=True)
    tr = sub.add_parser("train")
    tr.add_argument("--checkpoint", type=Path)
    tr.add_argument("--dataset", type=Path)
    tr.add_argument("--output", type=Path, required=True)
    tr.add_argument("--smoke", action="store_true")
    tr.add_argument("--rank", type=int, default=8)
    tr.add_argument("--context", type=int, default=1024)
    tr.add_argument("--epochs", type=int, default=3)
    tr.add_argument("--accumulation", type=int, default=4)
    tr.add_argument("--max-steps", type=int)
    a = p.parse_args()
    if a.command == "prepare":
        prepare_dataset(a.manifest, a.annotations, a.output)
    else:
        if not a.smoke and (not a.checkpoint or not a.dataset):
            p.error("--checkpoint en --dataset zijn verplicht voor echte training")
        print(
            json.dumps(
                train(
                    a.checkpoint,
                    a.dataset,
                    a.output,
                    a.rank,
                    a.context,
                    a.epochs,
                    a.accumulation,
                    a.smoke,
                    a.max_steps,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
