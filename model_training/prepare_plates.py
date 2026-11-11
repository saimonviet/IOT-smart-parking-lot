"""Tải và chuẩn bị dữ liệu biển số Việt Nam cho 2 mô hình: phát hiện biển (YOLO) và đọc ký tự (CRNN).

Nguồn dữ liệu:
  1. VNLP (fict-labs, ~37.300 ảnh, 1 dòng + 2 dòng, có nhãn khung + chuỗi biển trong TÊN FILE)
     https://github.com/fict-labs/VNLP  — Trinh et al., MAPR 2022; Pham, The Visual Computer 2023.
     Tên file: a_b_c_<BIENSO>_<x1>_<y1>_<x2>_<y2>.jpg  (readme ghi "rộng-cao" nhưng thực tế là góc dưới phải)
  2. LP_detection (trungdinh22/License-Plate-Recognition, ~8.300 ảnh cảnh đường phố, nhãn YOLO 1 lớp)
  3. Font + nền biển của NNDam/Vietnamese-License-Plate-Generator (để sinh biển tổng hợp khi huấn luyện OCR)

Kết quả:
  data/plates/det/{images,labels}/{train,val,test}  + data/plates/det/plates.yaml   (2 lớp: plate_1row, plate_2row)
  data/plates/ocr/crops/*.jpg + data/plates/ocr/{train,val,test}.csv               (đường dẫn, nhãn, 2 dòng)

Chạy:  python prepare_plates.py [--vnlp-det 9000] [--cleanup]
       --cleanup: xoá file zip sau khi giải nén (tiết kiệm ~4 GB)
"""
import argparse
import csv
import hashlib
import io
import random
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
P = ROOT / "data" / "plates"
RAW = P / "raw"
DET = P / "det"
OCR = P / "ocr"
VNLP_FOLDER = "https://drive.google.com/drive/folders/19OnlE0gFXEMPyngxRZ980d4z0fGQ-C7T"
LPDET_ID = "1xchPXf7a1r466ngow_W_9bittRqQEf_T"
GEN_ZIP = "https://github.com/NNDam/Vietnamese-License-Plate-Generator/archive/refs/heads/master.zip"
ALPHABET = set("0123456789ABCDEFGHKLMNPRSTUVXYZ")
PLATE_RE = re.compile(r"^(\d{2})([A-Z]{1,2}|[A-Z]\d)(\d{4,5})$")
ONE_ROW_MIN_RATIO = 3.2   # dataset 1 lớp: rộng/cao >= 3.2 coi là biển 1 dòng


def gdown(*args):
    exe = Path(sys.executable).with_name("gdown.exe" if sys.platform == "win32" else "gdown")
    cmd = [str(exe) if exe.exists() else "gdown", *args]
    print("[↓]", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=RAW)


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    vnlp = RAW / "Dataset" / "VNLP_detection.zip"
    if not vnlp.exists():
        gdown("--folder", VNLP_FOLDER)          # ~3.7 GB
    lp = RAW / "LP_detection.zip"
    if not lp.exists():
        gdown(LPDET_ID, "-O", str(lp))          # ~350 MB
    gen = P / "generator"
    if not (gen / "MyFont-Regular_ver3.otf").exists():
        print("[↓] NNDam generator (font + nền biển)")
        data = urllib.request.urlopen(GEN_ZIP).read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(P)
        shutil.move(str(P / "Vietnamese-License-Plate-Generator-master"), str(gen))
    return vnlp, lp


def split_of(key, val=0.1, test=0.1):
    """Chia theo biển số (cùng 1 xe không nằm ở cả train và test)."""
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test else "val" if h < test + val else "train"


def yolo_line(cls, x1, y1, x2, y2, w, h):
    x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
    return f"{cls} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"


def prepare_vnlp(zpath, det_quota):
    """Mọi ảnh -> ảnh biển đã cắt cho OCR; một phần ảnh đầy đủ -> tập phát hiện biển."""
    (OCR / "crops").mkdir(parents=True, exist_ok=True)
    rows = {"train": [], "val": [], "test": []}
    stats = Counter()
    rng = random.Random(0)
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".jpg")]
        rng.shuffle(names)
        quota = {"train": det_quota, "val": det_quota // 8, "test": det_quota // 8}
        for k, name in enumerate(names):
            folder, base = name.split("/")[-2], Path(name).stem
            parts = base.split("_")
            if len(parts) < 8:
                stats["bad_name"] += 1
                continue
            label = re.sub(r"[^0-9A-Z]", "", parts[3].upper())
            try:
                x1, y1, x2, y2 = map(int, parts[-4:])
            except ValueError:
                stats["bad_box"] += 1
                continue
            if not PLATE_RE.match(label) or set(label) - ALPHABET:
                stats["bad_label"] += 1
                continue
            two = folder != "one_row"
            img = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                stats["bad_img"] += 1
                continue
            h, w = img.shape[:2]
            if x2 - x1 < 12 or y2 - y1 < 8:
                stats["tiny"] += 1
                continue
            sp = split_of(label)
            # crop OCR: lề giống server (6% ngang, 10% dọc)
            px, py = (x2 - x1) * 0.06, (y2 - y1) * 0.10
            a, b = int(max(0, x1 - px)), int(max(0, y1 - py))
            c, d = int(min(w, x2 + px)), int(min(h, y2 + py))
            crop_name = f"vnlp_{k:05d}.jpg"
            cv2.imwrite(str(OCR / "crops" / crop_name), img[b:d, a:c], [cv2.IMWRITE_JPEG_QUALITY, 92])
            rows[sp].append((f"crops/{crop_name}", label, int(two)))
            stats[f"ocr_{sp}"] += 1
            # ảnh đầy đủ cho phát hiện biển (giới hạn số lượng: VNLP rất giống nhau, chụp ở trạm đăng kiểm)
            if quota[sp] > 0:
                quota[sp] -= 1
                stem = f"vnlp_{k:05d}"
                (DET / "images" / sp).mkdir(parents=True, exist_ok=True)
                (DET / "labels" / sp).mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(DET / "images" / sp / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                (DET / "labels" / sp / f"{stem}.txt").write_text(yolo_line(int(two), x1, y1, x2, y2, w, h) + "\n")
                stats[f"det_{sp}"] += 1
            if k % 2000 == 0:
                print(f"  VNLP {k}/{len(names)}")
    for sp, items in rows.items():
        with open(OCR / f"{sp}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["path", "label", "two_rows"])
            wr.writerows(items)
    return stats


def prepare_lpdet(zpath):
    """trungdinh22 LP_detection: nhãn 1 lớp -> 2 lớp theo tỉ lệ khung; val gốc chia đôi thành val/test."""
    stats = Counter()
    with zipfile.ZipFile(zpath) as z:
        labels = {Path(n).stem: n for n in z.namelist() if n.endswith(".txt") and "/labels/" in n}
        for name in z.namelist():
            if not name.lower().endswith((".jpg", ".jpeg", ".png")) or "/images/" not in name:
                continue
            stem = Path(name).stem
            src_split = "train" if "/train/" in name else "val"
            sp = src_split if src_split == "train" else ("val" if split_of(stem) != "test" else "test")
            data = z.read(name)
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None or stem not in labels:
                stats["skip"] += 1
                continue
            h, w = img.shape[:2]
            out = []
            for ln in z.read(labels[stem]).decode().split("\n"):
                v = ln.split()
                if len(v) != 5:
                    continue
                _, cx, cy, bw, bh = map(float, v)
                ratio = (bw * w) / max(bh * h, 1e-6)
                out.append(f"{0 if ratio >= ONE_ROW_MIN_RATIO else 1} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
                stats["box_1row" if ratio >= ONE_ROW_MIN_RATIO else "box_2row"] += 1
            (DET / "images" / sp).mkdir(parents=True, exist_ok=True)
            (DET / "labels" / sp).mkdir(parents=True, exist_ok=True)
            (DET / "images" / sp / f"lpd_{stem}{Path(name).suffix.lower()}").write_bytes(data)
            (DET / "labels" / sp / f"lpd_{stem}.txt").write_text("\n".join(out) + "\n")
            stats[f"det_{sp}"] += 1
    return stats


def write_yaml():
    (DET / "plates.yaml").write_text(
        f"path: {DET.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: plate_1row\n  1: plate_2row\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vnlp-det", type=int, default=9000, help="số ảnh VNLP đưa vào tập train phát hiện biển")
    ap.add_argument("--cleanup", action="store_true", help="xoá zip sau khi xong")
    args = ap.parse_args()
    vnlp, lp = download()
    if DET.exists() or OCR.exists():
        print("[*] xoá dữ liệu đã chuẩn bị lần trước")
        shutil.rmtree(DET, ignore_errors=True)
        shutil.rmtree(OCR, ignore_errors=True)
    print("[*] VNLP ...")
    s1 = prepare_vnlp(vnlp, args.vnlp_det)
    print("   ", dict(s1))
    print("[*] LP_detection ...")
    s2 = prepare_lpdet(lp)
    print("   ", dict(s2))
    write_yaml()
    if args.cleanup:
        vnlp.unlink(missing_ok=True)
        lp.unlink(missing_ok=True)
        print("[*] đã xoá file zip")
    print("Xong:", DET / "plates.yaml", "|", OCR)
