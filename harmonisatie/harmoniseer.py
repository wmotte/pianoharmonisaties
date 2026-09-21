"""Start de bestaande koraalgenerator met het meegeleverde basismodel."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from harmonizer.chorale_generate import main as generate

    generate(default_model=Path(__file__).with_name("model.json"))


if __name__ == "__main__":
    main()
