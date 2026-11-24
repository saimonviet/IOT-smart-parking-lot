"""Điều phối màn hình TFT ở cổng vào: màn 'dính' (hướng dẫn xe vừa vào) > màn chờ; tin cổng ra chỉ hiện thoáng qua.

Không có màn hình (tft=None) thì mọi hàm bỏ qua, chương trình vẫn chạy.
"""
import json
import threading
import time
from pathlib import Path

LOT_CACHE = Path(__file__).resolve().parent.parent / ".lot_cache.json"  # sơ đồ bãi lần trước, mất server vẫn vẽ được


class Screen:
    def __init__(self, tft):
        self.tft = tft
        self.lock = threading.RLock()
        self.free, self.total, self.online = 0, 0, False
        self.statuses = []      # trạng thái từng ô (free/occupied/reserved), cùng thứ tự với lot["slots"]
        self.lot = None         # sơ đồ bãi do server gửi
        self.sticky = None      # hàm vẽ giữ nguyên cho tới khi bị gỡ
        self._token = 0
        try:
            self.lot = json.loads(LOT_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    # --- dữ liệu từ server ---
    def set_lot(self, lot):
        with self.lock:
            self.lot = lot
            try:
                LOT_CACHE.write_text(json.dumps(lot), encoding="utf-8")
            except OSError:
                pass
            self.refresh()

    def set_counts(self, free, total, statuses=None):
        with self.lock:
            statuses = list(statuses or [])
            changed = (free, total, statuses) != (self.free, self.total, self.statuses)
            self.free, self.total, self.statuses = free, total, statuses
            # đang hướng dẫn mà có sơ đồ thì vẽ lại để màu các ô luôn đúng
            if changed and (not self.sticky or self.lot):
                self.refresh()

    def set_online(self, online):
        with self.lock:
            if online != self.online:
                self.online = online
                self.refresh()

    # --- vẽ ---
    def refresh(self):
        with self.lock:
            if not self.tft:
                return
            if self.sticky:
                self.sticky()
            else:
                self.tft.idle(self.free, self.total, self.online, lot=self.lot, statuses=self.statuses)

    def message(self, lines):
        """Hàm vẽ một thông báo chữ lớn (dùng với hold / flash)."""
        return lambda: self.tft.message(lines, big=True)

    def guidance(self, res):
        """Hàm vẽ màn hướng dẫn xe vào: ô được chỉ định, các bước rẽ, đường đi trên sơ đồ, biển số."""
        s = res["screen"]
        return lambda: self.tft.guidance(
            s["title"], s["lines"], s["arrow"], lot=self.lot, statuses=self.statuses,
            route=res.get("points"), target=res.get("slot"), steps=res.get("steps"), label=res.get("label"),
            plate=res.get("display"))

    def hold(self, draw):
        """Giữ màn hình `draw` cho tới khi release()."""
        with self.lock:
            self.sticky = draw
            self._token += 1
            self.refresh()

    def release(self):
        with self.lock:
            self.sticky = None
            self._token += 1
            self.refresh()

    def flash(self, draw, seconds=3.0):
        """Hiện `draw` trong vài giây rồi quay về màn đang có (màn chờ hoặc màn đang giữ)."""
        with self.lock:
            self._token += 1
            token = self._token
            if self.tft:
                draw()

        def back():
            time.sleep(seconds)
            with self.lock:
                if token == self._token:
                    self.refresh()
        threading.Thread(target=back, daemon=True).start()
