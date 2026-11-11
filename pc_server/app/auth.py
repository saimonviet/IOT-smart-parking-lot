"""Đăng nhập: băm mật khẩu PBKDF2 + token JWT."""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, Request

from . import config, db

ITER = 200_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def ensure_admin():
    if not db.one("SELECT id FROM users WHERE username=?", (config.ADMIN_USER,)):
        db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                   (config.ADMIN_USER, hash_password(config.ADMIN_PASSWORD), "admin", db.now_iso()))
        print(f"[auth] Đã tạo tài khoản quản lý '{config.ADMIN_USER}' (mật khẩu mặc định, hãy đổi sau).")


def make_token(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": user["username"], "role": user["role"], "exp": exp},
                      config.SECRET_KEY, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def current_user(request: Request, token: str = Query(default="")):
    """Chấp nhận Authorization: Bearer ... hoặc ?token=... (cho thẻ <img> và WebSocket)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    data = decode_token(token) if token else None
    if not data:
        raise HTTPException(401, "Chưa đăng nhập hoặc phiên đã hết hạn")
    return data


def require_admin(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Cần quyền quản lý")
    return user
