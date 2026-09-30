"""Print the Mulgore art budget and regenerate docs/azeroth/mulgore-art-manifest.md."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wilds.azeroth import manifest  # noqa: E402

if __name__ == "__main__":
    summary = manifest.summary()
    for module, s in summary.items():
        print(f"{module:14s} {s['sprites']:4d} sprites {s['frames']:4d} frames")
    print(f"{'TOTAL':14s} {sum(s['sprites'] for s in summary.values()):4d} sprites "
          f"{sum(s['frames'] for s in summary.values()):4d} frames")
    manifest.write_listing(ROOT / "docs" / "azeroth" / "mulgore-art-manifest.md")
