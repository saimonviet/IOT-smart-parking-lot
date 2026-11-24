"""Đăng nhập: băm mật khẩu PBKDF2 + token JWT, phân quyền admin (quản lý) / viewer (nhân viên, chỉ xem)."""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, Request

from . import config, db

ITER = 200_000
ROLES = ("admin", "viewer")
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


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


def check_username(name: str) -> str:
    name = (name or "").strip()
    if not USERNAME_RE.match(name):
        raise HTTPException(400, "Tên đăng nhập 3–32 ký tự, chỉ gồm chữ không dấu, số, dấu . _ -")
    return name


def check_password(pw: str, username: str = ""):
    if len(pw or "") < MIN_PASSWORD:
        raise HTTPException(400, f"Mật khẩu phải có ít nhất {MIN_PASSWORD} ký tự")
    if username and pw.lower() == username.lower():
        raise HTTPException(400, "Mật khẩu không được trùng tên đăng nhập")


def active_admins() -> int:
    return db.one("SELECT COUNT(*) n FROM users WHERE role='admin' AND active=1")["n"]


def ensure_admin():
    """Luôn còn ít nhất 1 tài khoản quản lý đang hoạt động (DB mới, hoặc cứu hộ khi lỡ mất hết)."""
    if active_admins() == 0:
        u = db.one("SELECT id FROM users WHERE username=?", (config.ADMIN_USER,))
        if u:
            db.execute("UPDATE users SET role='admin', active=1, must_change=1, token_ver=token_ver+1, "
                       "password_hash=? WHERE id=?", (hash_password(config.ADMIN_PASSWORD), u["id"]))
        else:
            db.execute("INSERT INTO users(username,password_hash,role,created_at,must_change) VALUES(?,?,?,?,1)",
                       (config.ADMIN_USER, hash_password(config.ADMIN_PASSWORD), "admin", db.now_iso()))
        print(f"[auth] Đã tạo tài khoản quản lý '{config.ADMIN_USER}' (mật khẩu mặc định, hãy đổi sau).")
        return
    # DB cũ: tài khoản admin vẫn để mật khẩu mặc định -> nhắc đổi trên giao diện
    u = db.one("SELECT id, password_hash FROM users WHERE username=? AND must_change=0", (config.ADMIN_USER,))
    if u and verify_password(config.ADMIN_PASSWORD, u["password_hash"]):
        db.execute("UPDATE users SET must_change=1 WHERE id=?", (u["id"],))


def public_user(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "role": u["role"], "must_change": bool(u["must_change"])}


def make_token(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": user["username"], "role": user["role"], "ver": user["token_ver"], "exp": exp},
                      config.SECRET_KEY, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def user_from_token(token: str):
    """Token hợp lệ khi: chữ ký + hạn đúng, tài khoản còn tồn tại, chưa bị khóa và token_ver khớp
    (đổi/đặt lại mật khẩu sẽ tăng token_ver => mọi phiên cũ mất hiệu lực). Quyền lấy từ DB nên đổi quyền có tác dụng ngay."""
    data = decode_token(token) if token else None
    if not data:
        return None
    u = db.one("SELECT * FROM users WHERE username=?", (data.get("sub", ""),))
    if not u or not u["active"] or u["token_ver"] != data.get("ver", 0):
        return None
    return {"sub": u["username"], "role": u["role"], "uid": u["id"]}


def current_user(request: Request, token: str = Query(default="")):
    """Chấp nhận Authorization: Bearer ... hoặc ?token=... (cho thẻ <img> và WebSocket)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    user = user_from_token(token)
    if not user:
        raise HTTPException(401, "Chưa đăng nhập hoặc phiên đã hết hạn")
    return user


def require_admin(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Cần quyền quản lý")
    return user
