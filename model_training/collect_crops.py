"""Thu ảnh từng ô từ camera để tinh chỉnh mô hình với xe mô hình của bạn.

Cắt 12 ô theo ROI trong pc_server/config/layout.json và tự gán nhãn: các ô trong --occupied là "có xe", còn lại là "trống".
Mỗi khung hình cho 12 ảnh có nhãn, nên vài phút là có hàng trăm ảnh.

Ví dụ (đặt xe mô hình vào ô 1, 3, 5, 8 rồi chạy):
    python collect_crops.py --url http://192.168.1.20:8081/snapshot.jpg --occupied 1,3,5,8 --frames 40
Đổi vị trí xe, bật/tắt đèn, che bóng... rồi chạy lại với danh sách ô mới. Bãi trống hoàn toàn: --occupied ""
Ảnh lưu vào data/custom/empty và data/custom/occupied — xem lại và xoá ảnh sai trước khi train.
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
LAYOUT = HERE.parent / "pc_server" / "config" / "layout.json"


def grab(url):
    if url.startswith("http"):
        data = urllib.request.urlopen(url, timeout=10).read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return cv2.imread(url)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="URL snapshot của Pi (…/snapshot.jpg) hoặc đường dẫn ảnh")
    ap.add_argument("--occupied", default="", help="các ô đang có xe, ví dụ 1,3,5")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--interval", type=float, default=1.0, help="giây giữa 2 lần chụp")
    ap.add_argument("--out", default=str(HERE / "data" / "custom"))
    a = ap.parse_args()

    layout = json.loads(LAYOUT.read_text())
    occ = {int(s) for s in a.occupied.split(",") if s.strip()}
    out = Path(a.out)
    for c in ("empty", "occupied"):
        (out / c).mkdir(parents=True, exist_ok=True)
    fw, fh = layout["frame"]["width"], layout["frame"]["height"]
    n = 0
    for i in range(a.frames):
        frame = grab(a.url)
        if frame is None:
            print("Không lấy được ảnh, thử lại...")
            time.sleep(a.interval)
            continue
        h, w = frame.shape[:2]
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{i:03d}"
        for s in layout["slots"]:
            pts = np.array(s["roi"], np.float32) * [w / fw, h / fh]
            x1, y1 = np.clip(pts.min(0).astype(int), 0, [w - 1, h - 1])
            x2, y2 = np.clip(pts.max(0).astype(int), 1, [w, h])
            label = "occupied" if s["id"] in occ else "empty"
            cv2.imwrite(str(out / label / f"slot{s['id']:02d}_{stamp}.jpg"), frame[y1:y2, x1:x2])
            n += 1
        print(f"\rkhung {i + 1}/{a.frames} — {n} ảnh", end="")
        time.sleep(a.interval)
    print(f"\nĐã lưu vào {out}  (có xe: ô {sorted(occ) or 'không'})")


if __name__ == "__main__":
    main()
