"""Generate a small synthetic cassava-leaf dataset for pipeline demos.

Real deployments should train on the Kaggle "Cassava Leaf Disease" dataset
(or MuZARDI field photos). This script draws simple leaf-like JPEGs in three
classes so the full train → quantise → serve pipeline can be exercised
end-to-end without proprietary imagery.

Usage:
    python generate_synthetic_dataset.py --out ../data/synthetic --per-class 240
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

CLASSES = ("Healthy", "CMD", "CBSD")


def _leaf_base(draw: ImageDraw.ImageDraw, w: int, h: int, curl: int = 0) -> None:
    """Draw a green leaf silhouette with a midrib and side veins."""
    margin = 20
    draw.ellipse([margin, margin // 2, w - margin, h - margin // 2], fill=(34, 120, 40))
    # midrib
    draw.line([(w // 2, margin), (w // 2, h - margin)], fill=(20, 80, 25), width=3)
    # veins
    for i in range(6):
        y = margin + 25 + i * 30
        draw.line([(w // 2, y), (w // 2 - 55 + curl, y + 20)], fill=(25, 90, 30), width=2)
        draw.line([(w // 2, y), (w // 2 + 55 - curl, y + 20)], fill=(25, 90, 30), width=2)


def make_healthy(rng: random.Random, size: int = 224) -> Image.Image:
    img = Image.new("RGB", (size, size), (245, 245, 240))
    draw = ImageDraw.Draw(img)
    _leaf_base(draw, size, size)
    # a few natural speckles
    for _ in range(rng.randint(5, 15)):
        x, y = rng.randint(30, size - 30), rng.randint(20, size - 20)
        r = rng.randint(1, 3)
        draw.ellipse([x, y, x + r, y + r], fill=(30, 100, 35))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def make_cmd(rng: random.Random, size: int = 224) -> Image.Image:
    """Cassava Mosaic Disease: yellow/light-green mosaic blotches, distorted blade."""
    img = make_healthy(rng, size)
    draw = ImageDraw.Draw(img)
    curl = rng.randint(-25, 25)
    for _ in range(rng.randint(10, 25)):
        x, y = rng.randint(25, size - 40), rng.randint(20, size - 40)
        r = rng.randint(6, 22)
        colour = rng.choice([(200, 210, 70), (170, 200, 60), (230, 225, 120), (140, 180, 50)])
        draw.ellipse([x, y, x + r, y + r], fill=colour)
    # slight curl / asymmetry marker
    draw.arc([10 + curl, 10, size - 10, size - 10], 200, 340, fill=(90, 130, 40), width=6)
    return img.filter(ImageFilter.GaussianBlur(0.8))


def make_cbsd(rng: random.Random, size: int = 224) -> Image.Image:
    """Cassava Brown Streak Disease: brown feathery streaks along veins."""
    img = make_healthy(rng, size)
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(6, 14)):
        x = rng.randint(40, size - 40)
        y = rng.randint(30, size - 60)
        length = rng.randint(25, 70)
        angle_spread = rng.randint(-25, 25)
        colour = rng.choice([(120, 80, 40), (140, 95, 50), (90, 60, 30), (160, 110, 60)])
        draw.line([(x, y), (x + angle_spread, y + length)], fill=colour, width=rng.randint(3, 7))
        # chlorotic halo
        draw.ellipse(
            [x - 10, y - 6, x + 14, y + 18],
            outline=(210, 190, 90),
            width=2,
        )
    return img.filter(ImageFilter.GaussianBlur(0.7))


GENERATORS = {"Healthy": make_healthy, "CMD": make_cmd, "CBSD": make_cbsd}


def generate(out_dir: Path, per_class: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    for split, n in (("train", per_class), ("val", max(24, per_class // 5))):
        for cls in CLASSES:
            dest = out_dir / split / cls
            dest.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                img = GENERATORS[cls](rng)
                img.save(dest / f"{cls.lower()}_{i:04d}.jpg", quality=88)
            print(f"  {dest}: {n} images")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="../data/synthetic", help="Output dataset root")
    parser.add_argument("--per-class", type=int, default=240, help="Training images per class")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    print(f"Generating synthetic dataset → {out}")
    generate(out, args.per_class, args.seed)
    print("Done. Use with:  python train.py --data-dir", out)


if __name__ == "__main__":
    main()
