"""Sinh notebook train_plate.ipynb (giữ mã nguồn notebook dễ đọc/diff ở dạng .py). Chạy: python make_plate_notebook.py"""
import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md(r"""
# Nhận diện biển số xe Việt Nam (ALPR) cho cổng bãi xe

Hai mô hình, dùng trong `pc_server/app/plates.py`:

| Bước | Mô hình | Dữ liệu | Xuất ra |
|---|---|---|---|
| 1. Phát hiện biển | **YOLO** (Ultralytics), 2 lớp `plate_1row` / `plate_2row` | VNLP + LP_detection (trungdinh22) | `pc_server/models/plate_det.pt` |
| 2. Đọc ký tự | **CRNN + CTC** (CNN + BiLSTM) | VNLP (~37k biển có nhãn chữ) + biển tổng hợp | `pc_server/models/plate_ocr.pt` + `.json` |

Biển 2 dòng (xe máy, ô tô biển vuông) được **cắt đôi theo chiều cao rồi ghép ngang** trước khi đưa vào CRNN,
nên một mô hình đọc được cả hai loại biển; lớp `plate_1row/2row` của YOLO quyết định có cắt đôi hay không.

Chuẩn bị dữ liệu trước: `python prepare_plates.py` (xem README).
Chạy thử nhanh (vài phút, kết quả không có ý nghĩa): đặt `$env:SMOKE="1"` trước khi mở Jupyter.
""")

code(r"""
import json, os, random, shutil, sys, time
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import ConcatDataset, DataLoader

sys.path.insert(0, str(Path.cwd()))
import plate_lib as L

SMOKE = os.getenv("SMOKE") == "1"
ROOT = Path.cwd()
P = ROOT / "data" / "plates"
RES = ROOT / "results" / "plates"; RES.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "models"; OUT.mkdir(exist_ok=True)
SERVER_MODELS = Path(os.getenv("SERVER_MODELS", r"C:\Users\OS\OneDrive - The University of Technology\IOT_CKY\pc_server\models"))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

CFG = dict(
    # --- phát hiện biển ---
    det_candidates=["yolo11n.pt", "yolo26n.pt", "yolo11s.pt"],   # sàng lọc vài epoch rồi chọn
    det_screen_epochs=3 if SMOKE else 8,
    det_screen_fraction=0.1 if SMOKE else 0.35,                  # sàng lọc trên 35% tập train cho nhanh
    det_epochs=2 if SMOKE else 60,
    det_imgsz=640,
    det_batch=16,                                                # vừa GPU 4 GB (RTX 3050 Ti); hết bộ nhớ thì giảm 8
    det_patience=15,
    # --- đọc ký tự ---
    ocr_epochs=2 if SMOKE else 40,
    ocr_batch=256,
    ocr_lr=2e-3,
    ocr_synth_per_epoch=2000 if SMOKE else 40000,                # biển tổng hợp sinh mới mỗi epoch
    ocr_real_limit=2000 if SMOKE else None,
    ocr_width=1.0,
    workers=min(6, os.cpu_count() or 2),
    seed=42,
)
L.set_seed(CFG["seed"])
print("Thiết bị:", DEVICE, torch.cuda.get_device_name(0) if DEVICE == "cuda" else "",
      "| torch", torch.__version__, "| SMOKE" if SMOKE else "")
CFG
""")

md("## 1. Khám phá dữ liệu")
code(r"""
import ultralytics
from ultralytics import YOLO
print("ultralytics", ultralytics.__version__)
DET_YAML = P / "det" / "plates.yaml"
assert DET_YAML.exists(), "Chưa có dữ liệu: chạy python prepare_plates.py"

def det_stats(split):
    labs = list((P / "det" / "labels" / split).glob("*.txt"))
    c = {0: 0, 1: 0}; src = {"vnlp": 0, "lpd": 0}
    for f in labs:
        src["vnlp" if f.name.startswith("vnlp") else "lpd"] += 1
        for ln in f.read_text().split("\n"):
            if ln.strip(): c[int(ln.split()[0])] += 1
    return {"ảnh": len(labs), "VNLP": src["vnlp"], "LP_detection": src["lpd"], "biển 1 dòng": c[0], "biển 2 dòng": c[1]}

det_df = pd.DataFrame({s: det_stats(s) for s in ("train", "val", "test")}).T
ocr = {s: pd.read_csv(P / "ocr" / f"{s}.csv") for s in ("train", "val", "test")}
ocr_df = pd.DataFrame({s: {"biển": len(d), "1 dòng": int((d.two_rows == 0).sum()), "2 dòng": int((d.two_rows == 1).sum()),
                           "số biển khác nhau": d.label.nunique()} for s, d in ocr.items()}).T
display(det_df); display(ocr_df)
lens = ocr["train"].label.str.len().value_counts().sort_index()
prov = ocr["train"].label.str[:2].value_counts().head(12)
fig, ax = plt.subplots(1, 2, figsize=(12, 3.2))
lens.plot.bar(ax=ax[0], title="Độ dài chuỗi biển (train)"); prov.plot.bar(ax=ax[1], title="12 mã tỉnh nhiều nhất (train)")
plt.tight_layout(); plt.savefig(RES / "eda.png", dpi=110); plt.show()
""")
code(r"""
# ảnh mẫu: tập phát hiện (có khung) và ảnh biển cắt cho OCR
fig, axes = plt.subplots(2, 4, figsize=(16, 6))
imgs = sorted((P / "det" / "images" / "train").glob("*"))
random.Random(1).shuffle(imgs)
pick = [p for p in imgs if p.name.startswith("vnlp")][:2] + [p for p in imgs if p.name.startswith("lpd")][:2]
for ax, p in zip(axes[0], pick):
    im = cv2.imread(str(p)); h, w = im.shape[:2]
    for ln in (P / "det" / "labels" / "train" / (p.stem + ".txt")).read_text().split("\n"):
        if not ln.strip(): continue
        c, cx, cy, bw, bh = map(float, ln.split())
        cv2.rectangle(im, (int((cx - bw / 2) * w), int((cy - bh / 2) * h)), (int((cx + bw / 2) * w), int((cy + bh / 2) * h)),
                      (0, 255, 0) if c == 0 else (255, 0, 255), 3)
    ax.imshow(im[..., ::-1]); ax.set_title(p.name[:22]); ax.axis("off")
for ax, (_, r) in zip(axes[1], ocr["train"].sample(4, random_state=3).iterrows()):
    ax.imshow(cv2.imread(str(P / "ocr" / r.path))[..., ::-1]); ax.set_title(f"{r.label} ({'2 dòng' if r.two_rows else '1 dòng'})"); ax.axis("off")
plt.tight_layout(); plt.savefig(RES / "samples.png", dpi=100); plt.show()
""")

md(r"""
## 2. Phát hiện biển số (YOLO)

**Sàng lọc**: mỗi kiến trúc train vài epoch trên một phần dữ liệu, so mAP50-95 trên val **và** thời gian chạy CPU
(server có thể không có GPU). Chọn mô hình có mAP cao nhất trong nhóm đủ nhanh (< 150 ms/ảnh trên CPU).
""")
code(r"""
def cpu_ms(weights, n=15):
    m = YOLO(weights)
    im = np.random.randint(0, 255, (768, 1024, 3), np.uint8)
    m.predict(im, imgsz=CFG["det_imgsz"], device="cpu", verbose=False)
    t = time.perf_counter()
    for _ in range(n): m.predict(im, imgsz=CFG["det_imgsz"], device="cpu", verbose=False)
    return (time.perf_counter() - t) / n * 1000

screen = []
for arch in CFG["det_candidates"]:
    name = "screen_" + Path(arch).stem
    try:
        m = YOLO(arch)
        r = m.train(data=str(DET_YAML), epochs=CFG["det_screen_epochs"], imgsz=CFG["det_imgsz"], batch=CFG["det_batch"],
                    fraction=CFG["det_screen_fraction"], workers=CFG["workers"], device=0 if DEVICE == "cuda" else "cpu",
                    project=str(RES / "det_runs"), name=name, exist_ok=True, plots=False, verbose=False, seed=CFG["seed"])
        best = RES / "det_runs" / name / "weights" / "best.pt"
        v = YOLO(best).val(data=str(DET_YAML), split="val", imgsz=CFG["det_imgsz"], batch=CFG["det_batch"], verbose=False, plots=False)
        screen.append({"model": Path(arch).stem, "mAP50": v.box.map50, "mAP50-95": v.box.map, "cpu_ms": cpu_ms(best),
                       "params_M": sum(p.numel() for p in YOLO(best).model.parameters()) / 1e6})
    except Exception as e:  # kiến trúc không có trong bản ultralytics đang cài
        print("bỏ qua", arch, "->", e)
screen_df = pd.DataFrame(screen).sort_values("mAP50-95", ascending=False)
screen_df.to_csv(RES / "det_screening.csv", index=False)
display(screen_df)
fast = screen_df[screen_df.cpu_ms < 150]
DET_ARCH = (fast if len(fast) else screen_df).iloc[0]["model"] + ".pt"
print("Chọn:", DET_ARCH)
""")
code(r"""
# huấn luyện đầy đủ mô hình được chọn
det = YOLO(DET_ARCH)
det.train(data=str(DET_YAML), epochs=CFG["det_epochs"], imgsz=CFG["det_imgsz"], batch=CFG["det_batch"],
          patience=CFG["det_patience"], workers=CFG["workers"], device=0 if DEVICE == "cuda" else "cpu",
          cos_lr=True, close_mosaic=10, degrees=5, perspective=0.0005, fliplr=0.0,   # lật ngang làm ngược chữ -> tắt
          hsv_v=0.5, scale=0.6, project=str(RES / "det_runs"), name="final", exist_ok=True, seed=CFG["seed"])
DET_BEST = RES / "det_runs" / "final" / "weights" / "best.pt"
hist = pd.read_csv(RES / "det_runs" / "final" / "results.csv"); hist.columns = hist.columns.str.strip()
fig, ax = plt.subplots(1, 2, figsize=(12, 3.5))
hist[["train/box_loss", "val/box_loss"]].plot(ax=ax[0], title="Box loss")
hist[["metrics/mAP50(B)", "metrics/mAP50-95(B)"]].plot(ax=ax[1], title="mAP trên val")
plt.tight_layout(); plt.savefig(RES / "det_curves.png", dpi=110); plt.show()
""")
code(r"""
# đánh giá trên tập test (biển số chưa từng thấy khi train)
vt = YOLO(DET_BEST).val(data=str(DET_YAML), split="test", imgsz=CFG["det_imgsz"], batch=CFG["det_batch"],
                        project=str(RES / "det_runs"), name="test", exist_ok=True)
det_metrics = {"precision": float(vt.box.mp), "recall": float(vt.box.mr), "mAP50": float(vt.box.map50),
               "mAP50-95": float(vt.box.map), "cpu_ms_1024x768": cpu_ms(DET_BEST)}
per_class = pd.DataFrame({"lớp": ["plate_1row", "plate_2row"], "mAP50-95": [float(x) for x in vt.box.maps[:2]]})
display(pd.Series(det_metrics).round(4)); display(per_class)

# độ bền với ảnh nhỏ/mờ/tối kiểu ESP32-CAM
test_imgs = sorted((P / "det" / "images" / "test").glob("*"))[: (60 if SMOKE else 400)]
def corrupt(im, kind):
    if kind == "gốc": return im
    if kind == "nhỏ (x0.4)": h, w = im.shape[:2]; return cv2.resize(cv2.resize(im, (int(w * .4), int(h * .4))), (w, h))
    if kind == "mờ": return cv2.GaussianBlur(im, (7, 7), 0)
    if kind == "tối": return (im * 0.35).astype(np.uint8)
    if kind == "JPEG q15": return cv2.imdecode(cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 15])[1], 1)
m = YOLO(DET_BEST); rob = []
for kind in ["gốc", "nhỏ (x0.4)", "mờ", "tối", "JPEG q15"]:
    hit = 0
    for p in test_imgs:
        im = corrupt(cv2.imread(str(p)), kind)
        gt = [list(map(float, l.split())) for l in (P / "det" / "labels" / "test" / (p.stem + ".txt")).read_text().split("\n") if l.strip()]
        r = m.predict(im, imgsz=CFG["det_imgsz"], conf=0.35, verbose=False)[0]
        h, w = im.shape[:2]
        boxes = r.boxes.xyxy.cpu().numpy() if len(r.boxes) else np.zeros((0, 4))
        for c, cx, cy, bw, bh in gt:
            g = np.array([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
            if len(boxes):
                ix = np.clip(np.minimum(boxes[:, 2], g[2]) - np.maximum(boxes[:, 0], g[0]), 0, None)
                iy = np.clip(np.minimum(boxes[:, 3], g[3]) - np.maximum(boxes[:, 1], g[1]), 0, None)
                inter = ix * iy; uni = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]) + (g[2] - g[0]) * (g[3] - g[1]) - inter
                hit += (inter / uni).max() >= 0.5
    rob.append({"biến đổi": kind, "recall@IoU0.5": hit / max(1, sum(len([l for l in (P / "det" / "labels" / "test" / (p.stem + ".txt")).read_text().split("\n") if l.strip()]) for p in test_imgs))})
rob_df = pd.DataFrame(rob); display(rob_df); rob_df.to_csv(RES / "det_robustness.csv", index=False)
""")

md(r"""
## 3. Đọc ký tự (CRNN + CTC)

Huấn luyện trên **ảnh biển thật** (VNLP, chia theo biển số) **trộn với biển tổng hợp** sinh mới mỗi epoch
(đủ định dạng: biển dài, biển vuông ô tô, xe máy; nền trắng/vàng; thu nhỏ, mờ, nghiêng, nhiễu, nén JPEG
để giống ảnh ESP32-CAM). Đánh giá trên **VNLP test** (biển thật chưa thấy) và tập tổng hợp cố định.
""")
code(r"""
def items(df):
    return [(P / "ocr" / r.path, r.label, r.two_rows) for r in df.itertuples()]
real_train = items(ocr["train"]); real_val = items(ocr["val"]); real_test = items(ocr["test"])
if CFG["ocr_real_limit"]:
    real_train, real_val, real_test = real_train[:CFG["ocr_real_limit"]], real_val[:500], real_test[:500]
renderer = L.PlateRenderer()
custom_csv = P / "custom" / "labels.csv"   # ảnh biển tự thu bằng ESP32-CAM (collect_plates.py) nếu có
custom = []
if custom_csv.exists():
    cdf = pd.read_csv(custom_csv)
    custom = [(P / "custom" / r.path, L.clean(r.label), int(r.two_rows)) for r in cdf.itertuples()]
    print("Ảnh tự thu:", len(custom))
train_ds = ConcatDataset([L.CropOCR(real_train + custom * 5, train=True),
                          L.SyntheticOCR(CFG["ocr_synth_per_epoch"], renderer=renderer)])
mk = lambda ds, sh: DataLoader(ds, batch_size=CFG["ocr_batch"], shuffle=sh, num_workers=CFG["workers"],
                               collate_fn=L.collate, worker_init_fn=L.worker_init, persistent_workers=CFG["workers"] > 0,
                               pin_memory=DEVICE == "cuda")
train_dl = mk(train_ds, True)
val_dl = mk(L.CropOCR(real_val, train=False), False)
test_dl = mk(L.CropOCR(real_test, train=False), False)
synth_test_dl = mk(L.SyntheticOCR(500 if SMOKE else 3000, seed=12345, renderer=renderer), False)
print(f"train: {len(real_train)} thật + {CFG['ocr_synth_per_epoch']} tổng hợp/epoch | val {len(real_val)} | test {len(real_test)}")
""")
code(r"""
model = L.CRNN(width=CFG["ocr_width"]).to(DEVICE)
print("Tham số:", sum(p.numel() for p in model.parameters()) / 1e6, "M")
opt = torch.optim.AdamW(model.parameters(), lr=CFG["ocr_lr"], weight_decay=1e-4)
steps = CFG["ocr_epochs"] * len(train_dl)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=CFG["ocr_lr"], total_steps=steps, pct_start=0.1)
scaler = torch.amp.GradScaler(enabled=DEVICE == "cuda")
best_acc, history, bad = -1, [], 0
for ep in range(CFG["ocr_epochs"]):
    model.train(); t0 = time.time(); tot = n = 0
    for x, tg, ln, _ in train_dl:
        x, tg, ln = x.to(DEVICE, non_blocking=True), tg.to(DEVICE), ln.to(DEVICE)
        with torch.autocast(DEVICE, dtype=torch.float16, enabled=DEVICE == "cuda"):
            logits = model(x)
        loss = L.ctc_loss(logits, tg, ln)
        opt.zero_grad(set_to_none=True); scaler.scale(loss).backward()
        scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scaler.step(opt); scaler.update(); sched.step()
        tot += loss.item() * len(x); n += len(x)
    vm, _ = L.evaluate_ocr(model, val_dl, DEVICE)
    history.append({"epoch": ep + 1, "train_loss": tot / n, **{f"val_{k}": v for k, v in vm.items()}, "sec": time.time() - t0})
    print(f"epoch {ep + 1:2d}  loss {tot / n:.4f}  val acc {vm['accuracy']:.4f}  CER {vm['cer']:.4f}  ({time.time() - t0:.0f}s)")
    if vm["accuracy"] > best_acc:
        best_acc, bad = vm["accuracy"], 0
        torch.save(model.state_dict(), OUT / "plate_ocr_best.pth")
    else:
        bad += 1
        if bad >= 8: print("dừng sớm"); break
hist_ocr = pd.DataFrame(history); hist_ocr.to_csv(RES / "ocr_history.csv", index=False)
fig, ax = plt.subplots(1, 2, figsize=(12, 3.5))
hist_ocr.plot(x="epoch", y=["train_loss", "val_loss"], ax=ax[0], title="CTC loss")
hist_ocr.plot(x="epoch", y=["val_accuracy"], ax=ax[1], title="Đúng cả biển (val)")
plt.tight_layout(); plt.savefig(RES / "ocr_curves.png", dpi=110); plt.show()
""")
code(r"""
model.load_state_dict(torch.load(OUT / "plate_ocr_best.pth", map_location=DEVICE))
tm, rows = L.evaluate_ocr(model, test_dl, DEVICE)
sm, _ = L.evaluate_ocr(model, synth_test_dl, DEVICE)
res = pd.DataFrame(rows, columns=["label", "pred", "conf"])
res["two_rows"] = [it[2] for it in real_test[:len(res)]]
res["ok"] = res.label == res.pred
by_type = res.groupby(res.two_rows.map({0: "1 dòng", 1: "2 dòng"})).ok.mean().rename("đúng cả biển")
ocr_metrics = {"test_accuracy": tm["accuracy"], "test_cer": tm["cer"], "synthetic_accuracy": sm["accuracy"],
               "acc_1row": float(by_type.get("1 dòng", np.nan)), "acc_2row": float(by_type.get("2 dòng", np.nan))}
display(pd.Series(ocr_metrics).round(4))
# ngưỡng tin cậy: độ chính xác khi chỉ chấp nhận kết quả có conf >= t (server dùng PLATE_MIN_CONF)
cov = pd.DataFrame([{"ngưỡng": t, "tỉ lệ chấp nhận": (res.conf >= t).mean(),
                     "đúng trong số chấp nhận": res[res.conf >= t].ok.mean()} for t in (0.0, 0.3, 0.5, 0.7, 0.9)])
display(cov.round(4)); cov.to_csv(RES / "ocr_confidence.csv", index=False)
errs = res[~res.ok].sort_values("conf", ascending=False).head(12)
display(errs)
""")
code(r"""
# ảnh lỗi tự tin nhất
fig, axes = plt.subplots(3, 4, figsize=(14, 6))
for ax, (_, r) in zip(axes.flat, errs.iterrows()):
    p = [it for it in real_test if it[1] == r.label][0][0]
    ax.imshow(cv2.imread(str(p))[..., ::-1]); ax.set_title(f"đúng {r.label}\nđoán {r.pred} ({r.conf:.2f})", fontsize=9); ax.axis("off")
plt.tight_layout(); plt.savefig(RES / "ocr_errors.png", dpi=100); plt.show()
# tốc độ CPU cho 1 biển
cpu_model = L.CRNN(width=CFG["ocr_width"]).eval(); cpu_model.load_state_dict(model.state_dict())
x = torch.zeros(1, 1, 48, 192)
with torch.no_grad():
    for _ in range(5): cpu_model(x)
    t = time.perf_counter()
    for _ in range(50): cpu_model(x)
ocr_metrics["cpu_ms_per_plate"] = (time.perf_counter() - t) / 50 * 1000
print(f"CPU: {ocr_metrics['cpu_ms_per_plate']:.1f} ms / biển")
""")

md(r"""
## 4. Đánh giá toàn bộ pipeline (ảnh gốc -> chuỗi biển)

Chạy đúng như server: YOLO -> cắt biển có lề -> OCR -> sửa nhầm chữ/số theo vị trí -> kiểm tra định dạng.
Tính trên ảnh VNLP test (ảnh đầy đủ, biển chưa thấy).
""")
code(r"""
srv_path = Path(r"C:\Users\OS\OneDrive - The University of Technology\IOT_CKY\pc_server")
sys.path.insert(0, str(srv_path))
from app.plates import fix_plate, is_valid as srv_valid   # dùng đúng hàm hậu xử lý của server
m = YOLO(DET_BEST)
ocr_cpu = cpu_model
e2e = []
imgs = [p for p in sorted((P / "det" / "images" / "test").glob("vnlp_*.jpg"))][: (100 if SMOKE else 1500)]
crop_label = {Path(r.path).stem: (r.label, r.two_rows) for r in ocr["test"].itertuples()}
for p in imgs:
    gt = crop_label.get(p.stem)
    if not gt: continue
    im = cv2.imread(str(p)); h, w = im.shape[:2]
    r = m.predict(im, imgsz=CFG["det_imgsz"], conf=0.35, verbose=False)[0]
    pred, conf = "", 0.0
    if len(r.boxes):
        b = r.boxes[int(r.boxes.conf.argmax())]
        x1, y1, x2, y2 = b.xyxy[0].tolist(); px, py = (x2 - x1) * .06, (y2 - y1) * .10
        crop = im[int(max(0, y1 - py)):int(min(h, y2 + py)), int(max(0, x1 - px)):int(min(w, x2 + px))]
        two = int(b.cls[0]) == 1
        with torch.no_grad():
            out = L.decode(ocr_cpu(torch.from_numpy(L.ocr_input(crop, two_rows=two))[None, None]))[0]
        pred, conf = fix_plate(out[0]), out[1] * float(b.conf[0])
    e2e.append({"label": gt[0], "pred": pred, "conf": conf, "valid": srv_valid(pred), "ok": pred == gt[0]})
e2e = pd.DataFrame(e2e)
e2e_metrics = {"end_to_end_accuracy": e2e.ok.mean(), "found_plate": (e2e.pred != "").mean(),
               "acc_when_conf>=0.5": e2e[e2e.conf >= .5].ok.mean(), "accepted_conf>=0.5": (e2e.conf >= .5).mean()}
display(pd.Series(e2e_metrics).round(4))
""")

md(r"""
## 5. Xuất mô hình cho server

- `plate_det.pt`: trọng số YOLO tốt nhất (Ultralytics nạp trực tiếp).
- `plate_ocr.pt`: CRNN dạng **TorchScript** (server không cần mã nguồn mô hình) + `plate_ocr.json`
  (bảng chữ, kích thước ảnh, chuẩn hóa — `ocr_input()` của server đọc file này) và các chỉ số đánh giá.
""")
code(r"""
meta = {**L.OCR_META, "alphabet": L.ALPHABET, "arch": f"CRNN(width={CFG['ocr_width']}) + CTC",
        "det_arch": DET_ARCH, "det_metrics": det_metrics, "ocr_metrics": ocr_metrics, "e2e_metrics": e2e_metrics,
        "datasets": ["VNLP (fict-labs)", "LP_detection (trungdinh22)", "biển tổng hợp (font NNDam)"],
        "custom_images": len(custom), "created": time.strftime("%Y-%m-%d %H:%M"), "smoke": SMOKE}
meta = json.loads(json.dumps(meta, default=float))
shutil.copy(DET_BEST, OUT / "plate_det.pt")
L.export_ocr(cpu_model, OUT / "plate_ocr.pt", meta)
(RES / "metrics.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
# kiểm tra file TorchScript cho kết quả giống mô hình gốc
ts = torch.jit.load(str(OUT / "plate_ocr.pt"))
x = torch.randn(4, 1, 48, 192)
with torch.no_grad(): assert torch.allclose(ts(x), cpu_model(x), atol=1e-4)
if SERVER_MODELS.exists() and not SMOKE:
    for f in ("plate_det.pt", "plate_ocr.pt", "plate_ocr.json"):
        shutil.copy(OUT / f, SERVER_MODELS / f)
    print("Đã chép vào", SERVER_MODELS, "-> trên dashboard: Thiết bị -> Nạp lại mô hình")
else:
    print("Mô hình ở", OUT, "(SMOKE hoặc không thấy thư mục server: tự chép plate_det.pt, plate_ocr.pt, plate_ocr.json)")
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "parking-train", "display_name": "Python (parking-train)", "language": "python"}})
nbf.write(nb, "train_plate.ipynb")
print("đã tạo train_plate.ipynb với", len(cells), "ô")
