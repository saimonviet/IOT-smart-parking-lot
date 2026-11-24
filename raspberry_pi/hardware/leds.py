"""Mỗi LED đại diện một ô (thứ tự theo config): sáng = trống, tắt = có xe, nhấp nháy = đang giữ chỗ.

Mỗi LED qua điện trở 330Ω–470Ω (không dùng 220Ω: nhiều LED cùng sáng sẽ vượt giới hạn dòng tổng của GPIO).
"""
import threading
import time

from gpiozero import LED


class LedBank:
    def __init__(self, pins, active_high=True):
        self.leds = []
        for p in pins:
            try:
                self.leds.append(LED(p, active_high=active_high, initial_value=False))
            except Exception as e:
                for led in self.leds:
                    led.close()
                hint = {2: "I2C", 3: "I2C", 14: "UART/serial", 15: "UART/serial", 7: "SPI", 8: "SPI",
                        9: "SPI", 10: "SPI", 11: "SPI"}.get(p, "chương trình/driver khác")
                raise RuntimeError(f"Không dùng được GPIO {p} cho LED (có thể đang bị {hint} chiếm): {e}") from e
        self.modes = ["off"] * len(self.leds)   # on | off | blink
        self._lock = threading.Lock()
        self._stop = False
        self._override = False                  # đang chạy chase() thì tạm dừng cập nhật nền
        threading.Thread(target=self._blinker, daemon=True).start()

    def __len__(self):
        return len(self.leds)

    def apply_slots(self, statuses):
        """statuses: danh sách 'free' | 'occupied' | 'reserved' cho ô 1..N."""
        modes = [{"free": "on", "reserved": "blink"}.get(s, "off") for s in statuses]
        with self._lock:
            self.modes = (modes + ["off"] * len(self.leds))[:len(self.leds)]
        self._render(True)

    def _render(self, blink_on):
        if self._override:
            return
        with self._lock:
            modes = list(self.modes)
        for led, m in zip(self.leds, modes):
            led.value = 1 if (m == "on" or (m == "blink" and blink_on)) else 0

    def _blinker(self):
        phase = True
        while not self._stop:
            time.sleep(0.5)
            phase = not phase
            self._render(phase)

    def _all(self, on):
        for led in self.leds:
            led.value = 1 if on else 0

    def chase(self, delay=0.25):
        """Sáng lần lượt đèn 1 -> N (lúc khởi động, để thấy ngay đèn nào cắm sai)."""
        self._override = True
        try:
            self._all(False)
            for led in self.leds:
                led.on()
                time.sleep(delay)
                led.off()
        finally:
            self._override = False
            self._render(True)

    def cleanup(self):
        self._stop = True
        self._all(False)
        for led in self.leds:
            led.close()
