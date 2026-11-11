"""FastAPI server: API cho giao diện quản lý + WebSocket cho dashboard và cho Raspberry Pi."""
import asyncio
import csv
import io
import ipaddress
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import (Body, Depends, FastAPI, HTTPException, Query, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, stats
from . import secure_channel as sc
from .detector import (KINDS, DetectionEngine, FrameSource, list_models, load_selection,
                       make_detector, render_frame, save_selection)
from . import layout as layout_mod
from .layout import Layout
from .plates import PlateReader, clean, is_valid, pretty, save_cam
from .state import LotState


class PiConn:
    """Một kết nối Pi ĐÃ XÁC THỰC: mọi tin gửi đi đều được ký bằng khóa phiên."""

    def __init__(self, ws, sess, ip, device, tls):
        self.ws, self.sess, self.ip, self.device, self.tls = ws, sess, ip, device, tls
        self.lock = asyncio.Lock()  # ký + gửi tuần tự để seq đến Pi đúng thứ tự

    async def send(self, body):
        async with self.lock:
            await self.ws.send_json(self.sess.seal(body))

    async def close(self, code=1000):
        try:
            await self.ws.close(code=code)
        except Exception:
            pass


class AuthGuard:
    """Chống dò khóa: một IP sai MAX_FAILS lần trong WINDOW giây thì bị chặn BLOCK giây."""
    MAX_FAILS, WINDOW, BLOCK = 5, 300, 300

    def __init__(self):
        self.fails, self.blocked = {}, {}

    def is_blocked(self, ip):
        if self.blocked.get(ip, 0) > time.time():
            return True
        self.blocked.pop(ip, None)
        return False

    def fail(self, ip):
        """Ghi một lần sai; trả về True nếu IP vừa bị chặn."""
        now = time.time()
        recent = [t for t in self.fails.get(ip, []) if now - t < self.WINDOW] + [now]
        if len(recent) >= self.MAX_FAILS:
            self.fails.pop(ip, None)
            self.blocked[ip] = now + self.BLOCK
            return True
        self.fails[ip] = recent
        return False

    def ok(self, ip):
        self.fails.pop(ip, None)


def _is_loopback(ip):
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


class Hub:
    """Quản lý kết nối WebSocket: dashboard (nhiều) và Pi (một)."""

    def __init__(self):
        self.dash = set()
        self.pi = None
        self.pi_info = {}
        self.pi_telemetry = {}
        self.pi_seen = 0.0
        self.loop = None

    def threadsafe(self, coro_fn, *args):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(coro_fn(*args), self.loop)

    async def to_dash(self, msg):
        for ws in list(self.dash):
            try:
                await ws.send_json(msg)
            except Exception:
                self.dash.discard(ws)

    async def to_pi(self, msg):
        conn = self.pi
        if conn:
            try:
                await conn.send(msg)
                return True
            except Exception:
                if self.pi is conn:
                    self.pi = None
        return False


hub = Hub()
pi_guard = AuthGuard()
pi_pending = 0  # số kết nối Pi đang bắt tay
layout = state = source = engine = None
plates = PlateReader()  # camera biển số ESP32-CAM + mô hình ALPR
detector_sel = None  # {"kind", "model", "threshold"} đang dùng


def device_info():
    pi_online = hub.pi is not None
    det = engine.detector
    return {
        "plate": plates.status(),
        "pi": {"online": pi_online, "ip": hub.pi_info.get("ip"), "last_seen": hub.pi_seen,
               "telemetry": hub.pi_telemetry if pi_online else {}, "info": hub.pi_info},
        "camera": {"online": source.online(), "fps": round(source.fps, 1), "source": source.source,
                   "error": source.error},
        "detector": {"name": engine.name, "fps": round(engine.fps, 1), "error": engine.error,
                     "has_reference": config.REFERENCE_PATH.exists(), "boxes": len(engine.boxes),
                     "model": detector_sel.get("model"),
                     "threshold": getattr(det, "threshold", None),
                     "default_threshold": getattr(det, "default_threshold", None),
                     # xác suất có xe từng ô (chỉ mô hình phân loại) — để chỉnh ngưỡng trên trang Thiết bị
                     "probs": {layout.label(s): round(p, 3) for s, p in getattr(det, "probs", {}).items()
                               if s in layout.slots}},
    }


def full_state():
    snap = state.snapshot()
    snap["devices"] = device_info()
    snap["now"] = time.time()
    return snap


def pi_layout_msg():
    return {"type": "layout", "lot": layout.screen()}


def pi_state_msg():
    return {"type": "state", "slots": state.pi_slots(), "free": state.free_count(),
            "total": len(layout.slot_ids)}


async def push_state():
    await hub.to_dash({"type": "state", "data": full_state()})
    await hub.to_pi(pi_state_msg())


def on_state_event(kind, payload):
    if kind == "state":
        hub.threadsafe(push_state)
    elif kind == "event":
        hub.threadsafe(hub.to_dash, {"type": "event", "data": payload})
    elif kind == "plate":
        hub.threadsafe(hub.to_dash, {"type": "plate", "data": payload})


async def ticker():
    while True:
        await asyncio.sleep(2)
        state.sweep_reservations()
        await hub.to_dash({"type": "state", "data": full_state()})


@asynccontextmanager
async def lifespan(app):
    global layout, state, source, engine, detector_sel
    db.init()
    auth.ensure_admin()
    layout = Layout()
    state = LotState(layout)
    source = FrameSource()
    source.start()
    if config.VIDEO_SOURCE != "auto":
        source.set_source(config.VIDEO_SOURCE)
    detector_sel = load_selection()
    engine = DetectionEngine(layout, state, source, make_detector(layout, detector_sel))
    engine.start()
    hub.loop = asyncio.get_running_loop()
    state.listeners.append(on_state_event)
    task = asyncio.create_task(ticker())
    threading.Thread(target=plates.ensure_model, daemon=True).start()
    print(f"[server] detector={engine.name} model={detector_sel.get('model')} source={config.VIDEO_SOURCE} "
          f"{'| ' + engine.error if engine.error else ''}")
    yield
    task.cancel()
    engine.stop()
    source.stop()


app = FastAPI(title="Smart Parking", lifespan=lifespan)


# ----------------------------------------------------------------- auth
class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody):
    u = db.one("SELECT * FROM users WHERE username=?", (body.username.strip(),))
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    return {"token": auth.make_token(u), "user": {"username": u["username"], "role": u["role"]}}


@app.get("/api/auth/me")
def me(user=Depends(auth.current_user)):
    return {"username": user["sub"], "role": user["role"]}


# ----------------------------------------------------------------- dữ liệu
@app.get("/api/layout")
def get_layout(user=Depends(auth.current_user)):
    return layout.public()


@app.post("/api/layout/validate")
def validate_layout(data: dict = Body(...), user=Depends(auth.require_admin)):
    errors, warnings = layout_mod.validate(data)
    return {"errors": errors, "warnings": warnings}


_reload_lock = threading.Lock()


@app.put("/api/layout")
def put_layout(data: dict = Body(...), user=Depends(auth.require_admin)):
    """Lưu sơ đồ mới và áp dụng ngay, không cần khởi động lại server."""
    global layout, state, engine
    errors, warnings = layout_mod.validate(data)
    if errors:
        raise HTTPException(400, "Sơ đồ chưa hợp lệ: " + "; ".join(errors))
    with _reload_lock:
        new_layout = Layout(data=layout_mod.save(data))
        engine.stop(wait=True)  # để luồng nhận diện cũ không ghi vào state cũ nữa
        old = state
        with old.lock:
            # ô bị xóa mà còn xe: đóng phiên đỗ để không treo phiên mãi
            for sid in old.layout.slot_ids:
                if sid not in new_layout.slots and sid in old.open_session:
                    old._on_left(sid)
            old.listeners.clear()
        layout = new_layout
        state = LotState(new_layout)
        state.listeners.append(on_state_event)
        engine = DetectionEngine(new_layout, state, source, make_detector(new_layout, detector_sel))
        engine.start()
    state.log("info", "layout", f"Quản lý {user['sub']} cập nhật sơ đồ bãi ({len(layout.slot_ids)} ô)")
    hub.threadsafe(hub.to_dash, {"type": "layout"})
    hub.threadsafe(hub.to_pi, pi_layout_msg())
    hub.threadsafe(push_state)
    return {"ok": True, "warnings": warnings, "layout": layout.public()}


@app.get("/api/camera/raw.jpg")
def camera_raw(user=Depends(auth.require_admin)):
    """Khung hình gốc (không vẽ ROI) để vẽ vùng ô; mất camera thì dùng ảnh nền đã chụp."""
    frame, _ = source.get()
    if frame is None and config.REFERENCE_PATH.exists():
        frame = cv2.imread(str(config.REFERENCE_PATH))
    if frame is None:
        raise HTTPException(503, "Chưa có khung hình từ camera")
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
def get_state(user=Depends(auth.current_user)):
    return full_state()


@app.get("/api/events")
def get_events(limit: int = 40, user=Depends(auth.current_user)):
    return db.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (min(limit, 200),))


@app.get("/api/stats/overview")
def get_overview(user=Depends(auth.current_user)):
    return stats.overview()


@app.get("/api/history")
def get_history(page: int = 1, size: int = 15, slot: int = 0, status: str = "",
                date_from: str = "", date_to: str = "", user=Depends(auth.current_user)):
    return stats.history(max(page, 1), min(size, 100), slot or None, status, date_from, date_to)


@app.get("/api/history/export.csv")
def export_csv(slot: int = 0, status: str = "", date_from: str = "", date_to: str = "",
               user=Depends(auth.current_user)):
    data = stats.history(1, 100000, slot or None, status, date_from, date_to)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "o_do", "bien_so", "gio_vao", "gio_ra", "thoi_gian_giay", "phi_vnd", "nguon"])
    for r in data["items"]:
        w.writerow([r["id"], r["slot_id"], pretty(r.get("plate")) if r.get("plate") else "", r["entry_at"], r["exit_at"] or "", r["duration_s"] or "",
                    r["fee"] or "", r["source"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=lich-su-do-xe.csv"})


# ----------------------------------------------------------------- điều khiển (admin)
class OverrideBody(BaseModel):
    mode: str  # occupied | free | auto


@app.post("/api/slots/{sid}/override")
def override_slot(sid: int, body: OverrideBody, user=Depends(auth.require_admin)):
    if sid not in layout.slots:
        raise HTTPException(404, "Không có ô này")
    val = {"occupied": True, "free": False, "auto": None}.get(body.mode)
    if body.mode not in ("occupied", "free", "auto"):
        raise HTTPException(400, "mode không hợp lệ")
    state.set_override(sid, val)
    state.log("info", "override", f"Quản lý đặt tay ô {layout.label(sid)} = {body.mode}", sid)
    return {"ok": True}


class BarrierBody(BaseModel):
    gate: str   # in | out
    action: str  # open | close


@app.post("/api/devices/barrier")
async def barrier(body: BarrierBody, user=Depends(auth.require_admin)):
    if body.gate not in ("in", "out") or body.action not in ("open", "close"):
        raise HTTPException(400, "Tham số không hợp lệ")
    ok = await hub.to_pi({"type": "command", "cmd": f"{body.action}_barrier", "gate": body.gate})
    if not ok:
        raise HTTPException(503, "Raspberry Pi đang offline")
    state.log("info", "barrier", f"Quản lý {body.action} rào {'vào' if body.gate == 'in' else 'ra'} bằng tay")
    return {"ok": True}


@app.post("/api/devices/led-test")
async def led_test(user=Depends(auth.require_admin)):
    if not await hub.to_pi({"type": "command", "cmd": "led_test"}):
        raise HTTPException(503, "Raspberry Pi đang offline")
    return {"ok": True}


@app.post("/api/detector/reference")
def capture_reference(user=Depends(auth.require_admin)):
    if not engine.capture_reference():
        raise HTTPException(503, "Chưa có khung hình từ camera")
    state.log("info", "reference", "Đã chụp ảnh nền bãi trống")
    return {"ok": True}


@app.get("/api/detector/models")
def detector_models(user=Depends(auth.current_user)):
    return {"current": detector_sel, "models": list_models()}


class DetectorBody(BaseModel):
    kind: str                       # classifier | yolo | background | none
    model: str | None = None        # đường dẫn trong danh sách /api/detector/models
    threshold: float | None = None  # chỉ cho classifier; None = ngưỡng lưu lúc huấn luyện


@app.put("/api/detector")
def set_detector(body: DetectorBody, user=Depends(auth.require_admin)):
    """Đổi bộ nhận diện / mô hình khi đang chạy; tải thử mô hình mới trước, lỗi thì giữ nguyên bộ cũ."""
    global engine, detector_sel
    if body.kind not in KINDS:
        raise HTTPException(400, "Loại bộ nhận diện không hợp lệ")
    if body.threshold is not None and not 0 < body.threshold < 1:
        raise HTTPException(400, "Ngưỡng phải nằm trong khoảng 0–1")
    if body.kind in ("classifier", "yolo") and not any(
            m["kind"] == body.kind and m["model"] == body.model for m in list_models()):
        raise HTTPException(400, f"Không tìm thấy mô hình {body.model}")
    sel = {"kind": body.kind,
           "model": body.model if body.kind in ("classifier", "yolo") else None,
           "threshold": body.threshold if body.kind == "classifier" else None}
    with _reload_lock:
        made = make_detector(layout, sel)
        if sel["kind"] != "none" and made[0] is None:
            raise HTTPException(400, made[1])
        engine.stop(wait=True)
        engine = DetectionEngine(layout, state, source, made)
        engine.start()
        detector_sel = sel
        save_selection(sel)
    name = {"classifier": "mô hình phân loại", "yolo": "YOLO", "background": "so sánh ảnh nền"}.get(sel["kind"], "tắt")
    extra = f" {sel['model']}" if sel["model"] else ""
    if sel["kind"] == "classifier":
        extra += f", ngưỡng {engine.detector.threshold:.2f}"
    state.log("info", "detector", f"Quản lý {user['sub']} đổi bộ nhận diện: {name}{extra}")
    hub.threadsafe(push_state)
    return {"ok": True, "current": sel}


@app.get("/api/devices")
def get_devices(user=Depends(auth.current_user)):
    return device_info()


# ----------------------------------------------------------------- video
def _statuses():
    return {s: state.status_of(s) for s in layout.slot_ids}


def _annotated_jpeg():
    frame, _ = source.get()
    img = render_frame(frame, layout, _statuses(), list(engine.boxes), engine.name)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return buf.tobytes() if ok else b""


@app.get("/api/snapshot.jpg")
def snapshot(user=Depends(auth.current_user)):
    return Response(_annotated_jpeg(), media_type="image/jpeg")


@app.get("/api/stream")
async def stream(user=Depends(auth.current_user)):
    async def gen():
        while True:
            jpg = await asyncio.get_running_loop().run_in_executor(None, _annotated_jpeg)
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            await asyncio.sleep(0.1)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


# ----------------------------------------------------------------- WebSocket
@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket, token: str = Query(default="")):
    if not auth.decode_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.dash.add(ws)
    try:
        await ws.send_json({"type": "state", "data": full_state()})
        while True:
            await ws.receive_text()  # chỉ để phát hiện ngắt kết nối
    except WebSocketDisconnect:
        pass
    finally:
        hub.dash.discard(ws)


@app.websocket("/ws/pi")
async def ws_pi(ws: WebSocket):
    """Kênh Pi: TLS (wss) + bắt tay HMAC hai chiều + mọi tin được ký. Xem app/secure_channel.py."""
    global pi_pending
    ip = ws.client.host if ws.client else "?"
    tls = ws.url.scheme == "wss"
    if pi_guard.is_blocked(ip) or pi_pending >= config.PI_MAX_PENDING:
        await ws.close(code=4429)  # IP đang bị chặn / quá nhiều kết nối đang bắt tay
        return
    if config.PI_REQUIRE_TLS and not tls and not _is_loopback(ip):
        pi_guard.fail(ip)
        state.log("warn", "security", f"Từ chối kết nối Pi KHÔNG mã hóa (ws://) từ {ip} — Pi phải dùng wss://")
        await ws.close(code=4426)
        return
    pi_pending += 1
    try:
        await ws.accept()
        conn = await pi_handshake(ws, ip, tls)
    finally:
        pi_pending -= 1
    if not conn:
        return

    # chỉ thay Pi cũ khi kết nối mới ĐÃ xác thực -> kẻ không có khóa không thể đá Pi thật ra
    old, hub.pi = hub.pi, conn
    if old:
        await old.close(4409)
    hub.pi_info = {"ip": ip, "device": conn.device, "tls": tls, "auth": "HMAC-SHA256"}
    hub.pi_seen = time.time()
    state.log("info", "pi_online", f"Raspberry Pi '{conn.device}' kết nối ({ip}, "
                                   f"{'TLS' if tls else 'KHÔNG mã hóa'}, đã xác thực HMAC)")
    try:
        await conn.send(pi_layout_msg())
        await conn.send(pi_state_msg())
        await hub.to_dash({"type": "state", "data": full_state()})
        while True:
            raw = await ws.receive_json()
            try:
                msg = conn.sess.open(raw)
            except sc.SecurityError as e:
                state.log("warn", "security", f"Gói tin từ Pi ({ip}) bị từ chối: {e} — ngắt kết nối")
                await conn.close(4400)
                break
            hub.pi_seen = time.time()
            await handle_pi_message(conn, msg, ip)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("[pi] lỗi:", e)
    finally:
        if hub.pi is conn:
            hub.pi = None
            state.log("warn", "pi_offline", "Raspberry Pi mất kết nối")
            await hub.to_dash({"type": "state", "data": full_state()})


async def pi_handshake(ws, ip, tls):
    """Challenge-response. Đúng khóa -> PiConn, sai -> ghi nhật ký, đếm lần sai, đóng kết nối, trả None."""
    nonce = sc.new_nonce()
    msg = None
    try:
        await ws.send_json(sc.challenge(nonce))
        msg = await asyncio.wait_for(ws.receive_json(), timeout=config.PI_AUTH_TIMEOUT)
    except Exception:  # hết giờ / ngắt kết nối / không phải JSON
        pass
    device = sc.check_auth(config.PI_KEY, nonce, msg)
    if not device:
        blocked = pi_guard.fail(ip)
        state.log("warn", "security", f"Xác thực Pi THẤT BẠI từ {ip} (sai khóa hoặc sai giao thức)"
                                      + (f" — chặn IP này {AuthGuard.BLOCK // 60} phút" if blocked else ""))
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        return None
    pi_guard.ok(ip)
    cnonce = msg["cnonce"]
    await ws.send_json(sc.auth_ok(config.PI_KEY, nonce, cnonce, device))
    sess = sc.Session(sc.session_key(config.PI_KEY, nonce, cnonce), send_dir="srv", recv_dir="pi")
    return PiConn(ws, sess, ip, device, tls)


async def handle_pi_message(conn, msg, ip):
    t = msg.get("type")
    if t == "hello":
        hub.pi_info.update({"version": msg.get("version"), "barrier": msg.get("barrier"),
                            "stream_port": msg.get("stream_port")})
        if config.VIDEO_SOURCE == "auto" and msg.get("stream_port"):
            source.set_source(f"http://{ip}:{msg['stream_port']}/stream.mjpg")
    elif t == "arrive":
        # đọc biển số mất 1–3 giây -> chạy riêng, không chặn các tin khác của Pi (telemetry, cổng còn lại)
        asyncio.create_task(process_arrival(conn, msg.get("gate"), msg.get("timeout")))
    elif t == "telemetry":
        hub.pi_telemetry = msg.get("data", {})
    elif t == "log":
        state.log(msg.get("level", "info"), "pi", msg.get("message", ""))


async def process_arrival(conn, gate, pi_timeout=None):
    gate = "in" if gate == "in" else "out"
    read = None
    if plates.enabled:
        # trả lời trước khi Pi hết kiên nhẫn (Pi quá hạn sẽ tự chuyển chế độ offline)
        budget = max(0.8, min(config.PLATE_BUDGET, float(pi_timeout or 3.0) - 1.0))
        read = await asyncio.get_running_loop().run_in_executor(None, plates.read, gate, budget)
    if gate == "in":
        res = state.handle_entry(read)
        body = {"type": "entry_result", **res}
    else:
        res = state.handle_exit(read)
        body = {"type": "exit_result", **res}
    try:
        await conn.send(body)
    except Exception as e:
        print("[pi] không gửi được kết quả cổng:", e)


# ----------------------------------------------------------------- biển số / lượt xe
class PlateCamBody(BaseModel):
    url: str = ""
    key: str = ""
    roi: dict


def _check_roi(roi):
    out = {}
    for g in ("in", "out"):
        r = roi.get(g)
        if not (isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in r)):
            raise HTTPException(400, f"ROI cổng {g} phải là [x1, y1, x2, y2] trong khoảng 0–1")
        if abs(r[2] - r[0]) < 0.05 or abs(r[3] - r[1]) < 0.05:
            raise HTTPException(400, f"ROI cổng {g} quá nhỏ")
        out[g] = [round(float(v), 4) for v in r]
    return out


@app.get("/api/plate-cam")
def plate_cam(user=Depends(auth.current_user)):
    cfg = dict(plates.cam.cfg)
    cfg["key"] = "••••" if cfg.get("key") else ""  # không trả khóa về trình duyệt
    return {"config": cfg, "status": plates.status()}


@app.put("/api/plate-cam")
def put_plate_cam(body: PlateCamBody, user=Depends(auth.require_admin)):
    url = body.url.strip()
    if url and not (url.startswith(("http://", "https://")) or Path(url).exists()):
        raise HTTPException(400, "URL phải là http://<ip-esp32> (hoặc đường dẫn ảnh/thư mục có thật để chạy thử)")
    cfg = {"url": url, "roi": _check_roi(body.roi),
           "key": plates.cam.cfg.get("key", "") if body.key == "••••" else body.key.strip()}
    save_cam(cfg)
    plates.cam.configure(cfg)
    state.log("info", "plate_cam", f"Quản lý {user['sub']} cập nhật camera biển số ({url or 'tắt'})")
    hub.threadsafe(push_state)
    return {"ok": True}


@app.get("/api/plate-cam/snapshot.jpg")
def plate_cam_snapshot(user=Depends(auth.current_user)):
    """Ảnh hiện tại của ESP32-CAM, vẽ vùng cổng vào (xanh) / cổng ra (đỏ) để căn chỉnh."""
    img = plates.cam.grab(timeout=2.0)
    if img is None:
        img = plates.cam.last_frame
    if img is None:
        raise HTTPException(503, f"Không lấy được ảnh: {plates.cam.error}")
    img = img.copy()
    h, w = img.shape[:2]
    for g, color in (("in", (248, 189, 56)), ("out", (113, 113, 248))):
        r = (plates.cam.cfg.get("roi") or {}).get(g)
        if r:
            cv2.rectangle(img, (int(r[0] * w), int(r[1] * h)), (int(r[2] * w), int(r[3] * h)), color, 2)
            cv2.putText(img, "VAO" if g == "in" else "RA", (int(r[0] * w) + 6, int(r[1] * h) + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class GateBody(BaseModel):
    gate: str


@app.post("/api/plate-cam/test")
def plate_cam_test(body: GateBody, user=Depends(auth.require_admin)):
    """Đọc thử biển số ở một cổng (không mở rào, không ghi lượt xe)."""
    if body.gate not in ("in", "out"):
        raise HTTPException(400, "gate phải là in hoặc out")
    return plates.read(body.gate, budget=config.PLATE_BUDGET)


@app.post("/api/plate-cam/reload-model")
def plate_reload(user=Depends(auth.require_admin)):
    m = plates.reload_model()
    if not m.ready:
        raise HTTPException(400, m.error)
    state.log("info", "plate_model", f"Quản lý {user['sub']} nạp lại mô hình biển số")
    return {"ok": True}


@app.get("/api/plates/img/{day}/{name}")
def plate_image(day: str, name: str, user=Depends(auth.current_user)):
    f = (config.PLATE_IMG_DIR / day / name).resolve()
    if not f.is_relative_to(config.PLATE_IMG_DIR.resolve()) or not f.is_file():
        raise HTTPException(404, "Không có ảnh")
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/visits")
def get_visits(page: int = 1, size: int = 15, status: str = "", q: str = "",
               date_from: str = "", date_to: str = "", user=Depends(auth.current_user)):
    where, params = ["1=1"], []
    if status in ("inside", "done"):
        where.append("status=?")
        params.append(status)
    if clean(q):
        where.append("plate LIKE ?")
        params.append(f"%{clean(q)}%")
    if date_from:
        where.append("entry_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("entry_at < date(?, '+1 day')")
        params.append(date_to)
    w = " AND ".join(where)
    size = min(max(size, 1), 100)
    tot = db.one(f"SELECT COUNT(*) c, COALESCE(SUM(fee),0) s FROM visits WHERE {w}", params)
    inside = db.one("SELECT COUNT(*) c FROM visits WHERE status='inside'")["c"]
    rows = db.query(f"SELECT * FROM visits WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?",
                    params + [size, (max(page, 1) - 1) * size])
    for r in rows:
        r["display"] = pretty(r["plate"])
    return {"items": rows, "total": tot["c"], "revenue": tot["s"], "inside": inside}


@app.get("/api/plate-reads")
def get_plate_reads(limit: int = 20, user=Depends(auth.current_user)):
    rows = db.query("SELECT * FROM plate_reads ORDER BY id DESC LIMIT ?", (min(limit, 100),))
    for r in rows:
        r["display"] = pretty(r["plate"]) if r["plate"] else None
    return rows


class PlateBody(BaseModel):
    plate: str


def _manual_plate(text):
    p = clean(text)
    if not is_valid(p):
        raise HTTPException(400, f"Biển số '{text}' không đúng định dạng Việt Nam (vd. 51G-123.45, 59-X1 234.56)")
    return p


@app.post("/api/visits/manual-entry")
async def manual_entry(body: PlateBody, user=Depends(auth.require_admin)):
    """Bảo vệ/quản lý nhập tay biển số khi camera không đọc được: ghi lượt vào, cấp ô và mở rào vào."""
    plate = _manual_plate(body.plate)
    read = {"plate": plate, "display": pretty(plate), "conf": 1.0, "reason": f"nhập tay bởi {user['sub']}",
            "image": (plates.recent[0].get("image") if plates.recent and plates.recent[0]["gate"] == "in" else None)}
    res = state.handle_entry(read, mode="manual")
    if not res["allowed"]:
        raise HTTPException(409, " ".join([res["oled"]["title"], *res["oled"]["lines"]]))
    sent = await hub.to_pi({"type": "command", "cmd": "gate_result", "gate": "in", "result": res})
    return {"ok": True, "pi": sent, "slot": res.get("label")}


@app.post("/api/visits/manual-exit")
async def manual_exit(body: PlateBody, user=Depends(auth.require_admin)):
    """Nhập tay biển số ở cổng ra: phải khớp một lượt trong bãi, tính phí và mở rào ra."""
    plate = _manual_plate(body.plate)
    read = {"plate": plate, "display": pretty(plate), "conf": 1.0, "reason": f"nhập tay bởi {user['sub']}",
            "image": (plates.recent[0].get("image") if plates.recent and plates.recent[0]["gate"] == "out" else None)}
    res = state.handle_exit(read, mode="manual")
    if not res["allowed"]:
        raise HTTPException(409, f"Không có xe {pretty(plate)} trong bãi")
    sent = await hub.to_pi({"type": "command", "cmd": "gate_result", "gate": "out", "result": res})
    return {"ok": True, "pi": sent, "fee": res.get("fee")}


@app.post("/api/visits/{vid}/checkout")
async def checkout_visit(vid: int, user=Depends(auth.require_admin)):
    """Đóng một lượt xe bằng tay (xe đã ra mà không qua camera, hoặc lượt bị treo)."""
    v = db.one("SELECT * FROM visits WHERE id=?", (vid,))
    if not v:
        raise HTTPException(404, "Không có lượt xe này")
    if v["status"] != "inside":
        raise HTTPException(409, "Lượt xe đã kết thúc")
    fee, dur = state.close_visit(v, None, "manual")
    state.log("info", "gate_out", f"Quản lý {user['sub']} kết thúc lượt xe {pretty(v['plate'])}, "
                                  f"gửi {dur // 60} phút, phí {fee:,}đ")
    return {"ok": True, "fee": fee}


@app.put("/api/visits/{vid}")
def edit_visit(vid: int, body: PlateBody, user=Depends(auth.require_admin)):
    """Sửa biển số đọc sai (để lúc ra so khớp đúng)."""
    plate = _manual_plate(body.plate)
    v = db.one("SELECT * FROM visits WHERE id=?", (vid,))
    if not v:
        raise HTTPException(404, "Không có lượt xe này")
    if v["status"] == "inside" and plate != v["plate"] and state.inside_visit(plate, exact_only=True):
        raise HTTPException(409, f"Xe {pretty(plate)} đã có một lượt khác trong bãi")
    db.execute("UPDATE visits SET plate=?, note=? WHERE id=?",
               (plate, f"sửa từ {v['plate']} bởi {user['sub']}", vid))
    db.execute("UPDATE sessions SET plate=? WHERE visit_id=?", (plate, vid))
    state.log("info", "plate_edit", f"Quản lý {user['sub']} sửa biển số {pretty(v['plate'])} -> {pretty(plate)}")
    return {"ok": True}


# ----------------------------------------------------------------- giao diện React (sau khi build)
if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = config.WEB_DIST / path
        return FileResponse(f if path and f.is_file() else config.WEB_DIST / "index.html")
else:
    @app.get("/")
    def root():
        return {"message": "API đang chạy. Chạy giao diện: cd web && npm install && npm run dev"}
