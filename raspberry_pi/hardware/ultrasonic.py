"""Cảm biến siêu âm HC-SR04.

LƯU Ý: chân ECHO ra 5V, phải qua cầu chia áp (1kΩ nối tiếp + 2kΩ xuống GND) trước khi vào GPIO của Pi.
"""
import statistics
import threading
import time

from gpiozero import DigitalInputDevice, DigitalOutputDevice

FAR_CM = 999.0


class Ultrasonic:
    def __init__(self, trig, echo):
        self.trig = DigitalOutputDevice(trig)
        self.echo = DigitalInputDevice(echo, pull_up=False)

    def read_cm(self, timeout=0.03):
        """Một lần đo (cm). Trả về None nếu không có tín hiệu phản hồi."""
        self.trig.on()
        time.sleep(0.00001)
        self.trig.off()
        t0 = time.perf_counter()
        while not self.echo.value:
            if time.perf_counter() - t0 > timeout:
                return None
        start = time.perf_counter()
        while self.echo.value:
            if time.perf_counter() - start > timeout:
                return None
        return (time.perf_counter() - start) * 34300 / 2

    def read_median(self, n=3):
        vals = []
        for _ in range(n):
            v = self.read_cm()
            if v is not None and 1 < v < 400:
                vals.append(v)
            time.sleep(0.015)
        return statistics.median(vals) if vals else FAR_CM

    def close(self):
        self.trig.close()
        self.echo.close()


class GateSensor:
    """Đọc liên tục ở nền và quyết định 'có xe' bằng độ trễ (hysteresis) để chống nhiễu."""

    CONFIRM = 3  # số lần đọc liên tiếp để đổi trạng thái

    def __init__(self, trig, echo, trigger_cm, hz=10, name=""):
        self.name = name
        self.us = Ultrasonic(trig, echo)
        self.trigger_cm = trigger_cm
        self.period = 1.0 / hz
        self.distance = FAR_CM
        self.present = False
        self._near = 0
        self._far = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            t0 = time.time()
            d = self.us.read_median(3)
            self.distance = d
            if d < self.trigger_cm:
                self._near += 1
                self._far = 0
                if self._near >= self.CONFIRM:
                    self.present = True
            elif d > self.trigger_cm + 3:  # vùng đệm 3cm
                self._far += 1
                self._near = 0
                if self._far >= self.CONFIRM:
                    self.present = False
            time.sleep(max(0.0, self.period - (time.time() - t0)))

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1)
        self.us.close()
