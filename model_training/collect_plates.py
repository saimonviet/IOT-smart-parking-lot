"""Thu ảnh biển số từ ESP32-CAM của chính bãi xe mô hình để tinh chỉnh OCR (rất nên làm).

Mỗi lần chụp: lưu ảnh gốc, dùng mô hình phát hiện biển (nếu có) để cắt biển, đoán chữ bằng OCR hiện tại
và ghi vào data/plates/custom/labels.csv. Sau đó MỞ labels.csv, SỬA cột label cho đúng (hoặc xoá dòng sai),
rồi chạy lại train_plate.ipynb: ảnh tự thu được trộn vào tập train (nhân 5 lần).

Chạy (đặt xe có biển ở cổng, đổi xe / góc / ánh sáng giữa các lần):
  python collect_plates.py --url http://192.168.1.50 --key <CAM_KEY> --count 30 --interval 1.5
  python collect_plates.py --url http://192.168.1.50 --key <CAM_KEY> --label 51G12345   (biết trước biển -> ghi luôn nhãn)
"""
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import plate_lib as L  # noqa: E402

OUT = ROOT / "data" / "plates" / "custom"


def grab(url, key, timeout=5):
    q = {"_": str(int(time.time() * 1000))}
    if key:
        q["key"] = key
    with urllib.request.urlopen(f"{url.rstrip('/')}/capture?{urllib.parse.urlencode(q)}", timeout=timeout) as r:
        return cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="http://<ip-esp32>")
    ap.add_argument("--key", default="", help="CAM_KEY trong firmware")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--label", default="", help="biển số của xe đang đặt ở cổng (nếu biết)")
    ap.add_argument("--det", default=str(ROOT / "models" / "plate_det.pt"))
    ap.add_argument("--ocr", default=str(ROOT / "models" / "plate_ocr.pt"))
    args = ap.parse_args()

    (OUT / "frames").mkdir(parents=True, exist_ok=True)
    (OUT / "crops").mkdir(parents=True, exist_ok=True)
    det = ocr = None
    if Path(args.det).exists():
        from ultralytics import YOLO
        det = YOLO(args.det)
    else:
        print("[!] chưa có mô hình phát hiện biển -> chỉ lưu ảnh gốc (data/plates/custom/frames) để tự gán nhãn")
    if Path(args.ocr).exists():
        ocr = torch.jit.load(args.ocr).eval()
        meta = json.loads(Path(args.ocr).with_suffix(".json").read_text(encoding="utf-8"))
    csv_path = OUT / "labels.csv"
    new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["path", "label", "two_rows"])
        for i in range(args.count):
            try:
                img = grab(args.url, args.key)
            except Exception as e:
                print("lỗi chụp:", e)
                time.sleep(args.interval)
                continue
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{i:03d}"
            cv2.imwrite(str(OUT / "frames" / f"{stamp}.jpg"), img)
            n = 0
            if det is not None:
                r = det.predict(img, conf=0.3, verbose=False)[0]
                h, wd = img.shape[:2]
                for j, b in enumerate(r.boxes):
                    x1, y1, x2, y2 = b.xyxy[0].tolist()
                    px, py = (x2 - x1) * .06, (y2 - y1) * .10
                    crop = img[int(max(0, y1 - py)):int(min(h, y2 + py)), int(max(0, x1 - px)):int(min(wd, x2 + px))]
                    two = int(b.cls[0]) == 1
                    guess = L.clean(args.label)
                    if not guess and ocr is not None:
                        with torch.no_grad():
                            x = torch.from_numpy(L.ocr_input(crop, meta, two_rows=two))[None, None]
                            guess = L.decode(ocr(x))[0][0]
                    name = f"crops/{stamp}_{j}.jpg"
                    cv2.imwrite(str(OUT / name), crop)
                    w.writerow([name, guess, int(two)])
                    n += 1
            print(f"[{i + 1}/{args.count}] {stamp}: {n} biển")
            f.flush()
            time.sleep(args.interval)
    print("Xong. Mở", csv_path, "sửa cột label cho đúng (xoá dòng hỏng), rồi chạy lại train_plate.ipynb")


if __name__ == "__main__":
    main()
