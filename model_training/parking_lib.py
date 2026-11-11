"""Thư viện dùng chung cho notebook huấn luyện: dữ liệu, mô hình, vòng lặp train/eval, các hàm đánh giá.

Đặt trong file .py (không định nghĩa trong notebook) để DataLoader nhiều worker chạy được trên Windows.
Quy ước nhãn: 1 = có xe (busy/occupied), 0 = trống (free/empty).
"""
import copy
import io
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import Dataset
from torchvision import models, transforms as T

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
CLASSES = ["empty", "occupied"]
WEATHER = {"S": "SUNNY", "O": "OVERCAST", "R": "RAINY"}


# =============================================================== dữ liệu
def load_cnr_split(root, split_file):
    """Đọc file nhãn của CNR-EXT (đường dẫn tương đối PATCHES/ + nhãn 0/1) thành DataFrame."""
    root = Path(root)
    rows = []
    for line in open(split_file, encoding="utf-8"):
        parts = line.split()
        if len(parts) != 2:
            continue
        rel, lab = parts
        weather, date, cam = rel.split("/")[:3]
        rows.append((str(root / "PATCHES" / rel), int(lab), weather, date, cam))
    return pd.DataFrame(rows, columns=["path", "label", "weather", "date", "camera"])


def load_cnrpark_ab(root):
    """CNRPark (camera A, B; thư mục busy/free) — dùng làm tập kiểm tra chéo bộ dữ liệu."""
    rows = []
    for cam in ("A", "B"):
        for cls, lab in (("free", 0), ("busy", 1)):
            for p in sorted((Path(root) / cam / cls).glob("*.jpg")):
                rows.append((str(p), lab, "-", "-", f"cam{cam}"))
    listing = Path(root).parent / "cache" / "cnrpark_ab.csv"
    if not rows and listing.exists():  # ảnh gốc đã xoá sau khi gói cache
        return pd.read_csv(listing)
    return pd.DataFrame(rows, columns=["path", "label", "weather", "date", "camera"])


def load_folder_dataset(root):
    """Dữ liệu tự thu (xe mô hình): root/empty/*.jpg và root/occupied/*.jpg."""
    rows = []
    for cls, lab in (("empty", 0), ("occupied", 1)):
        for p in sorted((Path(root) / cls).glob("*")):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                rows.append((str(p), lab, "-", "-", p.stem.split("_")[0]))
    return pd.DataFrame(rows, columns=["path", "label", "weather", "date", "camera"])


def _key(p):
    return os.path.normcase(os.path.abspath(p))


class JpegStore:
    """Toàn bộ ảnh JPEG gói trong 1 file .bin + chỉ mục (tạo bằng build_cache.py).

    Đọc hàng trăm nghìn file nhỏ trên Windows/OneDrive rất chậm (~170 file/s); đọc từ 1 file lớn nhanh hơn hàng chục lần.
    """

    def __init__(self, cache_dir):
        cache_dir = Path(cache_dir)
        idx = np.load(cache_dir / "index.npz", allow_pickle=False)
        self.bin_path = str(cache_dir / "patches.bin")
        self.index = {k: (int(o), int(n)) for k, o, n in zip(idx["keys"], idx["offsets"], idx["lengths"])}
        self._mm = None

    def __contains__(self, path):
        return _key(path) in self.index

    def get(self, path):
        if self._mm is None:  # mở trễ để mỗi worker DataLoader tự mở
            self._mm = np.memmap(self.bin_path, dtype=np.uint8, mode="r")
        o, n = self.index[_key(path)]
        return self._mm[o:o + n].tobytes()

    def __getstate__(self):
        d = self.__dict__.copy()
        d["_mm"] = None
        return d


class PatchDataset(Dataset):
    def __init__(self, df, transform, store=None):
        self.paths = df["path"].tolist()
        self.labels = df["label"].astype(int).tolist()
        self.transform = transform
        self.store = store

    def __len__(self):
        return len(self.paths)

    def load(self, i):
        p = self.paths[i]
        if self.store is not None and p in self.store:
            return Image.open(io.BytesIO(self.store.get(p))).convert("RGB")
        return Image.open(p).convert("RGB")

    def __getitem__(self, i):
        return self.transform(self.load(i)), self.labels[i]


def build_transforms(size=128, strong=True):
    """Tăng cường dữ liệu mô phỏng khác biệt camera thật: góc nhìn, ánh sáng, mờ, che khuất một phần."""
    train = [T.RandomResizedCrop(size, scale=(0.7, 1.0), ratio=(0.8, 1.25)), T.RandomHorizontalFlip()]
    if strong:
        train += [
            T.RandomApply([T.RandomAffine(degrees=12, translate=(0.05, 0.05), shear=6)], p=0.5),
            T.RandomApply([T.ColorJitter(0.4, 0.4, 0.35, 0.05)], p=0.8),
            T.RandomGrayscale(p=0.1),
            T.RandomApply([T.GaussianBlur(5, sigma=(0.1, 1.5))], p=0.2),
        ]
    train += [T.ToTensor(), T.Normalize(MEAN, STD)]
    if strong:
        train += [T.RandomErasing(p=0.25, scale=(0.02, 0.15))]
    evals = [T.Resize((size, size)), T.ToTensor(), T.Normalize(MEAN, STD)]
    return T.Compose(train), T.Compose(evals)


# =============================================================== mô hình
class MAlexNet(nn.Module):
    """mAlexNet — mạng nhỏ của bài báo gốc CNRPark+EXT (Amato et al. 2017), làm baseline."""

    def __init__(self, num_classes=2, dropout=0.5):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, 11, stride=4, padding=2), nn.ReLU(inplace=True),
            nn.MaxPool2d(3, 2), nn.LocalResponseNorm(5),
            nn.Conv2d(16, 20, 5, padding=2), nn.ReLU(inplace=True),
            nn.MaxPool2d(3, 2), nn.LocalResponseNorm(5),
            nn.Conv2d(20, 30, 3, padding=1), nn.ReLU(inplace=True),
            nn.MaxPool2d(3, 2),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(dropout), nn.LazyLinear(48),
                                        nn.ReLU(inplace=True), nn.Linear(48, num_classes))

    def forward(self, x):
        return self.classifier(self.features(x))


ARCHS = ["malexnet", "mobilenet_v3_small", "mobilenet_v3_large", "efficientnet_b0", "resnet18"]


def build_model(arch, dropout=0.2, pretrained=True, num_classes=2):
    if arch == "malexnet":
        m = MAlexNet(num_classes, dropout=max(dropout, 0.3))
        m(torch.zeros(1, 3, 128, 128))  # khởi tạo LazyLinear
        return m
    if arch.startswith("mobilenet_v3"):
        fn = getattr(models, arch)
        w = "DEFAULT" if pretrained else None
        m = fn(weights=w)
        m.classifier[2] = nn.Dropout(dropout)
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, num_classes)
        return m
    if arch == "efficientnet_b0":
        m = models.efficientnet_b0(weights="DEFAULT" if pretrained else None)
        m.classifier[0] = nn.Dropout(dropout)
        m.classifier[1] = nn.Linear(m.classifier[1].in_features, num_classes)
        return m
    if arch == "resnet18":
        m = models.resnet18(weights="DEFAULT" if pretrained else None)
        m.fc = nn.Sequential(nn.Dropout(dropout), nn.Linear(m.fc.in_features, num_classes))
        return m
    raise ValueError(arch)


def cam_layer(model, arch):
    """Lớp tích chập cuối để vẽ Grad-CAM."""
    if arch == "resnet18":
        return model.layer4
    return model.features[-1] if arch != "malexnet" else model.features[-3]


def count_params(model):
    return sum(p.numel() for p in model.parameters())


# =============================================================== huấn luyện
class EMA:
    """Trung bình trượt mũ của trọng số — thường cho mô hình ổn định và tổng quát hơn."""

    def __init__(self, model, decay=0.999):
        self.model = copy.deepcopy(model).eval()
        self.decay = decay
        for p in self.model.parameters():
            p.requires_grad_(False)

    @torch.no_grad()
    def update(self, model):
        msd = model.state_dict()
        for k, v in self.model.state_dict().items():
            if v.dtype.is_floating_point:
                v.mul_(self.decay).add_(msd[k].detach(), alpha=1 - self.decay)
            else:
                v.copy_(msd[k])


def make_optimizer(model, lr, weight_decay):
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (no_decay if p.ndim <= 1 or n.endswith(".bias") else decay).append(p)
    return torch.optim.AdamW([{"params": decay, "weight_decay": weight_decay},
                              {"params": no_decay, "weight_decay": 0.0}], lr=lr)


def cosine_with_warmup(optimizer, total_steps, warmup_steps):
    def f(step):
        if step < warmup_steps:
            return (step + 1) / warmup_steps
        prog = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1 + math.cos(math.pi * min(prog, 1.0)))
    return torch.optim.lr_scheduler.LambdaLR(optimizer, f)


def train_one_epoch(model, loader, optimizer, scheduler, scaler, device, label_smoothing=0.0,
                    ema=None, max_steps=None):
    model.train()
    crit = nn.CrossEntropyLoss(label_smoothing=label_smoothing)
    tot_loss = tot_ok = n = 0
    use_amp = device.type == "cuda"
    for step, (x, y) in enumerate(loader):
        if max_steps and step >= max_steps:
            break
        x = x.to(device, non_blocking=True).to(memory_format=torch.channels_last)
        y = y.to(device, non_blocking=True)
        with torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
            out = model(x)
            loss = crit(out, y)
        optimizer.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()
        if ema:
            ema.update(model)
        tot_loss += loss.item() * len(y)
        tot_ok += (out.argmax(1) == y).sum().item()
        n += len(y)
    return tot_loss / n, tot_ok / n


@torch.no_grad()
def predict(model, loader, device, tta=False):
    """Trả về (xác suất có xe, nhãn thật, loss trung bình)."""
    model.eval()
    probs, labels, loss_sum = [], [], 0.0
    use_amp = device.type == "cuda"
    for x, y in loader:
        x = x.to(device, non_blocking=True).to(memory_format=torch.channels_last)
        with torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
            logits = model(x).float()
            if tta:
                logits = (logits + model(torch.flip(x, dims=[3])).float()) / 2
        loss_sum += F.cross_entropy(logits, y.to(device), reduction="sum").item()
        probs.append(torch.softmax(logits, 1)[:, 1].cpu())
        labels.append(y)
    p, y = torch.cat(probs).numpy(), torch.cat(labels).numpy()
    return p, y, loss_sum / len(y)


# =============================================================== đánh giá
def binary_metrics(y, p, thr=0.5):
    from sklearn.metrics import (accuracy_score, average_precision_score, f1_score,
                                 precision_score, recall_score, roc_auc_score)
    pred = (p >= thr).astype(int)
    return {"accuracy": accuracy_score(y, pred), "precision": precision_score(y, pred, zero_division=0),
            "recall": recall_score(y, pred, zero_division=0), "f1": f1_score(y, pred, zero_division=0),
            "roc_auc": roc_auc_score(y, p) if len(set(y)) > 1 else float("nan"),
            "avg_precision": average_precision_score(y, p) if len(set(y)) > 1 else float("nan")}


def best_threshold(y, p):
    """Ngưỡng tối đa F1 (chọn trên tập val, áp dụng cho test)."""
    from sklearn.metrics import f1_score
    grid = np.linspace(0.05, 0.95, 91)
    scores = [f1_score(y, (p >= t).astype(int)) for t in grid]
    return float(grid[int(np.argmax(scores))])


def expected_calibration_error(y, p, bins=15):
    conf = np.where(p >= 0.5, p, 1 - p)
    pred = (p >= 0.5).astype(int)
    edges = np.linspace(0.5, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(ece)


@torch.no_grad()
def latency_ms(model, device, batch=12, size=128, runs=50):
    """Thời gian suy luận cho 1 khung hình = 12 ô (batch 12)."""
    model = model.to(device).eval()
    x = torch.randn(batch, 3, size, size, device=device)
    for _ in range(10):
        model(x)
    if device.type == "cuda":
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(runs):
        model(x)
    if device.type == "cuda":
        torch.cuda.synchronize()
    return (time.perf_counter() - t0) / runs * 1000


def gradcam(model, layer, x, target=1):
    """Grad-CAM cho lớp 'có xe': bản đồ nhiệt vùng ảnh mô hình dựa vào để quyết định."""
    acts, grads = {}, {}

    def fwd(m, i, o):
        acts["a"] = o
        o.register_hook(lambda g: grads.__setitem__("g", g))
    h = layer.register_forward_hook(fwd)
    model.eval()
    x = x.clone().requires_grad_(True)
    out = model(x)
    model.zero_grad()
    out[:, target].sum().backward()
    h.remove()
    w = grads["g"].mean(dim=(2, 3), keepdim=True)
    cam = F.relu((w * acts["a"]).sum(1, keepdim=True))
    cam = F.interpolate(cam, size=x.shape[-2:], mode="bilinear", align_corners=False)
    cam = cam - cam.amin(dim=(2, 3), keepdim=True)
    cam = cam / (cam.amax(dim=(2, 3), keepdim=True) + 1e-6)
    return cam[:, 0].detach().cpu().numpy(), torch.softmax(out, 1)[:, 1].detach().cpu().numpy()


def denorm(x):
    m = torch.tensor(MEAN).view(3, 1, 1)
    s = torch.tensor(STD).view(3, 1, 1)
    return (x.cpu() * s + m).clamp(0, 1).permute(1, 2, 0).numpy()


# --- nhiễu loạn để đo độ bền (áp dụng trên tensor đã chuẩn hoá) ---
def perturb(x, kind, level):
    m = torch.tensor(MEAN, device=x.device).view(1, 3, 1, 1)
    s = torch.tensor(STD, device=x.device).view(1, 3, 1, 1)
    img = x * s + m
    if kind == "brightness":
        img = img * level
    elif kind == "noise":
        img = img + torch.randn_like(img) * level
    elif kind == "blur":
        k = int(level) * 2 + 1
        img = T.functional.gaussian_blur(img, k)
    elif kind == "lowres":
        h = x.shape[-1]
        img = F.interpolate(F.interpolate(img, scale_factor=1 / level, mode="bilinear"), size=(h, h), mode="bilinear")
    elif kind == "occlusion":
        h = x.shape[-1]
        c = int(h * level)
        img = img.clone()
        img[:, :, :c, :c] = 0.5
    return (img.clamp(0, 1) - m) / s
