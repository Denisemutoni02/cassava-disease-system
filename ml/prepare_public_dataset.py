"""Download/extract the public iCassava 2019 dataset and map it to 3 classes.

Source (no auth needed):
    https://storage.googleapis.com/emcassavadata/cassavaleafdata.zip  (~1.26 GiB)
    = Kaggle "Cassava Disease" / iCassava 2019, 9430 labelled leaf photos.

The archive contains five classes (cbb, cbsd, cgm, cmd, healthy) already split
into train/test/validation.  This script:

  1. downloads the zip into ``data/downloads/`` (unless already present) unless
     ``--zip`` points at an existing file,
  2. extracts it under ``data/raw/cassavaleafdata/``,
  3. copies only the three classes we need — **cbsd → CBSD, cmd → CMD,
     healthy → Healthy** — into a flat, class-folder dataset that
     ``train_mobilenetv2.py`` can split stratified by itself.

The other two classes (bacterial blight, green mottle) are deliberately
dropped: the deployed system classifies exactly Healthy / CMD / CBSD.

Usage
-----
    python prepare_public_dataset.py                          # download + prepare all
    python prepare_public_dataset.py --per-class-cap 800      # balanced subset (recommended on CPU)
    python prepare_public_dataset.py --zip ../data/downloads/cassavaleafdata.zip
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

URL = "https://storage.googleapis.com/emcassavadata/cassavaleafdata.zip"

# archive folder name -> canonical label (exact labels used by the trainer)
CLASS_MAP = {
    "cbsd": "CBSD",
    "cmd": "CMD",
    "healthy": "Healthy",
}

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    p.add_argument("--data-root", default="../data",
                   help="Project data directory (downloads/, raw/, cassava/ live under it)")
    p.add_argument("--zip", default=None,
                   help="Existing cassavaleafdata.zip (skips the download)")
    p.add_argument("--url", default=URL, help="Archive URL")
    p.add_argument("--per-class-cap", type=int, default=0,
                   help="Keep at most N images per class (0 = keep everything). "
                        "Recommended: 600-800 when training on CPU.")
    p.add_argument("--seed", type=int, default=42, help="Shuffle seed for the cap")
    p.add_argument("--keep-raw", action="store_true",
                   help="Keep data/raw/cassavaleafdata after preparing (default: remove)")
    return p.parse_args()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000_000:
        print(f"[download] already present: {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return
    print(f"[download] {url}\n         -> {dest}  (about 1.26 GiB, takes a few minutes)")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed trusted URL
    tmp.rename(dest)
    print(f"[download] done ({dest.stat().st_size / 1e6:.0f} MB)")


def extract(zip_path: Path, raw_dir: Path) -> Path:
    """Extract the archive once; return the folder containing train/test/validation."""
    if not raw_dir.is_dir() or not any(raw_dir.rglob("*.jpg")):
        print(f"[extract] {zip_path} -> {raw_dir}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(raw_dir)
    # the zip nests everything under cassavaleafdata/
    root = raw_dir / "cassavaleafdata"
    if not root.is_dir():
        candidates = [d for d in raw_dir.iterdir() if d.is_dir()]
        if len(candidates) == 1:
            root = candidates[0]
        else:
            sys.exit(f"Unexpected archive layout under {raw_dir}")
    return root


def collect(root: Path, per_class_cap: int, seed: int) -> dict[str, list[Path]]:
    """Gather image paths per canonical class from all split folders."""
    rng = random.Random(seed)
    buckets: dict[str, list[Path]] = {label: [] for label in set(CLASS_MAP.values())}

    for split_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for src_name, label in CLASS_MAP.items():
            class_dir = split_dir / src_name
            if not class_dir.is_dir():
                continue
            imgs = [p for p in sorted(class_dir.rglob("*"))
                    if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
            buckets[label].extend(imgs)

    for label, paths in buckets.items():
        rng.shuffle(paths)
        if per_class_cap:
            buckets[label] = paths[:per_class_cap]
        else:
            buckets[label] = paths
    return buckets


def write_flat(buckets: dict[str, list[Path]], out_root: Path) -> None:
    if out_root.exists():
        shutil.rmtree(out_root)
    total = 0
    for label, paths in sorted(buckets.items()):
        dest = out_root / label
        dest.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(paths):
            shutil.copy2(src, dest / f"{label.lower()}_{i:05d}{src.suffix.lower()}")
        total += len(paths)
        print(f"  {label:<8} {len(paths):>6} images -> {dest}")
    print(f"  {'TOTAL':<8} {total:>6} images -> {out_root}")


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_root).resolve()

    zip_path = Path(args.zip).resolve() if args.zip else data_root / "downloads" / "cassavaleafdata.zip"
    raw_dir = data_root / "raw"
    out_root = data_root / "cassava"

    download(args.url, zip_path)
    root = extract(zip_path, raw_dir)
    print(f"[raw] dataset root: {root}")

    buckets = collect(root, args.per_class_cap, args.seed)
    print("\n[class distribution before cap]")
    for label, paths in sorted(buckets.items()):
        print(f"  {label:<8} {len(paths):>6}")

    # collect() applies the cap, so recompute counts for an honest table
    print(f"\n[prepare] writing 3-class flat dataset (cap={args.per_class_cap or 'none'})")
    write_flat(buckets, out_root)

    counts = Counter({k: len(v) for k, v in buckets.items()})
    if counts:
        ratio = max(counts.values()) / max(min(counts.values()), 1)
        if ratio >= 2.0:
            print(f"\n[warning] imbalance ratio {ratio:.1f}:1 — the trainer will "
                  "apply balanced sample weights automatically.")

    if not args.keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)
        print(f"[cleanup] removed {raw_dir} (zip kept at {zip_path})")

    print("\nDone. Next:")
    print(f"  python train_mobilenetv2.py --data {out_root} --output-dir models/run_real")


if __name__ == "__main__":
    main()
