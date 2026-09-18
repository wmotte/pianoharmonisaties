#!/usr/bin/env bash
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
#
# Zet alle mp3's in mp3/ om naar bladmuziek (midi/*.musicxml, open in MuseScore) + midi/*.mid.
# Transcriptie met Transkun v2 (standaard) of --model bytedance, daarna opschonen; zie transcribe_piano.py.
# Herhaald draaien is veilig: mp3's met een bestaand midi/*.mid worden overgeslagen.
# Log: midi.log. Extra opties (bijv. --grid 2 --meter 3 --reclean) worden doorgegeven aan transcribe_piano.py.
#
# Eerste keer setup (al gedaan):
#   uv venv --python 3.11 .venv
#   uv pip install --python .venv/bin/python transkun piano_transcription_inference torch pretty_midi music21
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
shopt -s nullglob
exec "$DIR/.venv/bin/python" "$DIR/transcribe_piano.py" "$@" "$DIR"/mp3/*.mp3
