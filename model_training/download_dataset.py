"""Tải bộ dữ liệu CNRPark+EXT (ảnh crop từng ô đỗ 150x150, nhãn trống / có xe).

Nguồn: http://cnrpark.it  (bản lưu trữ chính thức của tác giả trên GitHub: fabiocarrara/deep-parking)
Bài báo: Amato et al., "Deep learning for decentralized parking lot occupancy detection", Expert Systems with Applications 2017.

Chạy:  python download_dataset.py            (≈ 500 MB, giải nén vào data/)
"""
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://github.com/fabiocarrara/deep-parking/releases/download/archive/"
FILES = {
    "CNR-EXT-Patches-150x150.zip": "CNR-EXT",     # ~144k patch, 9 camera, nắng/âm u/mưa
    "CNRPark-Patches-150x150.zip": "CNRPark",     # ~12k patch, 2 camera (A, B)
    "splits.zip": "splits",                       # các split train/val/test chuẩn của bài báo
}
DATA = Path(__file__).resolve().parent / "data"


def download(name):
    dst = DATA / "raw" / name
    if dst.exists() and dst.stat().st_size > 0:
        print(f"[=] đã có {name}")
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    with urllib.request.urlopen(BASE + name) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write(f"\r[↓] {name}: {done / total:6.1%} ({done >> 20}/{total >> 20} MB)")
                sys.stdout.flush()
    print()
    tmp.replace(dst)
    return dst


def extract(zpath, folder):
    out = DATA / folder
    if out.exists() and any(out.iterdir()):
        print(f"[=] đã giải nén {folder}")
        return
    print(f"[*] giải nén {zpath.name} -> data/{folder}")
    tmp = DATA / (folder + "_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    # nếu trong zip chỉ có 1 thư mục gốc thì nâng nội dung lên
    items = list(tmp.iterdir())
    src = items[0] if len(items) == 1 and items[0].is_dir() else tmp
    shutil.move(str(src), str(out))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    for name, folder in FILES.items():
        extract(download(name), folder)
    print("Xong. Dữ liệu nằm trong", DATA)
