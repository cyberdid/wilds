"""Open the independent static Mulgore atlas viewer.

    python tools/view_mulgore.py
    python tools/view_mulgore.py --window 1600x1000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wilds.azeroth.viewer import DEFAULT_PACK_DIR, DEFAULT_SPAWN_FILE, MulgoreViewer  # noqa: E402

IMPORT_COMMAND = (
    "python tools/import_mulgore_spawns.py --sql-dir "
    "data/azeroth/raw/mangoszero-database/World/Setup/FullDB "
    "--pack-dir data/azeroth/mulgore --out data/azeroth/raw/mulgore-spawns.json"
)


def _parse_window(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("window size must look like WIDTHxHEIGHT") from error
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("window dimensions must be positive")
    return width, height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--spawn-file", type=Path, default=DEFAULT_SPAWN_FILE)
    parser.add_argument("--window", type=_parse_window, default=(1360, 820), metavar="WIDTHxHEIGHT")
    args = parser.parse_args()
    if not args.spawn_file.exists():
        print(f"Local Mulgore spawn snapshot is missing. Run this importer command:\n{IMPORT_COMMAND}")
        return 2
    MulgoreViewer(args.pack_dir, args.spawn_file, args.window).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
