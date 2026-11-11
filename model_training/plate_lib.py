"""Thư viện huấn luyện nhận diện biển số Việt Nam: sinh biển tổng hợp, dữ liệu OCR, mô hình CRNN-CTC, đánh giá.

Đặt trong file .py (không trong notebook) để DataLoader nhiều worker chạy được trên Windows.

Pipeline dùng trong pc_server/app/plates.py:
  ảnh ESP32-CAM -> YOLO (plate_det.pt) phát hiện biển -> cắt biển -> ocr_input() -> CRNN (plate_ocr.pt) -> CTC greedy.
Biển 2 dòng (vuông) được cắt đôi theo chiều cao rồi ghép ngang thành 1 dòng -> một mô hình đọc được cả 2 loại biển.
"""
import math
import random
import re
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
from torch.utils.data import Dataset

ROOT = Path(__file__).resolve().parent
GEN_DIR = ROOT / "data" / "plates" / "generator"   # NNDam/Vietnamese-License-Plate-Generator (font + nền)

# Biển VN không dùng I, J, O, Q, W -> bỏ khỏi bảng chữ để mô hình không nhầm O/0, I/1
ALPHABET = "0123456789ABCDEFGHKLMNPRSTUVXYZ"
CHAR2IDX = {c: i + 1 for i, c in enumerate(ALPHABET)}  # 0 = blank (CTC)
PLATE_RE = re.compile(r"^(\d{2})([A-Z]{1,2}|[A-Z]\d)(\d{4,5})$")
OCR_META = {"img_h": 48, "img_w": 192, "split_ratio": 2.2, "mean": 0.5, "std": 0.5}


def clean(text):
    return re.sub(r"[^0-9A-Z]", "", str(text).upper())


def is_valid(plate):
    return bool(PLATE_RE.match(plate or ""))


# ============================================================ tiền xử lý (GIỐNG HỆT pc_server/app/plates.py)
def ocr_input(crop, meta=OCR_META, two_rows=None):
    """two_rows: lớp do YOLO phát hiện (biển 1 dòng / 2 dòng); None = đoán theo tỉ lệ rộng/cao."""
    H, W = meta["img_h"], meta["img_w"]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = g.shape[:2]
    if two_rows is None:
        two_rows = w / max(h, 1) < meta.get("split_ratio", 2.2)
    if two_rows:
        ov = int(h * 0.04)
        top, bot = g[: h // 2 + ov], g[h // 2 - ov:]
        g = np.hstack([cv2.resize(top, (W // 2, H)), cv2.resize(bot, (W // 2, H))])
    else:
        g = cv2.resize(g, (W, H))
    x = g.astype(np.float32) / 255.0
    return (x - meta.get("mean", 0.5)) / meta.get("std", 0.5)


# ============================================================ sinh biển số tổng hợp
PROVINCES = [11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
             37, 38, 40, 43, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67,
             68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 81, 82, 83, 84, 85, 86, 88, 89, 90, 92, 93, 94, 95,
             97, 98, 99]
SERIES = "ABCDEFGHKLMNPRSTUVXYZ"


def random_plate():
    """Trả về (chuỗi chuẩn hóa, dòng trên, dòng dưới hoặc None, loại)."""
    prov = f"{random.choice(PROVINCES):02d}"
    d = lambda n: "".join(random.choice("0123456789") for _ in range(n))
    r = random.random()
    if r < 0.38:    # ô tô biển dài: 51G-123.45 / 51G-1234 / 30LD-123.45
        series = random.choice(SERIES) + (random.choice(SERIES) if random.random() < 0.12 else "")
        num = d(5) if random.random() < 0.85 else d(4)
        num_s = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
        return prov + series + num, f"{prov}{series}-{num_s}", None, "car_long"
    if r < 0.58:    # ô tô biển vuông: 51G / 123.45
        series = random.choice(SERIES) + (random.choice(SERIES) if random.random() < 0.1 else "")
        num = d(5) if random.random() < 0.85 else d(4)
        num_s = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
        return prov + series + num, f"{prov}{series}", num_s, "car_square"
    # xe máy: 59-X1 / 234.56 ; 29-AB / 123.45 ; cũ: 59-X1 / 2345
    series = random.choice(SERIES) + (random.choice("123456789") if random.random() < 0.8 else random.choice(SERIES))
    num = d(5) if random.random() < 0.8 else d(4)
    num_s = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
    return prov + series + num, f"{prov}-{series}", num_s, "moto"


class PlateRenderer:
    """Vẽ biển số kiểu Việt Nam (nền trắng / vàng, viền đen, font biển số) bằng font của NNDam generator."""

    def __init__(self, gen_dir=GEN_DIR):
        gen_dir = Path(gen_dir)
        self.font_path = str(gen_dir / "MyFont-Regular_ver3.otf")
        self.bgs = {k: [cv2.imread(str(p)) for p in sorted((gen_dir / "background").glob(f"{k}*.jpg"))]
                    for k in ("rec", "square")}
        self._fonts = {}

    def __getstate__(self):  # DataLoader trên Windows pickle đối tượng sang worker: bỏ cache font
        d = dict(self.__dict__)
        d["_fonts"] = {}
        return d

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size)
        return self._fonts[size]

    def _base(self, kind, w, h):
        pool = self.bgs["rec" if kind == "car_long" else "square"]
        if pool and random.random() < 0.5:
            bg = cv2.resize(random.choice(pool), (w, h))
        else:
            color = (255, 255, 255) if random.random() < 0.75 else (40, 200, 245)  # trắng / vàng (xe kinh doanh)
            color = tuple(int(np.clip(c + random.randint(-25, 10), 0, 255)) for c in color)
            bg = np.full((h, w, 3), color, np.uint8)
            t = max(2, h // 28)
            cv2.rectangle(bg, (t, t), (w - t - 1, h - t - 1), (20, 20, 20), t)
        return bg

    def _text(self, img, text, box):
        """Vẽ chữ căn giữa trong box (x1, y1, x2, y2), co giãn theo chiều ngang cho vừa."""
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        f = self.font(int(bh * 1.15))
        l, t, r, b = f.getbbox(text)
        tw, th = r - l, b - t
        canvas = Image.new("L", (tw + 4, th + 4), 0)
        ImageDraw.Draw(canvas).text((2 - l, 2 - t), text, font=f, fill=255)
        mask = np.array(canvas)
        scale_w = min(bw * random.uniform(0.86, 0.96), tw * bh / th * 1.1)
        mask = cv2.resize(mask, (max(4, int(scale_w)), max(4, int(bh * random.uniform(0.84, 0.94)))))
        mh, mw = mask.shape
        ox, oy = x1 + (bw - mw) // 2, y1 + (bh - mh) // 2
        ink = np.array([random.randint(0, 40)] * 3, np.float32)
        region = img[oy:oy + mh, ox:ox + mw].astype(np.float32)
        a = (mask.astype(np.float32) / 255.0)[..., None]
        img[oy:oy + mh, ox:ox + mw] = (region * (1 - a) + ink * a).astype(np.uint8)

    def render(self, top, bottom, kind):
        if kind == "car_long":
            w, h = 520, 110
            img = self._base(kind, w, h)
            self._text(img, top, (14, 10, w - 14, h - 10))
        else:
            w, h = (330, 165) if kind == "car_square" else (280, 200)
            img = self._base(kind, w, h)
            m = int(h * 0.07)
            self._text(img, top, (12, m, w - 12, h // 2 - m // 3))
            self._text(img, bottom, (12, h // 2 + m // 3, w - 12, h - m))
        return img

    def sample(self):
        label, top, bottom, kind = random_plate()
        return self.render(top, bottom, kind), label, kind


# ============================================================ tăng cường ảnh (giả lập ESP32-CAM: nhỏ, mờ, nén JPEG)
def augment_plate(img, strong=True, synthetic=True):
    h, w = img.shape[:2]
    if synthetic:
        # lề quanh biển giống khung YOLO + padding của server (6% ngang, 10% dọc), có xê dịch
        px, py = int(w * random.uniform(0.0, 0.14)), int(h * random.uniform(0.0, 0.22))
        border = tuple(int(v) for v in np.random.randint(0, 255, 3))
        img = cv2.copyMakeBorder(img, py, py, px, px, cv2.BORDER_CONSTANT, value=border)
    else:
        # ảnh thật đã có lề: cắt/nới ngẫu nhiên vài % để giống sai số của khung YOLO
        dx, dy = int(w * 0.05), int(h * 0.08)
        img = cv2.copyMakeBorder(img, dy, dy, dx, dx, cv2.BORDER_REPLICATE)
        x1, y1 = random.randint(0, 2 * dx), random.randint(0, 2 * dy)
        x2, y2 = w + 2 * dx - random.randint(0, 2 * dx), h + 2 * dy - random.randint(0, 2 * dy)
        img = img[y1:max(y2, y1 + 8), x1:max(x2, x1 + 8)]
    h, w = img.shape[:2]
    # phối cảnh nhẹ (camera nhìn chéo)
    if strong and random.random() < 0.8:
        d = 0.08
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        jit = np.random.uniform(-d, d, (4, 2)) * [w, h]
        M = cv2.getPerspectiveTransform(src, np.float32(src + jit))
        img = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if random.random() < 0.3:
        ang = random.uniform(-6, 6)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    # thu nhỏ rồi phóng lại: biển xa camera chỉ còn vài chục pixel
    if strong and random.random() < 0.6:
        s = random.uniform(0.2, 0.6) if synthetic else random.uniform(0.45, 0.9)  # ảnh thật vốn đã nhỏ
        small = cv2.resize(img, (max(8, int(w * s)), max(6, int(h * s))), interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (w, h), interpolation=random.choice([cv2.INTER_LINEAR, cv2.INTER_CUBIC]))
    if random.random() < (0.4 if synthetic else 0.2):
        k = random.choice([3, 5]) if synthetic else 3
        img = cv2.GaussianBlur(img, (k, k), 0)
    if random.random() < 0.2:  # nhòe do chuyển động
        k = random.randint(3, 7)
        kern = np.zeros((k, k), np.float32)
        kern[k // 2, :] = 1 / k
        img = cv2.filter2D(img, -1, kern)
    # sáng/tối/tương phản, bóng đổ
    img = img.astype(np.float32)
    img = img * random.uniform(0.55, 1.3) + random.uniform(-40, 40)
    if random.random() < 0.25:
        x0 = random.randint(0, w - 1)
        img[:, x0:] *= random.uniform(0.5, 0.85)
    if random.random() < 0.4:
        img += np.random.normal(0, random.uniform(2, 12), img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    if random.random() < 0.6:
        q = random.randint(20, 80)
        img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)
    return img


# ============================================================ dữ liệu OCR
class SyntheticOCR(Dataset):
    def __init__(self, n, seed=None, renderer=None, strong=True):
        self.n, self.seed, self.strong = n, seed, strong
        self.renderer = renderer or PlateRenderer()

    def __len__(self):
        return self.n

    def __getitem__(self, i):
        if self.seed is not None:  # tập val/test tổng hợp cố định
            random.seed(self.seed + i)
            np.random.seed((self.seed + i) % (2 ** 32))
        img, label, kind = self.renderer.sample()
        img = augment_plate(img, self.strong)
        return torch.from_numpy(ocr_input(img, two_rows=kind != "car_long"))[None], label


class CropOCR(Dataset):
    """Ảnh biển đã cắt + nhãn chữ (VNLP, ảnh tự thu): danh sách (đường_dẫn, nhãn, 2_dòng)."""

    def __init__(self, items, train=True):
        self.items, self.train = items, train

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, label, two_rows = self.items[i]
        img = cv2.imread(str(path))
        if img is None:
            img = np.full((48, 192, 3), 128, np.uint8)
        if self.train:
            img = augment_plate(img, strong=random.random() < 0.3, synthetic=False)
        return torch.from_numpy(ocr_input(img, two_rows=bool(two_rows)))[None], label


def collate(batch):
    x = torch.stack([b[0] for b in batch])
    labels = [b[1] for b in batch]
    targets = torch.tensor([CHAR2IDX[c] for s in labels for c in s if c in CHAR2IDX], dtype=torch.long)
    lengths = torch.tensor([sum(c in CHAR2IDX for c in s) for s in labels], dtype=torch.long)
    return x, targets, lengths, labels


# ============================================================ mô hình CRNN
def _block(cin, cout, pool):
    layers = [nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]
    if pool:
        layers.append(nn.MaxPool2d(pool))
    return layers


class CRNN(nn.Module):
    """CNN (48x192 -> 1x48) + BiLSTM + Linear. Đầu ra (N, T=48, C) logits, chỉ số 0 = blank."""

    def __init__(self, n_classes=len(ALPHABET) + 1, width=1.0, hidden=128, dropout=0.15):
        super().__init__()
        c = [int(v * width) for v in (32, 64, 128, 192, 256)]
        self.cnn = nn.Sequential(
            *_block(1, c[0], (2, 2)),          # 24 x 96
            *_block(c[0], c[1], (2, 2)),       # 12 x 48
            *_block(c[1], c[2], None),
            *_block(c[2], c[2], (2, 1)),       # 6 x 48
            *_block(c[2], c[3], None),
            *_block(c[3], c[3], (2, 1)),       # 3 x 48
            *_block(c[3], c[4], (3, 1)),       # 1 x 48
            nn.Dropout2d(dropout),
        )
        self.rnn = nn.LSTM(c[4], hidden, num_layers=2, bidirectional=True, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden * 2, n_classes)

    def forward(self, x):
        f = self.cnn(x).squeeze(2).permute(0, 2, 1)   # (N, T, C)
        f, _ = self.rnn(f)
        return self.fc(f)


def ctc_loss(logits, targets, lengths):
    logp = logits.log_softmax(-1).permute(1, 0, 2)   # (T, N, C)
    T, N = logp.shape[:2]
    return F.ctc_loss(logp.float(), targets, torch.full((N,), T, dtype=torch.long), lengths,
                      blank=0, zero_infinity=True)


def decode(logits):
    """CTC greedy -> [(chuỗi, độ tin cậy = min xác suất các ký tự)]."""
    prob = logits.float().softmax(-1).cpu().numpy()
    out = []
    for p in prob:
        idx, conf = p.argmax(-1), p.max(-1)
        chars, confs, prev = [], [], 0
        for i, c in zip(idx, conf):
            if i != prev and i != 0:
                chars.append(ALPHABET[i - 1])
                confs.append(c)
            prev = i
        out.append(("".join(chars), float(min(confs)) if confs else 0.0))
    return out


def char_errors(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@torch.no_grad()
def evaluate_ocr(model, loader, device):
    model.eval()
    n = exact = cerr = clen = 0
    loss_sum = 0.0
    rows = []
    for x, targets, lengths, labels in loader:
        logits = model(x.to(device))
        loss_sum += ctc_loss(logits, targets.to(device), lengths.to(device)).item() * len(labels)
        for (pred, conf), gt in zip(decode(logits), labels):
            n += 1
            exact += pred == gt
            cerr += char_errors(pred, gt)
            clen += len(gt)
            rows.append((gt, pred, conf))
    return {"loss": loss_sum / max(n, 1), "accuracy": exact / max(n, 1), "cer": cerr / max(clen, 1)}, rows


def export_ocr(model, path, meta):
    """TorchScript (CPU) + file .json mô tả cách tiền xử lý, giống ClassifierDetector của server."""
    import json
    model = model.cpu().eval()
    ex = torch.zeros(1, 1, meta["img_h"], meta["img_w"])
    ts = torch.jit.trace(model, ex)
    ts.save(str(path))
    Path(path).with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def set_seed(s=42):
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)


def worker_init(wid):
    s = torch.initial_seed() % (2 ** 32)
    random.seed(s + wid)
    np.random.seed((s + wid) % (2 ** 32))
