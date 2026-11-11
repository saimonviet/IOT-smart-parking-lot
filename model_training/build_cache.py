"""Gói toàn bộ ảnh patch (CNR-EXT + CNRPark A/B) vào data/cache/patches.bin để huấn luyện nhanh.

Chạy một lần sau download_dataset.py:  python build_cache.py
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import parking_lib as pl

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "cache"


def main():
    cnr = pl.load_cnr_split(DATA / "CNR-EXT", DATA / "CNR-EXT" / "LABELS" / "all.txt")
    ab = pl.load_cnrpark_ab(DATA / "CNRPark")
    paths = list(dict.fromkeys(cnr.path.tolist() + ab.path.tolist()))
    OUT.mkdir(parents=True, exist_ok=True)
    ab.to_csv(OUT / "cnrpark_ab.csv", index=False)  # danh sách + nhãn, để có thể xoá ảnh gốc sau khi gói
    print(f"Gói {len(paths)} ảnh vào {OUT / 'patches.bin'} ...")

    def read(p):
        with open(p, "rb") as f:
            return f.read()

    keys, offsets, lengths = [], [], []
    off = 0
    t0 = time.time()
    with open(OUT / "patches.bin", "wb") as out, ThreadPoolExecutor(32) as ex:
        for i, (p, b) in enumerate(zip(paths, ex.map(read, paths, chunksize=64))):
            out.write(b)
            keys.append(pl._key(p))
            offsets.append(off)
            lengths.append(len(b))
            off += len(b)
            if i % 5000 == 0:
                sys.stdout.write(f"\r  {i}/{len(paths)}  ({i / max(time.time() - t0, 1e-6):.0f} ảnh/s)")
                sys.stdout.flush()
    np.savez(OUT / "index.npz", keys=np.array(keys), offsets=np.array(offsets, np.int64),
             lengths=np.array(lengths, np.int64))
    print(f"\nXong: {off / 2**20:.0f} MB trong {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
