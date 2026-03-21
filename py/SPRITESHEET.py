"""
Combine numbered sprite frames (name_0.png, name_1.png, …)
into vertical sprite sheets (n × n*m).

Usage:
    python SPRITESHEET.py <folder> [--out <output_folder>] [--prefix <name> ...]

Examples:
    # Convert all sprite groups in the Animations folder
    python SPRITESHEET.py ../popvuj/PopVuj/Assets/Resources/Animations

    # Convert specific sprite groups
    python SPRITESHEET.py ../popvuj/PopVuj/Assets/Resources/Animations --prefix explosion spark sga

    # Specify output folder
    python SPRITESHEET.py ../popvuj/PopVuj/Assets/Resources/Animations --out ./sheets
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

FRAME_PATTERN = re.compile(r"^(.+)_(\d+|[a-z])\.png$", re.IGNORECASE)


def _sort_key(token: str) -> tuple[int, str]:
    """Return a sort key that orders digits numerically and letters alphabetically."""
    if token.isdigit():
        return (0, token.zfill(10))
    return (0, token.lower())


def discover_groups(folder: Path, prefixes: list[str] | None = None) -> dict[str, list[Path]]:
    """Find all name_N.png groups in *folder*, sorted by frame index."""
    allowed = set(prefixes) if prefixes else None
    groups: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for p in folder.iterdir():
        if not p.is_file():
            continue
        m = FRAME_PATTERN.match(p.name)
        if not m:
            continue
        base, idx = m.group(1), m.group(2)
        if allowed and base not in allowed:
            continue
        groups[base].append((idx, p))

    # Sort each group by frame index and return just the paths
    return {
        base: [path for _, path in sorted(frames, key=lambda t: _sort_key(t[0]))]
        for base, frames in sorted(groups.items())
        if len(frames) > 1
    }


def make_sheet(frames: list[Path], output: Path) -> None:
    """Stack *frames* vertically into a single sprite sheet at *output*."""
    images = [Image.open(f).convert("RGBA") for f in frames]
    w, h = images[0].size
    sheet = Image.new("RGBA", (w, h * len(images)), (0, 0, 0, 0))
    for i, img in enumerate(images):
        sheet.paste(img, (0, h * i))
    sheet.save(output)
    print(f"  {output.name}  ({w}×{h * len(images)}, {len(images)} frames)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine sprite frames into vertical sheets.")
    parser.add_argument("folder", type=Path, help="Folder containing name_N.png frames")
    parser.add_argument("--out", type=Path, default=None, help="Output folder (default: same as input)")
    parser.add_argument("--prefix", nargs="+", default=None, help="Only process these base names")
    args = parser.parse_args()

    folder = args.folder.resolve()
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    out_dir = (args.out or folder).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    groups = discover_groups(folder, args.prefix)
    if not groups:
        print("No frame groups found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(groups)} sprite group(s) in {folder}:\n")
    for base, frames in groups.items():
        output_path = out_dir / f"{base}.png"
        make_sheet(frames, output_path)

    print(f"\nDone — {len(groups)} sheet(s) written to {out_dir}")


if __name__ == "__main__":
    main()
