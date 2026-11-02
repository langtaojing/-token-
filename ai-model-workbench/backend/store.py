from __future__ import annotations
import hashlib, hmac, secrets, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

DB_PATH = Path(os.getenv("AI_TEAM_HUB_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "trial.sqlite3")))

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db

def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, daily_requests INTEGER NOT NULL DEFAULT 20, daily_tokens INTEGER NOT NULL DEFAULT 20000, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, day TEXT NOT NULL, model TEXT NOT NULL, prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0, latency_ms INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_calls_user_day ON calls(user_id, day);
        CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, original_name TEXT NOT NULL, stored_name TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'uploaded', created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id, created_at);
        """)

def now(): return datetime.now(timezone.utc)

def hash_password(password):
    if not password: raise ValueError("Password cannot be empty.")
    salt=secrets.token_bytes(16); iterations=390000; digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"

def verify_password(password, encoded):
    try:
        algorithm,iterations,salt,expected=encoded.split("$")
        if algorithm != "pbkdf2_sha256": return False
        digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),int(iterations))
        return hmac.compare_digest(digest,bytes.fromhex(expected))
    except (ValueError,TypeError): return False

def create_user(username,password,role="member",daily_requests=20,daily_tokens=20000):
    if not username or not username.strip(): raise ValueError("Username cannot be empty.")
    with connect() as db:
        cur=db.execute("INSERT INTO users(username,password_hash,role,daily_requests,daily_tokens,created_at) VALUES(?,?,?,?,?,?)",(username,hash_password(password),role,daily_requests,daily_tokens,now().isoformat()))
        return int(cur.lastrowid)

def list_users():
    with connect() as db: return db.execute("SELECT id,username,role,active,daily_requests,daily_tokens,created_at FROM users ORDER BY id").fetchall()

def update_user(user_id, daily_requests, daily_tokens, active=None):
    with connect() as db:
        if active is None: db.execute("UPDATE users SET daily_requests=?,daily_tokens=? WHERE id=?", (daily_requests,daily_tokens,user_id))
        else: db.execute("UPDATE users SET daily_requests=?,daily_tokens=?,active=? WHERE id=?", (daily_requests,daily_tokens,int(active),user_id))

def username_exists(username):
    with connect() as db: return db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None

def authenticate(username,password):
    with connect() as db: user=db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    dummy="pbkdf2_sha256$390000$"+"00"*16+"$"+"00"*32
    valid=verify_password(password,user["password_hash"] if user else dummy)
    return user if user and user["active"] and valid else None

def create_session(user_id):
    token=secrets.token_urlsafe(32); expires=(now()+timedelta(days=7)).isoformat()
    with connect() as db: db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user_id,expires))
    return token

def user_for_session(token):
    if not token: return None
    with connect() as db: return db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",(hashlib.sha256(token.encode()).hexdigest(),now().isoformat())).fetchone()

def delete_session(token):
    if token:
        with connect() as db: db.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))

def usage(db,user_id,day):
    row=db.execute("SELECT COUNT(*) requests, COALESCE(SUM(total_tokens),0) tokens FROM calls WHERE user_id=? AND day=? AND status IN ('pending','success')",(user_id,day)).fetchone()
    return int(row["requests"]),int(row["tokens"])

def reserve_call(user,model,day):
    db=connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        requests,tokens=usage(db,user["id"],day)
        if requests >= user["daily_requests"]: raise ValueError("已达到今日请求次数上限。")
        if tokens >= user["daily_tokens"]: raise ValueError("已达到今日 Token 上限。")
        n=now(); cur=db.execute("INSERT INTO calls(user_id,created_at,day,model,status) VALUES(?,?,?,?,?)",(user["id"],n.isoformat(),day,model,'pending'))
        db.commit(); return int(cur.lastrowid)
    except Exception:
        db.rollback(); raise
    finally: db.close()

def finish_call(call_id,status,prompt_tokens=0,completion_tokens=0,total_tokens=0,latency_ms=0):
    with connect() as db:
        db.execute("UPDATE calls SET status=?,prompt_tokens=?,completion_tokens=?,total_tokens=?,latency_ms=? WHERE id=?",(status,prompt_tokens,completion_tokens,total_tokens,latency_ms,call_id))

def record_call(db,user_id,model,status,prompt_tokens=0,completion_tokens=0,total_tokens=0,latency_ms=0):
    n=now(); db.execute("INSERT INTO calls(user_id,created_at,day,model,prompt_tokens,completion_tokens,total_tokens,latency_ms,status) VALUES(?,?,?,?,?,?,?,?,?)",(user_id,n.isoformat(),n.date().isoformat(),model,prompt_tokens,completion_tokens,total_tokens,latency_ms,status))

def add_file(user_id, original_name, stored_name, content_type, size_bytes):
    with connect() as db:
        cur=db.execute("INSERT INTO files(user_id,original_name,stored_name,content_type,size_bytes,created_at) VALUES(?,?,?,?,?,?)",(user_id,original_name,stored_name,content_type,size_bytes,now().isoformat()))
        return int(cur.lastrowid)

def list_files(user_id):
    with connect() as db: return db.execute("SELECT id,original_name,content_type,size_bytes,status,created_at FROM files WHERE user_id=? ORDER BY id DESC",(user_id,)).fetchall()

def get_file(user_id, file_id):
    with connect() as db: return db.execute("SELECT * FROM files WHERE id=? AND user_id=?",(file_id,user_id)).fetchone()

def remove_file(user_id, file_id):
    with connect() as db: db.execute("DELETE FROM files WHERE id=? AND user_id=?",(file_id,user_id))
