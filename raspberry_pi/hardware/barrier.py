"""Rào chắn dùng servo SG90.

PWM phần mềm hay rung. Nên chạy:  sudo pigpiod  và đặt  GPIOZERO_PIN_FACTORY=pigpio  để servo đứng yên.
"""
import threading
import time

from gpiozero import AngularServo


class ServoBarrier:
    TRAVEL_S = 0.8  # thời gian ước lượng servo quay xong

    def __init__(self, pin, closed_angle=0, open_angle=90):
        self.servo = AngularServo(pin, min_angle=0, max_angle=180,
                                  min_pulse_width=0.0005, max_pulse_width=0.0024)
        self.closed_angle, self.open_angle = closed_angle, open_angle
        self._state = "closed"
        self._move(closed_angle)

    @property
    def state(self):
        return self._state

    def _move(self, angle, final=None):
        self.servo.angle = angle

        def settle():
            time.sleep(self.TRAVEL_S)
            if final:
                self._state = final
            self.servo.detach()  # ngắt xung để hết rung
        threading.Thread(target=settle, daemon=True).start()

    def open(self):
        self._state = "opening"
        self._move(self.open_angle, "open")

    def close(self):
        self._state = "closing"
        self._move(self.closed_angle, "closed")

    def wait_idle(self, timeout=5):
        t0 = time.time()
        while self._state in ("opening", "closing") and time.time() - t0 < timeout:
            time.sleep(0.05)

    def cleanup(self):
        self.servo.detach()
        self.servo.close()
