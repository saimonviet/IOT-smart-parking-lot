"""Thử nhận diện biển số từ ESP32-CAM (chạy trên máy tính, dùng đúng mô hình + cách bỏ phiếu của server).

ESP32-CAM không đủ sức chạy YOLO/CRNN, nên ESP32 chỉ gửi ảnh, máy tính nhận diện.
  - MẶC ĐỊNH: KHÔNG stream, camera nghỉ. Chỉ khi bấm c (hoặc nút Chụp 3 ảnh / SPACE) mới CHỤP giống hệt server
    khi xe tới cổng: chụp liền 3 ảnh (/capture) -> nhận diện cả 3 -> bỏ phiếu -> KẾT QUẢ (cho qua / chuyển bảo vệ).
    Xoay động cơ (i/o/g, nhích, test xoay) cũng KHÔNG tự chụp — bấm c khi muốn xem hình.
  - --stream: xem LUỒNG MJPEG cổng 81 và nhận diện liên tục (để căn góc, lấy nét). Biển giống nhau 3 khung -> "ON DINH".
  - --auto: tự chụp lượt mới liên tục (nghỉ --interval giây giữa 2 lượt).

Chạy (thư mục pc_server, đã kích hoạt .venv):
  python tools/plate_cam_test.py                                   # lấy URL/khóa đã lưu ở trang Thiết bị, bấm c để chụp
  python tools/plate_cam_test.py --url http://192.168.1.50 --key <CAM_KEY>
  python tools/plate_cam_test.py --gate out                        # ESP32 có động cơ bước: xoay về cổng ra trước
  python tools/plate_cam_test.py --stream                          # xem luồng liên tục như trước
  python tools/plate_cam_test.py --source D:/anh_bien_so            # không có ESP32: ảnh / thư mục ảnh (c = ảnh tiếp theo)

Nút bấm (chuột) dưới cửa sổ: [Cổng VÀO] [Cổng RA] [Đổi cổng] [Chụp 3 ảnh] — mỗi lần bấm động cơ bước quay 1 lần.
  Hàng nút thứ 2 = TEST ĐỘNG CƠ BƯỚC: [-128] [-16] [+16] [+128] [Lưu=VÀO] [Lưu=RA] [Test xoay].
Khi CHỤP (nút Chụp 3 ảnh / --capture) đèn flash tự bật như server (mức đã lưu ở trang Thiết bị, mặc định 80).
Phím: q/ESC thoát | g đổi cổng | i / o xoay về cổng VÀO / RA | c (hoặc SPACE) chụp 3 ảnh như server
      f bật/tắt đèn flash | s lưu ảnh + ảnh cắt biển | (--stream) SPACE tạm dừng luồng
Phím động cơ bước: , / .  nhích -16 / +16 bước | < / >  (Shift) nhích -128 / +128 bước (2048 bước = 1 vòng)
      1 / 2  lưu vị trí hiện tại = cổng VÀO / RA (ESP32 nhớ qua mất điện) | t  test xoay VÀO <-> RA 3 lượt, đo thời gian
      m  in vị trí động cơ hiện tại
"""
import argparse
import json
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.plates import PlateCamera, PlateModel, is_valid, load_cam, pretty  # noqa: E402

SAVE_DIR = config.DATA_DIR / "plate_test"
GREEN, ORANGE, RED, WHITE = (80, 220, 120), (0, 165, 255), (80, 80, 255), (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX
WIN = "Thu bien so ESP32-CAM (q: thoat)"


class LatestFrame:
    """Đọc luồng MJPEG ở luồng nền, chỉ giữ khung MỚI NHẤT -> hình không bị trễ dần khi nhận diện chậm hơn luồng."""

    def __init__(self, url, key):
        u = urllib.parse.urlparse(url if "://" in url else "http://" + url)
        q = f"?key={urllib.parse.quote(key)}" if key else ""
        self.src = f"{u.scheme}://{u.hostname}:81/stream{q}"
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            raise SystemExit(f"Không mở được luồng {u.hostname}:81/stream — firmware mặc định TẮT stream "
                             f"(đặt STREAM_ENABLED = true trong esp32_cam.ino rồi nạp lại), hoặc sai IP / khóa. "
                             f"Bỏ --stream để dùng chế độ bấm c mới chụp.")
        self.frame, self.seq, self.ok = None, 0, True
        self.lock = threading.Lock()
        self.fps, self._t = 0.0, time.time()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.ok:
            ok, f = self.cap.read()
            if not ok:
                time.sleep(0.5)
                self.cap.release()
                self.cap = cv2.VideoCapture(self.src)   # mất luồng (ESP32 khởi động lại...) -> mở lại
                continue
            now = time.time()
            self.fps = 0.9 * self.fps + 0.1 / max(1e-3, now - self._t) if self.fps else 1 / max(1e-3, now - self._t)
            self._t = now
            with self.lock:
                self.frame, self.seq = f, self.seq + 1

    def get(self, after=-1, timeout=5.0):
        """Khung mới hơn số thứ tự `after` (chờ tối đa timeout)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if self.frame is not None and self.seq > after:
                    return self.frame.copy(), self.seq
            time.sleep(0.01)
        return None, after

    def release(self):
        self.ok = False
        self.cap.release()


def vote(per_frame):
    """Giống PlateReader của server: điểm = độ tin cậy (x0.3 nếu sai định dạng), cộng dồn theo biển, chia số ảnh."""
    votes = defaultdict(float)
    for reads in per_frame:
        if reads:
            plate, conf, _ = reads[0]
            votes[plate] += conf * (1.0 if is_valid(plate) else 0.3)
    if not votes:
        return None, 0.0, False
    plate = max(votes, key=votes.get)
    conf = min(1.0, votes[plate] / max(1, len(per_frame)))
    return plate, conf, bool(plate) and is_valid(plate) and conf >= config.PLATE_MIN_CONF


def annotate(img, reads):
    out = img.copy()
    s = max(0.6, out.shape[1] / 1280)
    for plate, conf, box in reads or []:
        x1, y1, x2, y2 = map(int, box)
        color = GREEN if is_valid(plate) and conf >= config.PLATE_MIN_CONF else ORANGE
        cv2.rectangle(out, (x1, y1), (x2, y2), color, max(2, int(2 * s)))
        label = f"{pretty(plate) or plate or '?'}  {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.8 * s, 2)
        ty = max(th + 8, y1 - 8)
        cv2.rectangle(out, (x1, ty - th - 6), (x1 + tw + 8, ty + 4), color, -1)
        cv2.putText(out, label, (x1 + 4, ty), FONT, 0.8 * s, (0, 0, 0), 2, cv2.LINE_AA)
    return out


def compose(shots, per_frame, foot_text, foot_color, hud, width):
    """Ảnh tốt nhất ở trên, (nếu nhiều ảnh) các ảnh của lượt chụp xếp hàng bên dưới, dòng kết quả ở cuối."""
    scores = [r[0][1] if r else -1 for r in per_frame]
    best = int(np.argmax(scores)) if shots else 0
    main = annotate(shots[best], per_frame[best])
    main = cv2.resize(main, (width, int(main.shape[0] * width / main.shape[1])), interpolation=cv2.INTER_AREA)
    rows = [np.full((30, width, 3), 20, np.uint8)]
    cv2.putText(rows[0], hud, (8, 21), FONT, 0.55, WHITE, 1, cv2.LINE_AA)
    rows.append(main)
    if len(shots) > 1:
        tw = width // len(shots)
        th = int(shots[0].shape[0] * tw / shots[0].shape[1])
        strip = np.full((th + 26, width, 3), 30, np.uint8)
        for i, (img, reads) in enumerate(zip(shots, per_frame)):
            t = cv2.resize(annotate(img, reads), (tw - 4, th), interpolation=cv2.INTER_AREA)
            strip[0:th, i * tw + 2:i * tw + 2 + tw - 4] = t
            txt = f"#{i + 1} " + (f"{pretty(reads[0][0]) or reads[0][0] or '?'} {reads[0][1]:.0%}" if reads else "khong thay")
            cv2.putText(strip, txt, (i * tw + 6, th + 19), FONT, 0.5, GREEN if reads else RED, 1, cv2.LINE_AA)
        rows.append(strip)
    foot = np.full((46, width, 3), 20, np.uint8)
    cv2.putText(foot, foot_text, (8, 31), FONT, 0.75, foot_color, 2, cv2.LINE_AA)
    rows.append(foot)
    return np.vstack(rows)


BUTTONS = [
    [("in", "Cong VAO  [i]"), ("out", "Cong RA  [o]"), ("toggle", "Doi cong  [g]"), ("shot", "Chup 3 anh  [c]")],
    # hàng 2: test động cơ bước
    [("-128", "-128 [<]"), ("-16", "-16 [,]"), ("+16", "+16 [.]"), ("+128", "+128 [>]"),
     ("set_in", "Luu=VAO [1]"), ("set_out", "Luu=RA [2]"), ("sweep", "Test xoay [t]")],
]
NUDGE_KEYS = {",": -16, ".": 16, "<": -128, ">": 128}
KEY_OF = {"in": "i", "out": "o", "toggle": "g", "shot": "c", "-128": "<", "-16": ",", "+16": ".", "+128": ">",
          "set_in": "1", "set_out": "2", "sweep": "t"}


def with_buttons(view, gate, aiming):
    """Thêm các hàng nút dưới khung hình; trả về (ảnh, [(x1, y1, x2, y2, action)]) để bắt cú bấm chuột."""
    w = view.shape[1]
    bars, rects, y0 = [], [], view.shape[0]
    for row in BUTTONS:
        bar = np.full((52, w, 3), 35, np.uint8)
        bw = w // len(row)
        for i, (act, label) in enumerate(row):
            x1, x2 = i * bw + 6, (i + 1) * bw - 6
            active = act == gate
            color = (40, 140, 60) if active else (90, 90, 90)
            if aiming == act:
                color, label = (0, 140, 200), "dang quay..."
            elif act.startswith("set_"):
                color = (140, 90, 40)
            cv2.rectangle(bar, (x1, 8), (x2, 44), color, -1)
            cv2.rectangle(bar, (x1, 8), (x2, 44), (200, 200, 200) if active else (120, 120, 120), 1)
            (tw, _), _ = cv2.getTextSize(label, FONT, 0.55, 1)
            sc = min(0.55, 0.55 * (x2 - x1 - 8) / max(1, tw))     # chữ dài thì thu nhỏ cho vừa nút
            (tw, _), _ = cv2.getTextSize(label, FONT, sc, 1)
            cv2.putText(bar, label, (x1 + (x2 - x1 - tw) // 2, 32), FONT, sc, WHITE, 1, cv2.LINE_AA)
            rects.append((x1, y0 + 8, x2, y0 + 44, act))
        bars.append(bar)
        y0 += 52
    return np.vstack([view, *bars]), rects


def verdict_line(result):
    plate, conf, ok = result
    if plate is None:
        return "KET QUA: khong thay bien so", RED
    if ok:
        return f"KET QUA: {pretty(plate)}  ({conf:.0%})  -> server se CHO QUA", GREEN
    return f"CHUA CHAC: {pretty(plate) or plate or '?'} ({conf:.0%}) -> bao ve nhap tay", ORANGE


def save(shots, per_frame):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    n = 0
    for i, (img, reads) in enumerate(zip(shots, per_frame)):
        cv2.imwrite(str(SAVE_DIR / f"{stamp}_{i + 1}.jpg"), img)
        h, w = img.shape[:2]
        for j, (plate, conf, (x1, y1, x2, y2)) in enumerate(reads or []):
            px, py = (x2 - x1) * 0.06, (y2 - y1) * 0.10
            crop = img[int(max(0, y1 - py)):int(min(h, y2 + py)), int(max(0, x1 - px)):int(min(w, x2 + px))]
            cv2.imwrite(str(SAVE_DIR / f"{stamp}_{i + 1}_bien{j}_{plate or 'unk'}.jpg"), crop)
            n += 1
    print(f"  -> đã lưu {len(shots)} ảnh + {n} ảnh cắt biển vào {SAVE_DIR}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="http://<ip-esp32> (mặc định: URL đã lưu ở trang Thiết bị)")
    ap.add_argument("--key", help="CAM_KEY trong firmware (mặc định: khóa đã lưu)")
    ap.add_argument("--source", help="ảnh hoặc thư mục ảnh để thử không cần ESP32")
    ap.add_argument("--stream", action="store_true", help="xem luồng :81 và nhận diện liên tục (mặc định: chỉ chụp khi bấm c)")
    ap.add_argument("--auto", action="store_true", help="tự chụp lượt mới liên tục thay vì chờ bấm c")
    ap.add_argument("--capture", action="store_true", help=argparse.SUPPRESS)   # giữ cho lệnh cũ: nay là mặc định
    ap.add_argument("--frames", type=int, default=config.PLATE_FRAMES, help="số ảnh mỗi lượt chụp (mặc định như server)")
    ap.add_argument("--gap", type=float, default=config.PLATE_FRAME_GAP_S, help="nghỉ giữa 2 lần chụp (giây)")
    ap.add_argument("--manual", action="store_true", help=argparse.SUPPRESS)    # giữ cho lệnh cũ: nay là mặc định
    ap.add_argument("--interval", type=float, default=1.0, help="(--auto) nghỉ giữa 2 lượt chụp tự động (giây)")
    ap.add_argument("--flash", type=int, default=None,
                    help="độ sáng flash khi chụp 0–255 (mặc định: mức đã lưu ở trang Thiết bị; 0 = không bật)")
    ap.add_argument("--gate", choices=["in", "out"], help="ESP32 có động cơ bước: xoay camera về cổng này lúc bắt đầu")
    ap.add_argument("--no-window", action="store_true", help="không mở cửa sổ, chỉ in kết quả")
    ap.add_argument("--width", type=int, default=1000, help="chiều rộng cửa sổ hiển thị")
    args = ap.parse_args()

    saved = load_cam()
    cam = PlateCamera()
    cam.configure({**saved, "url": args.source or args.url or saved.get("url", ""),
                   "key": saved.get("key", "") if args.key is None else args.key})
    url = (cam.cfg.get("url") or "").strip()
    if not url:
        raise SystemExit("Chưa có địa chỉ camera: thêm --url http://<ip-esp32> (hoặc --source <ảnh/thư mục>)")
    is_http = url.startswith("http")
    capture_only = not (args.stream and is_http)        # mặc định không stream; ảnh/thư mục thì không có luồng
    manual = not args.auto                              # True = chỉ chụp khi bấm c / SPACE
    n = max(1, args.frames)

    print("Nạp mô hình...", end=" ", flush=True)
    model = PlateModel()
    if not model.ready:
        raise SystemExit(model.error)
    print("xong.")

    gate = args.gate
    aiming = None                                       # cổng đang xoay tới (động cơ quay ở luồng nền)
    actions = deque()                                   # cú bấm nút / phím chờ xử lý
    rects = []

    def aim_to(g, then_shot=False):
        """Mỗi lần bấm: quay động cơ bước 1 lần về cổng g (luồng nền, luồng hình vẫn chạy để thấy camera xoay)."""
        nonlocal gate, aiming
        if not is_http or aiming:
            return
        aiming = g

        def run():
            nonlocal gate, aiming
            ta = time.time(); r = cam.aim(g)
            ms = (time.time() - ta) * 1000
            if r is None:
                print(f"KHÔNG xoay được về cổng {g}: {cam.error}")
            else:
                motor.update(r)
                gate = g
                print(f"xoay camera về cổng {'VÀO' if g == 'in' else 'RA'}: {ms:.0f} ms"
                      f"{' (đã đúng hướng)' if not r.get('moved') else ''}")
                history.clear()
                if then_shot:
                    actions.append("shot")
            aiming = None
        threading.Thread(target=run, daemon=True).start()

    # ---------------- test động cơ bước (lệnh /aim của firmware, chạy ở luồng nền để hình vẫn chạy khi quay)
    motor = {}                                          # vị trí ESP32 trả về gần nhất: pos, in_pos, out_pos, enabled

    def motor_call(q, timeout=15.0):
        if cam.cfg.get("key"):
            q = {**q, "key": cam.cfg["key"]}
        with urllib.request.urlopen(f"{url.rstrip('/')}/aim?{urllib.parse.urlencode(q)}", timeout=timeout) as r:
            d = json.loads(r.read().decode() or "{}")
        motor.update(d)
        if not d.get("enabled", 1):
            print("  (!) firmware đang TẮT động cơ: đặt STEPPER_ENABLED = true trong esp32_cam.ino rồi nạp lại")
        return d

    def motor_job(act, fn):
        nonlocal aiming
        if not is_http:
            print("Đang chạy với ảnh/thư mục — không có động cơ để test"); return
        if aiming:
            print("Động cơ đang quay, chờ xong rồi bấm lại"); return
        aiming = act

        def run():
            nonlocal aiming
            try:
                fn()
            except Exception as e:
                print(f"LỖI động cơ ({act}): {e}")
            finally:
                aiming = None
        threading.Thread(target=run, daemon=True).start()

    def motor_text():
        if "pos" not in motor:
            return ""
        return f" | buoc {motor['pos']} (VAO {motor.get('in_pos')} / RA {motor.get('out_pos')})"

    def nudge(n):
        def fn():
            nonlocal gate
            before = motor.get("pos", "?")
            t = time.time(); d = motor_call({"steps": n})
            gate = None                                 # đã rời vị trí cổng
            history.clear()
            print(f"nhích {n:+d} bước ({n * 360 / 2048:+.1f}°): vị trí {before} -> {d.get('pos')}, "
                  f"{(time.time() - t) * 1000:.0f} ms")
        motor_job(f"{n:+d}", fn)

    def save_pos(g):
        def fn():
            nonlocal gate
            d = motor_call({"set": g})
            gate = g
            print(f"ĐÃ LƯU vị trí {d.get('pos')} = cổng {'VÀO' if g == 'in' else 'RA'} "
                  f"(VÀO {d.get('in_pos')} / RA {d.get('out_pos')}) — ESP32 nhớ qua mất điện")
        motor_job("set_" + g, fn)

    def sweep(rounds=3):
        def fn():
            nonlocal gate
            print(f"TEST XOAY: {rounds} lượt VÀO -> RA -> VÀO. Nhìn hình: mỗi lần về phải đúng khung cũ.")
            motor_call({"gate": "in"}); gate = "in"
            times = []
            for i in range(rounds):
                for g in ("out", "in"):
                    t = time.time(); d = motor_call({"gate": g}); ms = (time.time() - t) * 1000
                    gate = g
                    times.append(ms)
                    print(f"  lượt {i + 1}: -> cổng {'RA ' if g == 'out' else 'VÀO'}  vị trí {d.get('pos')}  {ms:.0f} ms")
            history.clear()
            span = abs((motor.get("out_pos") or 0) - (motor.get("in_pos") or 0))
            print(f"  => xong: trung bình {statistics.mean(times):.0f} ms/lần quay ({span} bước ≈ {span * 360 / 2048:.0f}°), "
                  f"chậm nhất {max(times):.0f} ms.")
            print("     Hình lệch dần sau mỗi lượt = động cơ TRƯỢT BƯỚC: kiểm tra nguồn 5V/2A, "
                  "tăng STEP_DELAY_MS (4–5) trong firmware.")
        motor_job("sweep", fn)

    def show_motor():
        def fn():
            d = motor_call({})                          # không tham số = chỉ hỏi vị trí, không quay
            print(f"động cơ: vị trí {d.get('pos')} | cổng VÀO {d.get('in_pos')} | cổng RA {d.get('out_pos')} "
                  f"| đang nhìn: {d.get('gate')}")
        motor_job("status", fn)

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            for x1, y1, x2, y2, act in rects:
                if x1 <= x <= x2 and y1 <= y <= y2:
                    actions.append(act)

    history = deque(maxlen=3)
    if gate and is_http:
        ta = time.time(); r = cam.aim(gate)
        print(f"xoay camera về cổng {gate}: {(time.time() - ta) * 1000:.0f} ms" if r is not None else f"KHÔNG xoay được: {cam.error}")
        if r:
            motor.update(r)
    elif is_http:
        try:
            motor_call({}, timeout=3)                   # lấy vị trí động cơ để hiện trên màn
        except Exception:
            pass
    stream = None if capture_only else LatestFrame(url, cam.cfg.get("key", ""))
    if not capture_only:
        mode = f"LUỒNG :81 nhận diện liên tục (bấm c để chụp {n} ảnh như server)"
    elif manual:
        mode = f"camera NGHỈ, không stream — bấm c (hoặc nút Chụp 3 ảnh) để chụp {n} ảnh + nhận diện"
    else:
        mode = f"tự chụp {n} ảnh/lượt mỗi {args.interval:g}s rồi nhận diện"
    print(f"Nguồn: {url} | {mode} | ngưỡng tin cậy {config.PLATE_MIN_CONF:.0%}")

    # flash khi CHỤP giống server; đèn lúc xem luồng (light) thì bật/tắt bằng phím f
    shot_flash = max(0, min(255, args.flash if args.flash is not None else int(cam.cfg.get("flash") or 0)))
    light = 0
    if is_http:
        print(f"Flash khi chụp: {shot_flash if shot_flash else 'tắt'}")
    view, last, seq = None, None, -1
    if capture_only and manual:                         # màn chờ: chưa chụp gì, chỉ hiện hướng dẫn + các nút
        h = args.width * 3 // 4
        view = np.full((h, args.width, 3), 25, np.uint8)
        for i, (txt, color) in enumerate([("Camera dang nghi (khong stream)", WHITE),
                                          ("Bam  c  (hoac nut 'Chup 3 anh') de chup + nhan dien bien so", GREEN),
                                          ("i / o: xoay ve cong VAO / RA   , . < >: nhich dong co   t: test xoay", WHITE),
                                          ("1 / 2: luu vi tri cong VAO / RA   f: den flash   q: thoat", WHITE)]):
            cv2.putText(view, txt, (30, h // 2 - 60 + i * 40), FONT, 0.7, color, 2 if i == 1 else 1, cv2.LINE_AA)
    want = capture_only and not manual                  # True = cần chụp 1 lượt 3 ảnh
    hold_until = 0.0                                    # luồng: giữ kết quả chụp trên màn hình vài giây
    last_print = ("", 0.0)

    def burst():
        """Chụp n ảnh /capture -> nhận diện -> bỏ phiếu, giống luồng chính của server."""
        nonlocal view, last
        if shot_flash and is_http:
            cam.set_flash(shot_flash); time.sleep(0.25)    # chờ camera chỉnh lại độ phơi sáng
        shots, t0 = [], time.time()
        for i in range(n):
            img = cam.grab(timeout=3.0)
            if not is_http:
                cam.next_file()
            if img is None:
                print("Không lấy được ảnh:", cam.error); break
            shots.append(img)
            if i < n - 1 and args.gap > 0:
                time.sleep(args.gap)
        cap_ms = (time.time() - t0) * 1000
        if shot_flash and is_http:
            cam.set_flash(light)                           # trả đèn về trạng thái lúc xem luồng
        if not shots:
            return False
        t1 = time.time()
        per_frame = [model.recognize(img) for img in shots]
        det_ms = (time.time() - t1) * 1000
        result = vote(per_frame)
        h, w = shots[0].shape[:2]
        hud = (f"CHUP {len(shots)} anh {w}x{h}{' | cong ' + gate if gate else ''}{motor_text()} | chup {cap_ms:.0f} ms, "
               f"nhan dien {det_ms:.0f} ms | tong {(time.time() - t0) * 1000:.0f} ms")
        each = " | ".join(f"{pretty(r[0][0]) or r[0][0] or '?'} {r[0][1]:.0%}" if r else "không thấy" for r in per_frame)
        plate, conf, ok = result
        verdict = (f"{pretty(plate)} ({conf:.0%}) CHO QUA" if ok else
                   f"chưa chắc: {pretty(plate) or plate or '?'} ({conf:.0%})" if plate is not None else "không thấy biển")
        print(f"[{datetime.now():%H:%M:%S}] CHỤP {len(shots)} ảnh: chụp {cap_ms:.0f} ms, nhận diện {det_ms:.0f} ms"
              f" | từng ảnh: {each} => {verdict}")
        view = compose(shots, per_frame, *verdict_line(result), hud, args.width)
        last = (shots, per_frame)
        return True

    try:
        while True:
            if want:                                    # ---- chụp 3 ảnh như server
                want = capture_only and not manual
                if not burst():
                    time.sleep(1.0)
                hold_until = time.time() + 4.0
            elif stream and time.time() >= hold_until:  # ---- luồng: khung mới nhất, nhận diện
                frame, seq = stream.get(after=seq)
                if frame is None:
                    print("Chưa nhận được khung hình từ luồng..."); continue
                t = time.time(); reads = model.recognize(frame); det = (time.time() - t) * 1000
                top = reads[0][0] if reads and is_valid(reads[0][0]) and reads[0][1] >= config.PLATE_MIN_CONF else None
                history.append(top)
                stable = top if top and len(history) == 3 and len(set(history)) == 1 else None
                if stable:
                    foot = (f"ON DINH: {pretty(stable)}  ({reads[0][1]:.0%})", GREEN)
                elif reads:
                    foot = (f"thay: {pretty(reads[0][0]) or reads[0][0] or '?'} ({reads[0][1]:.0%}) - giu yen xe", ORANGE)
                else:
                    foot = ("khong thay bien so", RED)
                h, w = frame.shape[:2]
                hud = (f"LUONG :81 {w}x{h} | {stream.fps:.1f} fps | nhan dien {det:.0f} ms"
                       f"{' | cong ' + gate if gate else ''}{motor_text()}{' | DANG QUAY...' if aiming else ''}"
                       f"{' | den bat' if light else ''}")
                view = compose([frame], [reads], *foot, hud, args.width)
                last = ([frame], [reads])
                msg = foot[0]
                if args.no_window and (msg != last_print[0] or time.time() - last_print[1] > 2):
                    print(f"[{datetime.now():%H:%M:%S}] luồng {stream.fps:.1f} fps, nhận diện {det:.0f} ms -> {msg}")
                    last_print = (msg, time.time())

            if args.no_window:
                if capture_only:
                    if manual:
                        input("Enter để chụp lượt mới (Ctrl+C thoát)... ")
                    else:
                        time.sleep(args.interval)
                    want = True
                continue
            if view is not None:
                shown, rects = with_buttons(view, gate, aiming) if is_http else (view, [])
                cv2.imshow(WIN, shown)
                if not getattr(main, "_mouse", False):
                    cv2.setMouseCallback(WIN, on_mouse)
                    main._mouse = True
            if stream:
                wait = 1
            elif manual:
                wait = 50
            else:
                wait = max(1, int(args.interval * 1000))
            k = cv2.waitKey(wait) & 0xFF
            if capture_only and not manual:
                want = True
            if k in (ord("q"), 27):
                break
            # nút bấm chuột -> giống phím tắt
            if k == 255 and actions:
                k = ord(KEY_OF[actions.popleft()])
            if k == ord("c"):
                want = True
            elif k == ord("g") and is_http:
                aim_to("in" if gate == "out" else "out", then_shot=capture_only and not manual)
            elif k == ord(" "):
                if capture_only and manual:
                    want = True
                else:
                    print("Tạm dừng — bấm phím bất kỳ để chạy tiếp"); cv2.waitKey(0)
            elif k == ord("s") and last:
                save(*last)
            elif k in (ord("i"), ord("o")) and is_http:
                aim_to("in" if k == ord("i") else "out", then_shot=capture_only and not manual)
            elif chr(k) in NUDGE_KEYS:
                nudge(NUDGE_KEYS[chr(k)])
            elif k in (ord("1"), ord("2")):
                save_pos("in" if k == ord("1") else "out")
            elif k == ord("t"):
                sweep()
            elif k == ord("m"):
                show_motor()
            elif k == ord("f") and is_http:
                light = 0 if light else (shot_flash or 80)
                cam.set_flash(light)
                print("đèn lúc xem luồng:", light or "tắt")
    except KeyboardInterrupt:
        pass
    finally:
        if is_http and (light or shot_flash):
            cam.set_flash(0)
        if stream:
            stream.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
