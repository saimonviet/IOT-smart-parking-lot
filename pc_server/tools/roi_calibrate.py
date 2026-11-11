"""Vẽ lại vùng ROI của các ô trên ảnh camera thật và ghi vào config/layout.json.

Chạy:  python tools/roi_calibrate.py http://<ip-pi>:8081/snapshot.jpg      (hoặc đường dẫn ảnh)
Với mỗi ô (theo thứ tự id: A1, A2, A3, B1 … C4): bấm 4 góc (theo chiều bất kỳ). Phím  u = làm lại ô hiện tại,  s = bỏ qua ô (giữ cũ),  q = thoát không lưu.
Cần opencv-python (bản có giao diện):  pip uninstall opencv-python-headless && pip install opencv-python
Chỉ thay ROI; các nút đường đi (nodes) giữ nguyên — nếu bố cục bãi khác, chỉnh thêm nodes trong layout.json.
"""
import json
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

LAYOUT = Path(__file__).resolve().parent.parent / "config" / "layout.json"


def load(src):
    if src.startswith("http"):
        data = np.frombuffer(urllib.request.urlopen(src, timeout=10).read(), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    return cv2.imread(src)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    img = load(sys.argv[1])
    h, w = img.shape[:2]
    layout = json.loads(LAYOUT.read_text())
    slots = {s["id"]: s for s in layout["slots"]}
    new = {}
    pts = []

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append([x, y])

    cv2.namedWindow("ROI")
    cv2.setMouseCallback("ROI", on_mouse)
    for sid in sorted(slots):
        pts.clear()
        while True:
            view = img.copy()
            for roi in new.values():
                cv2.polylines(view, [np.array(roi, np.int32)], True, (0, 200, 0), 2)
            for p in pts:
                cv2.circle(view, tuple(p), 4, (0, 0, 255), -1)
            if len(pts) > 1:
                cv2.polylines(view, [np.array(pts, np.int32)], len(pts) == 4, (0, 255, 255), 2)
            cv2.putText(view, f"O {slots[sid].get('label', sid)}: bam 4 goc  (u=lam lai, s=bo qua, q=thoat)", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imshow("ROI", view)
            k = cv2.waitKey(30) & 0xFF
            if k == ord("q"):
                return
            if k == ord("u"):
                pts.clear()
            if k == ord("s"):
                new[sid] = slots[sid]["roi"]
                break
            if len(pts) == 4:
                cx, cy = np.mean(pts, axis=0)
                new[sid] = sorted(pts, key=lambda p: np.arctan2(p[1] - cy, p[0] - cx))  # thứ tự đa giác
                break
    for sid, roi in new.items():
        slots[sid]["roi"] = [list(map(int, p)) for p in roi]
    layout["frame"] = {"width": w, "height": h}
    LAYOUT.write_text(json.dumps(layout, indent=1))
    print(f"Đã lưu {LAYOUT} (khung {w}x{h}). Khởi động lại server để áp dụng.")


if __name__ == "__main__":
    main()
