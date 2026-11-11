"""Pi Camera -> luồng MJPEG qua HTTP (http://<ip-pi>:8081/stream.mjpg) + thống kê độ ổn định."""
import collections
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Output(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.cond = threading.Condition()
        self.count = 0
        self.stamps = collections.deque(maxlen=600)

    def write(self, buf):
        with self.cond:
            self.frame = bytes(buf)
            self.count += 1
            self.stamps.append(time.time())
            self.cond.notify_all()
        return len(buf)


class CameraStreamer:
    def __init__(self, width=640, height=480, fps=15, port=8081, hflip=False, vflip=False):
        self.width, self.height, self.fps, self.port = width, height, fps, port
        self.hflip, self.vflip = hflip, vflip
        self.out = _Output()
        self.cam = None
        self.httpd = None

    def start(self):
        try:
            from libcamera import Transform
            from picamera2 import Picamera2
            from picamera2.encoders import JpegEncoder
            from picamera2.outputs import FileOutput
        except ImportError as e:
            raise RuntimeError("Thiếu picamera2: sudo apt install -y python3-picamera2 "
                               "(và tạo venv với --system-site-packages)") from e
        self.cam = Picamera2()
        cfg = self.cam.create_video_configuration(
            main={"size": (self.width, self.height)},
            transform=Transform(hflip=self.hflip, vflip=self.vflip),
            controls={"FrameRate": self.fps})
        self.cam.configure(cfg)
        self.cam.start_recording(JpegEncoder(), FileOutput(self.out))
        self._serve()
        return self

    def _serve(self):
        out = self.out

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/snapshot"):
                    with out.cond:
                        out.cond.wait(2)
                        frame = out.frame
                    if not frame:
                        self.send_error(503)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    return
                if not self.path.startswith("/stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<img src='/stream.mjpg' style='max-width:100%'>")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
                self.end_headers()
                try:
                    while True:
                        with out.cond:
                            out.cond.wait(2)
                            frame = out.frame
                        if frame:
                            self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def snapshot(self):
        with self.out.cond:
            self.out.cond.wait(2)
            return self.out.frame

    def stats(self, window_s=5.0):
        """fps trung bình, khoảng trống lớn nhất giữa 2 khung (giây) và số khung trong cửa sổ."""
        now = time.time()
        st = [t for t in list(self.out.stamps) if now - t <= window_s]
        if len(st) < 2:
            return {"fps": 0.0, "max_gap": None, "frames": len(st), "total": self.out.count}
        gaps = [b - a for a, b in zip(st, st[1:])]
        return {"fps": round((len(st) - 1) / (st[-1] - st[0]), 1), "max_gap": round(max(gaps), 3),
                "frames": len(st), "total": self.out.count}

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
        if self.cam:
            try:
                self.cam.stop_recording()
                self.cam.close()
            except Exception:
                pass
