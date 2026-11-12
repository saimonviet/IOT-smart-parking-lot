"""Servo xoay ESP32-CAM (đọc biển số) về phía cổng đang có xe — một camera dùng chung cho cả 2 cổng.

Mỗi lần đọc biển, cổng phải "mượn" camera: acquire(gate) -> xoay tới góc của cổng, chờ ổn định -> đọc -> release().
Nhiều xe cùng lúc thì xếp hàng, CỔNG RA ĐƯỢC ƯU TIÊN: yêu cầu của cổng vào phải chờ một khoảng ngắn (priority_window_s)
để nếu cổng ra cũng vừa có xe thì cổng ra được phục vụ trước; cổng vào chỉ được cấp khi không còn xe ra nào đang chờ.
"""
import threading
import time

from gpiozero import AngularServo


class CamMount:
    PRIORITY = ("out", "in")   # thứ tự ưu tiên khi cùng chờ

    def __init__(self, pin, angles, travel_s=0.6, settle_s=0.4, priority_window_s=0.3, hold=False):
        self.servo = AngularServo(pin, min_angle=0, max_angle=180,
                                  min_pulse_width=0.0005, max_pulse_width=0.0024)
        self.angles = angles                   # {"in": độ, "out": độ}
        self.travel_s, self.settle_s = travel_s, settle_s
        self.window = priority_window_s
        self.hold = hold                       # True: giữ xung PWM (camera không bị lệch nhưng servo có thể rung)
        self.cv = threading.Condition()
        self.owner = None
        self.waiting = {}                      # gate -> thời điểm bắt đầu chờ
        self.aim = None
        self._point("in")                      # vị trí mặc định: nhìn cổng vào

    def _point(self, gate):
        if self.aim == gate:
            return 0.0
        prev, self.aim = self.aim, gate
        self.servo.angle = self.angles[gate]
        # quay 180° mất lâu hơn quay vài độ; lần đầu (prev=None) chờ đủ
        span = 1.0 if prev is None else abs(self.angles[gate] - self.angles[prev]) / 180
        wait = self.travel_s * max(span, 0.3) + self.settle_s
        time.sleep(wait)                       # chờ servo tới nơi + camera hết rung
        if not self.hold:
            self.servo.detach()
        return wait

    def _my_turn(self, gate):
        if self.owner is not None:
            return False
        for g in self.PRIORITY:
            if g == gate:
                break
            if g in self.waiting:              # có cổng ưu tiên hơn đang chờ
                return False
        if gate != self.PRIORITY[0]:           # cổng ít ưu tiên: chờ hết cửa sổ để cổng ra kịp xếp hàng
            return time.time() - self.waiting[gate] >= self.window
        return True

    def acquire(self, gate, timeout=30, on_wait=None):
        """Chờ tới lượt rồi xoay camera về `gate`. Trả về số giây đã chờ (gồm cả lúc xoay). on_wait(): gọi 1 lần nếu phải chờ cổng kia."""
        t0 = time.time()
        notified = False
        with self.cv:
            self.waiting[gate] = t0
            try:
                while not self._my_turn(gate):
                    if time.time() - t0 > timeout:
                        raise TimeoutError(f"chờ camera quá {timeout}s")
                    if on_wait and not notified and self.owner not in (None, gate):
                        notified = True
                        on_wait()
                    self.cv.wait(0.05)
                self.owner = gate
            finally:
                self.waiting.pop(gate, None)
        self._point(gate)                      # xoay ngoài lock (mất ~1s), cổng kia vẫn xếp hàng được
        return time.time() - t0

    def release(self, gate):
        with self.cv:
            if self.owner == gate:
                self.owner = None
            self.cv.notify_all()

    def cleanup(self):
        self.servo.detach()
        self.servo.close()
