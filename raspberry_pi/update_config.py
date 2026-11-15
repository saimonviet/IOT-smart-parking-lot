"""Cập nhật config.yaml của Pi lên bản mới mà KHÔNG đụng khóa / IP server / chân cắm / góc servo rào đã chỉnh.

Chạy trên Pi sau khi chép code mới:   python3 update_config.py
Chạy lại nhiều lần cũng được (đã đúng thì bỏ qua). Bản cũ được giữ ở config.yaml.bak.

Bản hiện tại: camera biển số do ESP32-CAM tự xoay bằng động cơ bước (server điều khiển, xe ra ưu tiên)
  -> bỏ mục cam_mount (servo xoay camera trên Pi) nếu còn
  -> request_timeout_s >= 15 (server phải chờ lượt camera + quay động cơ + chụp 3 ảnh + nhận diện)
"""
import re
import shutil
from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parent / "config.yaml"
MIN_TIMEOUT = 15


def drop_section(text, name):
    """Bỏ mục cấp 1 `name:` cùng các dòng thụt lề / dòng trống ngay bên dưới (duyệt từng dòng, không đụng mục khác)."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if skipping:
            if line.strip() == "" or line[:1] in (" ", "\t"):
                continue
            skipping = False
        if line.startswith(f"{name}:"):
            skipping = True
            continue
        out.append(line)
    return "".join(out)


def main():
    s = CFG.read_text(encoding="utf-8")
    old = s
    changes = []

    m = re.search(r"^(\s*request_timeout_s:\s*)(\d+(?:\.\d+)?)", s, flags=re.M)
    if m and float(m.group(2)) < MIN_TIMEOUT:
        s = s[:m.start(2)] + str(MIN_TIMEOUT) + s[m.end(2):]
        changes.append(f"request_timeout_s {m.group(2)} -> {MIN_TIMEOUT}")
    elif not m:
        s = re.sub(r"^(server:\s*\n)", rf"\g<1>  request_timeout_s: {MIN_TIMEOUT}\n", s, count=1, flags=re.M)
        changes.append(f"thêm request_timeout_s: {MIN_TIMEOUT}")

    s2 = drop_section(s, "cam_mount")
    if s2 != s:
        s = s2
        changes.append("bỏ mục cam_mount (servo xoay camera) — ESP32-CAM tự xoay bằng động cơ bước")

    cfg = yaml.safe_load(s)  # báo lỗi ngay nếu YAML hỏng, trước khi ghi
    if s != old:
        shutil.copyfile(CFG, CFG.with_suffix(".yaml.bak"))
        CFG.write_text(s, encoding="utf-8")
    print("config OK —", "; ".join(changes) if changes else "đã là bản mới, không đổi gì")
    print("  server.url        =", cfg["server"]["url"])
    print("  request_timeout_s =", cfg["server"]["request_timeout_s"])
    print("  cam_mount         =", cfg.get("cam_mount", "không có (đúng)"))


if __name__ == "__main__":
    main()
