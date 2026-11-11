"""Đo xác suất "có xe" của mô hình phân loại (DETECTOR=classifier) trên từng ô và chọn ngưỡng.

Chạy (trong thư mục pc_server):
  python tools/classifier_probe.py anh.jpg                       chỉ in xác suất từng ô
  python tools/classifier_probe.py http://<ip-pi>:8081/snapshot.jpg
  python tools/classifier_probe.py trong.jpg= co_xe.jpg=A1,B2,C4  có nhãn: liệt kê ô CÓ XE sau dấu "=",
                                                                   các ô còn lại coi là trống → đề xuất ngưỡng
  python tools/classifier_probe.py ... --save                    ghi ngưỡng đề xuất vào models/occupancy.json
  python tools/classifier_probe.py --mock 40                     thử trên 40 ảnh Pi giả (xe ngẫu nhiên)

Nguồn video/URL luồng: lấy --frames khung (mặc định 1). Nên có cả ảnh bãi trống lẫn ảnh nhiều ô có xe,
chụp từ đúng camera và góc đặt thật thì ngưỡng mới có ý nghĩa.
"""
import argparse
import json
import random
import sys
import urllib.request
import warnings
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
warnings.filterwarnings("ignore", category=FutureWarning)  # torch.jit.load deprecated

from app import config  # noqa: E402
from app.detector import ClassifierDetector  # noqa: E402
from app.layout import Layout  # noqa: E402


def read_frames(src, n):
    if src.startswith("http") and src.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png")):
        data = np.frombuffer(urllib.request.urlopen(src, timeout=10).read(), np.uint8)
        return [cv2.imdecode(data, cv2.IMREAD_COLOR)]
    if Path(src).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
        img = cv2.imread(src)
        if img is None:
            sys.exit(f"Không đọc được ảnh: {src}")
        return [img]
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened():
        sys.exit(f"Không mở được nguồn: {src}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if Path(src).exists() else 0
    frames = []
    for i in range(n):
        if total > n:  # video: lấy mẫu rải đều
            cap.set(cv2.CAP_PROP_POS_FRAMES, i * total // n)
        ok, f = cap.read()
        if ok:
            frames.append(f)
    cap.release()
    return frames


def mock_samples(layout, n):
    sys.path.insert(0, str(BASE_DIR / "simulator"))
    import mock_pi
    out = []
    for _ in range(n):
        occ = set(random.sample(layout.slot_ids, random.randint(0, len(layout.slot_ids))))
        mock_pi.cars.clear()
        mock_pi.cars.update({sid: random.choice(mock_pi.CAR_COLORS) for sid in occ})
        out.append((mock_pi.render(), occ))
    return out


def parse_slots(layout, text):
    by_label = {layout.label(s).upper(): s for s in layout.slot_ids}
    out = set()
    for tok in filter(None, (t.strip().upper() for t in text.split(","))):
        sid = by_label.get(tok) or (int(tok) if tok.isdigit() and int(tok) in layout.slots else None)
        if sid is None:
            sys.exit(f"Không có ô '{tok}'. Các ô: {', '.join(by_label)}")
        out.add(sid)
    return out


def best_threshold(p, y):
    """Ngưỡng cho balanced accuracy cao nhất; hoà thì lấy điểm giữa khoảng rộng nhất."""
    cands = np.unique(np.concatenate([[0.0, 1.0], p]))
    mids = (cands[:-1] + cands[1:]) / 2
    best, best_score, best_gap = 0.5, -1, -1
    for t, gap in zip(mids, np.diff(cands)):
        pred = p >= t
        tpr = pred[y].mean() if y.any() else 1.0
        tnr = (~pred[~y]).mean() if (~y).any() else 1.0
        score = round((tpr + tnr) / 2, 6)
        if score > best_score or (score == best_score and gap > best_gap):
            best, best_score, best_gap = float(t), score, gap
    return best, best_score


def report(p, y, t, name):
    pred = p >= t
    tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
    fn, tn = int((~pred & y).sum()), int((~pred & ~y).sum())
    print(f"  ngưỡng {t:.3f} ({name}): đúng {tp + tn}/{len(y)} = {(tp + tn) / len(y):.1%}"
          f" | có xe nhận đúng {tp}/{tp + fn}, trống nhận đúng {tn}/{tn + fp}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="ảnh / video / URL, thêm '=A1,B2' để gán nhãn ô có xe")
    ap.add_argument("--frames", type=int, default=1, help="số khung lấy từ video/luồng")
    ap.add_argument("--mock", type=int, default=0, help="số ảnh Pi giả sinh ngẫu nhiên")
    ap.add_argument("--save", action="store_true", help="ghi ngưỡng đề xuất vào file .json của mô hình")
    a = ap.parse_args()
    if not a.sources and not a.mock:
        sys.exit(__doc__)

    layout = Layout(config.LAYOUT_PATH)
    det = ClassifierDetector(layout)
    print(f"Mô hình: {config.CLASSIFIER_MODEL.name}  ngưỡng hiện tại {det.threshold:.3f}  "
          f"temperature {det.temperature:.3f}")

    samples = []  # (tên, frame, tập ô có xe hoặc None)
    for s in a.sources:
        src, labeled, occ = s.partition("=")
        occ = parse_slots(layout, occ) if labeled else None
        for i, f in enumerate(read_frames(src, a.frames)):
            samples.append((f"{Path(src).name}#{i}" if a.frames > 1 else Path(src).name, f, occ))
    for i, (f, occ) in enumerate(mock_samples(layout, a.mock)):
        samples.append((f"mock#{i}", f, occ))

    labels = [layout.label(s) for s in layout.slot_ids]
    print(f"\n{'ảnh':<22}" + "".join(f"{l:>7}" for l in labels))
    ps, ys = [], []
    for name, frame, occ in samples:
        det.detect(frame)
        row = [det.probs[s] for s in layout.slot_ids]
        cells = "".join(f"{v:>6.2f}{'*' if occ and s in occ else ' '}" for v, s in zip(row, layout.slot_ids))
        print(f"{name[:21]:<22}{cells}")
        if occ is not None:
            ps += row
            ys += [s in occ for s in layout.slot_ids]
    print("(* = ô được gán nhãn có xe)")

    if not ys:
        print("\nKhông có nhãn → chỉ in xác suất. Thêm '=A1,B2' (hoặc '=' cho bãi trống) để đề xuất ngưỡng.")
        return
    p, y = np.array(ps), np.array(ys, bool)
    print(f"\nTrên {len(y)} lượt ô có nhãn ({int(y.sum())} có xe, {int((~y).sum())} trống):")
    if y.any():
        print(f"  xác suất ô có xe : min {p[y].min():.3f}  trung vị {np.median(p[y]):.3f}")
    if (~y).any():
        print(f"  xác suất ô trống : max {p[~y].max():.3f}  trung vị {np.median(p[~y]):.3f}")
    t, _ = best_threshold(p, y)
    report(p, y, det.threshold, "hiện tại")
    report(p, y, t, "đề xuất")
    if y.all() or not y.any():
        print("  ⚠ Chỉ có một loại nhãn — cần cả ảnh có xe lẫn bãi trống để chọn ngưỡng đáng tin.")
    else:
        auc = (p[y][:, None] > p[~y][None, :]).mean() + 0.5 * (p[y][:, None] == p[~y][None, :]).mean()
        print(f"  ROC-AUC {auc:.3f} (1.0 = tách hoàn hảo, 0.5 = đoán mò)")
        if auc < 0.5:
            print("  ⚠ Mô hình đang nhận NGƯỢC trên ảnh này (ô có xe điểm thấp hơn ô trống) — "
                  "ảnh quá khác dữ liệu huấn luyện, cần fine-tune.")
        elif p[y].min() <= p[~y].max():
            print("  ⚠ Hai nhóm chồng lấn: không ngưỡng nào tách hết — nên fine-tune mô hình trên ảnh camera này.")

    if a.save:
        if a.mock and not a.sources:
            sys.exit("Không lưu ngưỡng đo trên ảnh Pi giả (sẽ làm sai với camera thật).")
        meta_path = config.CLASSIFIER_META
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["threshold"] = round(t, 4)
        meta["threshold_calibrated_on"] = f"{len(samples)} ảnh, {len(y)} lượt ô (tools/classifier_probe.py)"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã ghi threshold={meta['threshold']} vào {meta_path}")


if __name__ == "__main__":
    main()
