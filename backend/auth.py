import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "app.db"
SECRET_PATH = BASE_DIR / ".auth_secret"
TOKEN_TTL = timedelta(days=7)
PBKDF2_ITERATIONS = 600_000


def _load_secret():
    env_secret = os.getenv("AUTH_SECRET")
    if env_secret:
        return env_secret.encode()
    if SECRET_PATH.exists():
        return SECRET_PATH.read_bytes()
    value = secrets.token_urlsafe(48).encode()
    SECRET_PATH.write_bytes(value)
    SECRET_PATH.chmod(0o600)
    return value


AUTH_SECRET = _load_secret()
security = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/auth", tags=["auth"])


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with get_connection() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        users = connection.execute("SELECT id FROM users").fetchall()
        for user in users:
            ensure_default_knowledge_base(user["id"], connection)


def ensure_default_knowledge_base(user_id: str, connection=None):
    owns_connection = connection is None
    connection = connection or get_connection()
    try:
        existing = connection.execute(
            "SELECT * FROM knowledge_bases WHERE user_id = ? ORDER BY created_at LIMIT 1",
            (user_id,),
        ).fetchone()
        if existing:
            return dict(existing)

        knowledge_base_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?)",
            (knowledge_base_id, user_id, "默认知识库", created_at),
        )
        if owns_connection:
            connection.commit()
        return {
            "id": knowledge_base_id,
            "user_id": user_id,
            "name": "默认知识库",
            "created_at": created_at,
        }
    finally:
        if owns_connection:
            connection.close()


def _hash_password(password: str):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str):
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(user_id: str):
    payload = {"sub": user_id, "exp": int((datetime.now(timezone.utc) + TOKEN_TTL).timestamp())}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_token(token: str):
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise ValueError
        payload = json.loads(_b64decode(body))
        if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError
        return payload
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="登录状态无效或已过期")


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


def _public_user(user):
    return {"id": user["id"], "username": user["username"]}


@router.post("/register")
def register(request: AuthRequest):
    username = request.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少3个字符")
    user_id = str(uuid.uuid4())
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                (user_id, username, _hash_password(request.password), datetime.now(timezone.utc).isoformat()),
            )
            ensure_default_knowledge_base(user_id, connection)
            user = connection.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="用户名已存在")
    return {"token": create_token(user_id), "user": _public_user(user)}


@router.post("/login")
def login(request: AuthRequest):
    with get_connection() as connection:
        user = connection.execute("SELECT * FROM users WHERE username = ?", (request.username.strip(),)).fetchone()
    if not user or not _verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": create_token(user["id"]), "user": _public_user(user)}


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="请先登录")
    payload = decode_token(credentials.credentials)
    with get_connection() as connection:
        user = connection.execute("SELECT id, username FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return dict(user)


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"user": user}


init_database()
