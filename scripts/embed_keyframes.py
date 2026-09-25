"""Embed BTC keyframes with SigLIP-2 or BEiT-3 on any GPU machine (Lightning, Colab, local).

Same preprocessing as personal/aic26-{siglip,beit3}-embedding.ipynb, so the vectors share the
space of the N/S vectors already in the FAISS indexes:
  - SigLIP-2 (google/siglip2-so400m-patch14-384): pad to square with black, processor,
    vision_model pooler_output, L2-normalized, 1152-d.
  - BEiT-3 (beit3_base_patch16_384_coco_retrieval): resize 384x384 bicubic, normalize 0.5,
    vision CLS from only_infer=True, L2-normalized, 768-d.

Output: <out>/<model>/<video_id>.npy with row i = i-th image of the video sorted by the number
in its file name (0001.jpg, 0002.jpg, ...) = row n of map-keyframes/<video_id>.csv. A video
whose .npy already has the right shape is skipped, so the script can be re-run after an
interruption. No shot detection is needed.

Setup (once):
    pip install torch torchvision transformers accelerate pillow tqdm
    # BEiT-3 only:
    pip install timm sentencepiece tensorboardX torchscale
    git clone https://github.com/microsoft/unilm.git
    sed -i 's/from torch._six import inf/from math import inf/g' unilm/beit3/utils.py
    wget -nc https://github.com/addf400/files/releases/download/beit3/beit3_base_patch16_384_coco_retrieval.pth

Examples:
    python embed_keyframes.py --model siglip2 --keyframe-dir data/m --map-dir data/map-keyframes --out out/m
    python embed_keyframes.py --model beit3 --keyframe-dir data/m --map-dir data/map-keyframes --out out/m \\
        --beit3-repo unilm/beit3 --beit3-weights beit3_base_patch16_384_coco_retrieval.pth
"""

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from tqdm.auto import tqdm

VIDEO_ID_RE = re.compile(r"^[A-Z]\d{2,3}[-_]V\d{3}$")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DIMS = {"siglip2": 1152, "beit3": 768}


def scan_keyframes(root: Path) -> dict[str, list[Path]]:
    """Every <video_id>/ folder with images, at any depth, images sorted by number."""
    videos: dict[str, list[Path]] = {}
    for video_dir in sorted(p for p in root.rglob("*") if p.is_dir() and VIDEO_ID_RE.match(p.name)):
        images = [f for f in video_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            continue
        bad = [f.name for f in images if not f.stem.isdigit()]
        if bad:
            raise SystemExit(f"{video_dir}: non-numeric image names {bad[:5]}")
        if video_dir.name in videos:
            raise SystemExit(f"Duplicate video_id {video_dir.name}: {video_dir}")
        videos[video_dir.name] = sorted(images, key=lambda f: int(f.stem))
    return videos


def check_against_map(videos: dict[str, list[Path]], map_dir: Path) -> None:
    problems = []
    for video_id, images in videos.items():
        map_csv = map_dir / f"{video_id}.csv"
        if not map_csv.exists():
            problems.append(f"{video_id}: no map CSV")
            continue
        with open(map_csv, encoding="utf-8") as f:
            numbers = [int(row["n"]) for row in csv.DictReader(f)]
        if [int(p.stem) for p in images] != numbers:
            problems.append(f"{video_id}: {len(images)} images, map has {len(numbers)} rows")
    if problems:
        raise SystemExit("Keyframes do not match map-keyframes:\n" + "\n".join(problems[:20]))
    print(f"[OK] {len(videos)} videos match map-keyframes (count and order)")


class ImageDataset(Dataset):
    def __init__(self, paths: list[Path], preprocess):
        self.paths = paths
        self.preprocess = preprocess

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> torch.Tensor:
        # Raise instead of skipping: a dropped image would shift every later row.
        with Image.open(self.paths[index]) as image:
            return self.preprocess(image.convert("RGB"))


def build_siglip2(device: torch.device):
    from transformers import AutoModel, AutoProcessor

    name = "google/siglip2-so400m-patch14-384"
    processor = AutoProcessor.from_pretrained(name)
    model = AutoModel.from_pretrained(name).to(device).eval()

    def preprocess(image: Image.Image) -> torch.Tensor:
        width, height = image.size
        side = max(width, height)
        padded = Image.new("RGB", (side, side), (0, 0, 0))
        padded.paste(image, ((side - width) // 2, (side - height) // 2))
        return processor(images=padded, return_tensors="pt")["pixel_values"].squeeze(0)

    def encode(pixel_values: torch.Tensor) -> torch.Tensor:
        return model.vision_model(pixel_values=pixel_values).pooler_output

    return preprocess, encode


def build_beit3(device: torch.device, repo: Path, weights: Path):
    from torchvision import transforms

    sys.path.append(str(repo))
    from modeling_finetune import beit3_base_patch16_384_retrieval

    model = beit3_base_patch16_384_retrieval(pretrained=False)
    checkpoint = torch.load(weights, map_location="cpu")
    incompatible = model.load_state_dict(checkpoint["model"], strict=False)
    if incompatible.missing_keys:
        raise SystemExit(f"BEiT-3 checkpoint misses keys: {incompatible.missing_keys[:10]}")
    model = model.to(device).eval()
    preprocess = transforms.Compose([
        transforms.Resize((384, 384), interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
    ])

    def encode(pixel_values: torch.Tensor) -> torch.Tensor:
        return model(image=pixel_values, only_infer=True)[0]

    return preprocess, encode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=sorted(DIMS), required=True)
    parser.add_argument("--keyframe-dir", type=Path, required=True)
    parser.add_argument("--map-dir", type=Path, help="map-keyframes/*.csv to check count and order")
    parser.add_argument("--out", type=Path, required=True, help="writes <out>/<model>/<video_id>.npy")
    parser.add_argument("--videos", nargs="*", help="only these video ids or group prefixes (e.g. M01 M02)")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--beit3-repo", type=Path, default=Path("unilm/beit3"))
    parser.add_argument("--beit3-weights", type=Path, default=Path("beit3_base_patch16_384_coco_retrieval.pth"))
    args = parser.parse_args()

    videos = scan_keyframes(args.keyframe_dir)
    if args.videos:
        videos = {v: p for v, p in videos.items() if any(v == s or v.startswith(s) for s in args.videos)}
    if not videos:
        raise SystemExit(f"No keyframe folders found under {args.keyframe_dir}")
    if args.map_dir:
        check_against_map(videos, args.map_dir)
    total = sum(map(len, videos.values()))
    print(f"[INFO] {len(videos)} videos, {total} keyframes ({min(videos)} … {max(videos)})")

    out_dir = args.out / args.model
    out_dir.mkdir(parents=True, exist_ok=True)
    dim = DIMS[args.model]

    def done(video_id: str) -> bool:
        path = out_dir / f"{video_id}.npy"
        if not path.exists():
            return False
        try:
            return np.load(path, mmap_mode="r").shape == (len(videos[video_id]), dim)
        except ValueError:
            return False

    pending = [v for v in videos if not done(v)]
    print(f"[INFO] done {len(videos) - len(pending)}, pending {len(pending)}")
    if not pending:
        return

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] device {device}")
    if args.model == "siglip2":
        preprocess, encode = build_siglip2(device)
    else:
        preprocess, encode = build_beit3(device, args.beit3_repo, args.beit3_weights)

    start = time.time()
    with torch.no_grad(), torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
        for video_id in tqdm(pending, desc=args.model):
            loader = DataLoader(ImageDataset(videos[video_id], preprocess), batch_size=args.batch_size,
                                num_workers=args.workers, pin_memory=device.type == "cuda")
            chunks = []
            for pixel_values in loader:
                embeddings = encode(pixel_values.to(device, non_blocking=True))
                chunks.append(torch.nn.functional.normalize(embeddings.float(), dim=-1).cpu().numpy())
            matrix = np.vstack(chunks).astype(np.float32)
            if matrix.shape != (len(videos[video_id]), dim):
                raise SystemExit(f"{video_id}: got {matrix.shape}, expected ({len(videos[video_id])}, {dim})")
            tmp = out_dir / f"{video_id}.npy.tmp"
            with open(tmp, "wb") as f:
                np.save(f, matrix)
            tmp.replace(out_dir / f"{video_id}.npy")

    missing = [v for v in videos if not done(v)]
    print(f"[DONE] {len(videos) - len(missing)}/{len(videos)} videos in {(time.time() - start) / 60:.1f} min"
          + (f"; missing {missing[:10]}" if missing else ""))


if __name__ == "__main__":
    main()
