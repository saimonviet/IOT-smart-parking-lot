"""Chạy server với 2 cổng dùng chung một ứng dụng:
  - HTTP  127.0.0.1:8000  — dashboard trên chính máy này, giao diện dev (vite), mock Pi
  - HTTPS 0.0.0.0:8443    — Raspberry Pi (wss://) và các máy khác trong mạng LAN (https://)

Chạy (từ thư mục pc_server):  python run.py
Lần đầu tự tạo chứng chỉ TLS (data/tls/) và khóa Pi (data/pi.key). Xem cấu hình cho Pi: python tools/pi_secret.py
"""
import asyncio
import contextlib
import signal
import sys

import uvicorn

from app import config, tls


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):  # Ctrl+C do main() xử lý chung cho cả hai cổng
        yield


async def main():
    for stream in (sys.stdout, sys.stderr):  # console Windows không phải UTF-8: thay ký tự lạ thay vì crash
        stream.reconfigure(errors="replace")
    if tls.ensure_cert():
        print(f"[tls] đã tạo chứng chỉ tự ký: {config.TLS_CERT}")
    from app.main import app

    http = _Server(uvicorn.Config(app, host=config.HTTP_HOST, port=config.HTTP_PORT))
    https = _Server(uvicorn.Config(app, host=config.TLS_HOST, port=config.TLS_PORT, lifespan="off",
                                   ssl_certfile=str(config.TLS_CERT), ssl_keyfile=str(config.TLS_KEY)))

    def stop(*_):
        for s in (http, https):
            if s.should_exit:
                s.force_exit = True  # Ctrl+C lần 2: thoát ngay
            s.should_exit = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    first = asyncio.create_task(http.serve())  # cổng HTTP chạy lifespan (khởi tạo DB, camera, nhận diện)
    while not http.started and not first.done():
        await asyncio.sleep(0.05)
    if first.done():
        return await first
    print(f"[server] dashboard:  http://localhost:{config.HTTP_PORT}   |   LAN: https://<ip-máy-này>:{config.TLS_PORT}")
    print(f"[server] Raspberry Pi: wss://<ip-máy-này>:{config.TLS_PORT}  (vân tay TLS {tls.fingerprint()[:16]}...)")
    await asyncio.gather(first, https.serve())


if __name__ == "__main__":
    asyncio.run(main())
