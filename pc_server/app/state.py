"""Trạng thái bãi xe: ô trống / có xe / giữ chỗ, phiên đỗ, tính phí và nhật ký sự kiện."""
import math
import threading
import time
from datetime import datetime, timezone

from . import config, db
from .plates import distance, pretty
from .layout import Layout


def calc_fee(duration_s: int) -> int:
    minutes = math.ceil(duration_s / 60)
    blocks = max(1, math.ceil(minutes / config.BLOCK_MINUTES))
    return int(blocks * config.RATE_PER_HOUR * config.BLOCK_MINUTES / 60)


class LotState:
    def __init__(self, layout: Layout):
        self.layout = layout
        self.lock = threading.RLock()
        self.detected = {s: False for s in layout.slot_ids}   # kết quả camera (đã làm mượt)
        self.overrides = {}                                    # sid -> True/False (ép tay)
        self.occupied = {s: False for s in layout.slot_ids}   # trạng thái hiệu lực
        self.since = {s: time.time() for s in layout.slot_ids}
        self.open_session = {}                                 # sid -> session id
        self.reservations = {}                                 # sid -> {"at","expires","route"}
        self.listeners = []                                    # callback(kind, payload) gọi từ mọi thread
        self._restore_open_sessions()

    # ---------- tiện ích ----------
    def _restore_open_sessions(self):
        for r in db.query("SELECT id, slot_id FROM sessions WHERE exit_at IS NULL"):
            if r["slot_id"] in self.occupied:
                self.occupied[r["slot_id"]] = True
                self.detected[r["slot_id"]] = True
                self.open_session[r["slot_id"]] = r["id"]

    def _emit(self, kind, payload=None):
        for cb in self.listeners:
            try:
                cb(kind, payload)
            except Exception as e:  # không để lỗi listener làm hỏng logic chính
                print("[state] listener error:", e)

    def log(self, level, type_, message, slot_id=None):
        ts = db.now_iso()
        db.execute("INSERT INTO events(ts,level,type,message,slot_id) VALUES(?,?,?,?,?)",
                   (ts, level, type_, message, slot_id))
        self._emit("event", {"ts": ts, "level": level, "type": type_, "message": message,
                             "slot_id": slot_id})

    def status_of(self, sid):
        if self.occupied[sid]:
            return "occupied"
        if sid in self.reservations:
            return "reserved"
        return "free"

    # ---------- cập nhật từ camera / ép tay ----------
    def set_detected(self, occ: dict):
        with self.lock:
            changed = False
            for sid, v in occ.items():
                if sid in self.detected and self.detected[sid] != v:
                    self.detected[sid] = v
                    changed = True
            if changed:
                self._recompute()

    def set_override(self, sid, value):
        """value: True (có xe) / False (trống) / None (theo camera)."""
        with self.lock:
            if value is None:
                self.overrides.pop(sid, None)
            else:
                self.overrides[sid] = value
            self._recompute()

    def _recompute(self):
        """Tính lại trạng thái hiệu lực, mở/đóng phiên đỗ khi một ô đổi trạng thái."""
        for sid in self.layout.slot_ids:
            eff = self.overrides.get(sid, self.detected[sid])
            if eff == self.occupied[sid]:
                continue
            self.occupied[sid] = eff
            self.since[sid] = time.time()
            if eff:
                self._on_parked(sid)
            else:
                self._on_left(sid)
        self._emit("state")

    def _on_parked(self, sid):
        source = "manual" if sid in self.overrides else "camera"
        res = None
        if sid in self.reservations:
            res = self.reservations.pop(sid)
            entry_ts = datetime.fromtimestamp(res["at"], timezone.utc).isoformat(timespec="seconds")
            self.log("info", "park", f"Xe {self._pl(res)}đã đỗ vào ô {self.layout.label(sid)} (đúng ô được chỉ định)", sid)
        else:
            entry_ts = db.now_iso()
            if self.reservations:
                # xe đỗ ô khác ô được chỉ định -> coi như xe đang được dẫn đã rẽ nhầm ô
                oldest = min(self.reservations, key=lambda k: self.reservations[k]["at"])
                res = self.reservations.pop(oldest)
                self.log("warn", "wrong_slot",
                         f"Xe {self._pl(res)}đỗ vào ô {self.layout.label(sid)} thay vì ô "
                         f"{self.layout.label(oldest)} được chỉ định", sid)
            else:
                self.log("warn", "park_no_gate",
                         f"Ô {self.layout.label(sid)} có xe nhưng không qua cổng vào (hoặc cổng offline)", sid)
        plate, visit_id = (res or {}).get("plate"), (res or {}).get("visit_id")
        if visit_id:
            db.execute("UPDATE visits SET slot_id=? WHERE id=?", (sid, visit_id))
        self.open_session[sid] = db.execute(
            "INSERT INTO sessions(slot_id,entry_at,source,plate,visit_id) VALUES(?,?,?,?,?)",
            (sid, entry_ts, source, plate, visit_id))

    def _on_left(self, sid):
        sess_id = self.open_session.pop(sid, None)
        if sess_id is None:
            return
        row = db.one("SELECT entry_at FROM sessions WHERE id=?", (sess_id,))
        entry = datetime.fromisoformat(row["entry_at"])
        dur = max(0, int((datetime.now(timezone.utc) - entry).total_seconds()))
        fee = calc_fee(dur)
        db.execute("UPDATE sessions SET exit_at=?, duration_s=?, fee=? WHERE id=?",
                   (db.now_iso(), dur, fee, sess_id))
        self.log("info", "leave", f"Xe rời ô {self.layout.label(sid)}, đỗ {dur // 60} phút, phí {fee:,}đ", sid)

    # ---------- giữ chỗ / cấp ô ----------
    def sweep_reservations(self):
        with self.lock:
            now = time.time()
            expired = [s for s, r in self.reservations.items() if r["expires"] < now]
            for s in expired:
                self.reservations.pop(s)
                self.log("warn", "reserve_expired", f"Hết hạn giữ chỗ ô {self.layout.label(s)} (xe không đỗ vào)", s)
            if expired:
                self._emit("state")

    @staticmethod
    def _pl(res):
        return f"{pretty(res['plate'])} " if res and res.get("plate") else ""

    @staticmethod
    def _deny(reason, title, *lines):
        return {"allowed": False, "reason": reason, "oled": {"title": title, "lines": list(lines), "arrow": "none"}}

    def _record_read(self, gate, read, result, visit_id=None):
        """Lưu mọi lần đọc biển (kể cả bị từ chối) để tra soát, đẩy lên dashboard theo thời gian thực."""
        if read is None:
            return
        t = read.get("timing") or {}
        read["read_id"] = db.execute(
            "INSERT INTO plate_reads(ts,gate,plate,guess,conf,image,result,visit_id,reason,read_ms) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (db.now_iso(), gate, read.get("plate"), read.get("guess"), read.get("conf"), read.get("image"),
             result, visit_id, read.get("reason"), t.get("read_ms")))
        self._emit("plate", {"gate": gate, "plate": read.get("plate"), "display": read.get("display"),
                             "guess": read.get("guess"), "conf": read.get("conf"), "image": read.get("image"),
                             "result": result, "reason": read.get("reason"), "ts": time.time(),
                             "read_ms": t.get("read_ms")})

    def inside_visit(self, plate, exact_only=False):
        """Lượt xe đang trong bãi khớp biển số; cho phép lệch PLATE_MATCH_DIST ký tự nếu chỉ có đúng 1 ứng viên."""
        rows = db.query("SELECT * FROM visits WHERE status='inside' ORDER BY id DESC")
        exact = [r for r in rows if r["plate"] == plate]
        if exact or exact_only:
            return exact[0] if exact else None
        near = [r for r in rows if len(r["plate"]) == len(plate)
                and distance(plate, r["plate"]) <= config.PLATE_MATCH_DIST]
        return near[0] if len(near) == 1 else None

    def handle_entry(self, read=None, mode="auto"):
        """Xe tới cổng vào: kiểm tra biển số, cấp ô trống gần nhất và giữ chỗ.

        read = kết quả PlateReader.read("in"), hoặc None khi không dùng camera biển số (hành vi cũ).
        """
        with self.lock:
            self.sweep_reservations()
            plate = (read or {}).get("plate")
            if read is not None and not plate:
                if config.PLATE_REQUIRED:
                    self.log("warn", "plate_unread", f"Cổng vào: không đọc được biển số — {read.get('reason')}")
                    self._record_read("in", read, "denied_unread")
                    return self._deny("unread", "KHONG DOC DUOC", "bien so xe.", "Lui lai, thu lai")
                self.log("warn", "plate_unread", "Cổng vào: không đọc được biển số, vẫn cho vào (PLATE_REQUIRED=0)")
            if plate and self.inside_visit(plate, exact_only=True):
                self.log("warn", "plate_duplicate", f"Cổng vào: xe {pretty(plate)} đã có trong bãi (trùng biển?) — chặn lại")
                self._record_read("in", read, "denied_duplicate")
                return self._deny("duplicate", "XE DA TRONG BAI", pretty(plate), "Lien he bao ve")
            free = [s for s in self.layout.slot_ids if self.status_of(s) == "free"]
            found = self.layout.nearest_free(free)
            if not found:
                self.log("warn", "gate_in", "Xe tới cổng vào nhưng bãi đã đầy")
                self._record_read("in", read, "denied_full")
                self._emit("state")
                return self._deny("full", "BAI DA DAY", "Xin quay lai sau")
            sid, route = found
            now = time.time()
            visit_id = None
            if plate:
                visit_id = db.execute(
                    "INSERT INTO visits(plate,entry_at,entry_img,entry_conf,entry_mode) VALUES(?,?,?,?,?)",
                    (plate, db.now_iso(), read.get("image"), read.get("conf"), mode))
            self.reservations[sid] = {"at": now, "expires": now + config.RESERVE_TIMEOUT, "route": route,
                                      "plate": plate, "visit_id": visit_id}
            who = f"Xe {pretty(plate)} " if plate else "Xe "
            how = " (quản lý nhập tay)" if mode == "manual" else ""
            self.log("info", "gate_in", f"{who}vào cổng{how}, chỉ định ô {route['label']}", sid)
            self._record_read("in", read, "allowed", visit_id)
            self._emit("state")
            return {"allowed": True, "slot": sid, "label": route["label"], "route": route["path"],
                    "steps": route["steps"], "points": route["points"], "oled": route["oled"],
                    "plate": plate, "display": pretty(plate) if plate else None, "visit_id": visit_id}

    def handle_exit(self, read=None, mode="auto"):
        """Xe tới cổng ra: biển số phải khớp một lượt đang trong bãi; phí tính từ lúc vào cổng đến lúc ra cổng."""
        bye = {"title": "Hen gap lai!", "lines": [], "arrow": "none"}
        if read is None:
            self.log("info", "gate_out", "Xe qua cổng ra")
            return {"allowed": True, "oled": bye}
        with self.lock:
            plate = read.get("plate")
            if not plate:
                if config.PLATE_REQUIRED:
                    self.log("warn", "plate_unread", f"Cổng ra: không đọc được biển số — {read.get('reason')}")
                    self._record_read("out", read, "denied_unread")
                    return self._deny("unread", "KHONG DOC DUOC", "bien so xe.", "Lui lai, thu lai")
                self.log("warn", "plate_unread", "Cổng ra: không đọc được biển số, vẫn cho ra (PLATE_REQUIRED=0)")
                self._record_read("out", read, "allowed")
                return {"allowed": True, "oled": bye}
            visit = self.inside_visit(plate)
            if not visit:
                if config.PLATE_REQUIRED:
                    self.log("warn", "plate_nomatch", f"Cổng ra: xe {pretty(plate)} không có lượt vào — chặn lại")
                    self._record_read("out", read, "denied_nomatch")
                    return self._deny("nomatch", "KHONG KHOP", pretty(plate), "Lien he bao ve")
                self.log("warn", "plate_nomatch", f"Cổng ra: xe {pretty(plate)} không có lượt vào, vẫn cho ra")
                self._record_read("out", read, "allowed")
                return {"allowed": True, "oled": {**bye, "lines": [pretty(plate)]}}
            fee, dur = self.close_visit(visit, read, mode)
            self._record_read("out", read, "allowed", visit["id"])
            fix = f" (lúc vào đọc {pretty(visit['plate'])})" if visit["plate"] != plate else ""
            how = " (quản lý xác nhận)" if mode == "manual" else ""
            self.log("info", "gate_out", f"Xe {pretty(plate)} ra cổng{how}{fix}, gửi {dur // 60} phút, phí {fee:,}đ")
            return {"allowed": True, "plate": visit["plate"], "fee": fee, "duration_s": dur,
                    "oled": {**bye, "lines": [pretty(visit["plate"]), f"Phi {fee:,}d".replace(",", ".")]}}

    def close_visit(self, visit, read=None, mode="auto"):
        entry = datetime.fromisoformat(visit["entry_at"])
        dur = max(0, int((datetime.now(timezone.utc) - entry).total_seconds()))
        fee = calc_fee(dur)
        db.execute("UPDATE visits SET exit_at=?, exit_img=?, exit_conf=?, duration_s=?, fee=?, status='done', "
                   "exit_mode=? WHERE id=?",
                   (db.now_iso(), (read or {}).get("image"), (read or {}).get("conf"), dur, fee, mode, visit["id"]))
        return fee, dur

    # ---------- xuất dữ liệu ----------
    def free_count(self):
        return sum(1 for s in self.layout.slot_ids if self.status_of(s) == "free")

    def pi_slots(self):
        """Danh sách trạng thái gửi cho Pi để điều khiển đèn LED."""
        return [self.status_of(s) for s in self.layout.slot_ids]

    def snapshot(self):
        with self.lock:
            now = time.time()
            slots = []
            for sid in self.layout.slot_ids:
                st = self.status_of(sid)
                item = {"id": sid, "label": self.layout.label(sid), "status": st, "since": self.since[sid],
                        "override": self.overrides.get(sid)}
                if st == "reserved":
                    item["expires_in"] = max(0, int(self.reservations[sid]["expires"] - now))
                    item["route"] = self.reservations[sid]["route"]["path"]
                if st == "occupied" and sid in self.open_session:
                    row = db.one("SELECT entry_at FROM sessions WHERE id=?", (self.open_session[sid],))
                    item["entry_at"] = row["entry_at"] if row else None
                slots.append(item)
            total = len(slots)
            occ = sum(1 for s in slots if s["status"] == "occupied")
            res = sum(1 for s in slots if s["status"] == "reserved")
            return {"slots": slots, "total": total, "occupied": occ, "reserved": res,
                    "free": total - occ - res}
