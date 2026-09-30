"""Build a zone's content pack from a raw category dump.

    python tools/wiki_dump.py --base https://warcraft.wiki.gg --out data/azeroth/raw/mulgore-en \
        --category Mulgore --category "Mulgore NPCs" ...
    python tools/build_azeroth_content.py data/azeroth/raw/mulgore-en data/azeroth/mulgore
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wilds.azeroth.content import build  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    counts = build(Path(sys.argv[1]) / "categories.jsonl", Path(sys.argv[2]))
    print(counts)
