"""In biển số Việt Nam (đúng font, đúng định dạng) để dán lên xe mô hình.

Dùng cùng bộ vẽ với dữ liệu tổng hợp khi huấn luyện OCR -> biển in ra giống dữ liệu mô hình đã học.
Kết quả: data/plates/print/bien_so_A4.png (300 dpi, in đúng tỉ lệ 100%) + danh sách biển trong .txt

  python print_plates.py --plates 51G12345 30A98765 59X123456 --width-mm 40
  python print_plates.py --random 12 --width-mm 35
  python print_plates.py --random 6 --color yellow        (biển vàng xe kinh doanh)

Chọn cỡ: biển phải rộng >= ~120 px trong ảnh ESP32-CAM (XGA 1024 px, góc nhìn ~66°)
  -> chiều rộng biển (mm) >= 1.5 x khoảng cách camera-biển (cm). Vd. camera cách 25 cm -> biển >= 38 mm.
"""
import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import plate_lib as L  # noqa: E402

DPI = 300
A4 = (int(210 / 25.4 * DPI), int(297 / 25.4 * DPI))  # (rộng, cao) px


def layout(label):
    """Chuỗi chuẩn hóa -> (dòng trên, dòng dưới, loại) theo định dạng thật."""
    m = L.PLATE_RE.match(label)
    if not m:
        raise ValueError(f"{label}: sai định dạng (vd. 51G12345, 59X123456)")
    prov, series, num = m.groups()
    num_s = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
    if len(series) == 2 and series[1].isdigit():
        return f"{prov}-{series}", num_s, "moto"
    return f"{prov}{series}-{num_s}", None, "car_long"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plates", nargs="*", default=[])
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--width-mm", type=float, default=40, help="chiều rộng biển dài khi in (mm)")
    ap.add_argument("--square", action="store_true", help="in biển ô tô dạng vuông 2 dòng")
    ap.add_argument("--color", choices=["white", "yellow"], default="white", help="white = xe cá nhân | yellow = xe kinh doanh")
    args = ap.parse_args()
    labels = [L.clean(p) for p in args.plates]
    while len(labels) < len(args.plates) + args.random:
        lab, _, _, kind = L.random_plate()
        if kind != "moto" or random.random() < 0.3:
            labels.append(lab)
    r = L.PlateRenderer()
    bg_color = (255, 255, 255) if args.color == "white" else (40, 200, 245)   # BGR

    def base(kind, w, h):
        bg = np.full((h, w, 3), bg_color, np.uint8)
        t = max(2, h // 28)
        cv2.rectangle(bg, (t, t), (w - t - 1, h - t - 1), (20, 20, 20), t)
        return bg
    r._base = base
    page = np.full((A4[1], A4[0], 3), 255, np.uint8)
    margin = int(10 / 25.4 * DPI)
    x, y, row_h = margin, margin, 0
    for lab in labels:
        top, bottom, kind = layout(lab)
        if args.square and kind == "car_long":
            m = L.PLATE_RE.match(lab)
            num = m.group(3)
            top, bottom, kind = m.group(1) + m.group(2), (f"{num[:3]}.{num[3:]}" if len(num) == 5 else num), "car_square"
        # nền màu đồng nhất + viền đen (không lấy ảnh nền / màu ngẫu nhiên)
        random.seed(0)
        img = r.render(top, bottom, kind)
        wmm = args.width_mm if kind == "car_long" else args.width_mm * (330 / 520 if kind == "car_square" else 280 / 520)
        wpx = int(wmm / 25.4 * DPI)
        img = cv2.resize(img, (wpx, int(img.shape[0] * wpx / img.shape[1])), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
        if x + w > A4[0] - margin:
            x, y, row_h = margin, y + row_h + margin // 2, 0
        if y + h > A4[1] - margin:
            print("[!] hết trang, bỏ bớt biển")
            break
        page[y:y + h, x:x + w] = img
        cv2.putText(page, lab, (x, y + h + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)
        x += w + margin // 2
        row_h = max(row_h, h + 40)
    out = ROOT / "data" / "plates" / "print"
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "bien_so_A4.png"), page)
    (out / "bien_so.txt").write_text("\n".join(labels), encoding="utf-8")
    print("Đã tạo", out / "bien_so_A4.png", f"({len(labels)} biển) — in ở tỉ lệ 100% / Actual size, 300 dpi")


if __name__ == "__main__":
    main()
