from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .orchestrator import ProviderError, run_orchestration
from .store import authenticate, connect, create_session, create_user, delete_session, finish_call, initialize, list_users, reserve_call, update_user, usage, user_for_session, username_exists

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
MINIMAX_URL = os.getenv("MINIMAX_API_URL", "https://api.minimax.cn/v1/text/chatcompletion_v2")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
app = FastAPI(title="AI Team Hub", docs_url=None, redoc_url=None)
initialize()

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)

class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)

class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)
    repeat: str = Field(min_length=1, max_length=200)

class UserAdminRequest(BaseModel):
    daily_requests: int = Field(ge=1, le=1000)
    daily_tokens: int = Field(ge=1, le=1_000_000)
    active: bool | None = None

def current_user(session: str | None):
    user = user_for_session(session)
    if not user: raise HTTPException(401, "请先登录。")
    return user

@app.get("/api/health")
async def health():
    return {"mode": "live" if os.getenv("MINIMAX_API_KEY", "").strip() else "unconfigured", "model": MINIMAX_MODEL}

@app.post("/api/login")
async def login(request: LoginRequest, response: Response):
    user = authenticate(request.username.strip(), request.password)
    if not user: raise HTTPException(401, "用户名或密码错误。")
    token = create_session(user["id"])
    response.set_cookie("ai_team_session", token, httponly=True, samesite="lax", max_age=7*24*3600)
    return {"username": user["username"], "role": user["role"]}

@app.post("/api/register")
async def register(request: RegisterRequest, response: Response):
    username = request.username.strip()
    if request.password != request.repeat: raise HTTPException(400, "两次密码不一致。")
    if not username: raise HTTPException(400, "用户名不能为空。")
    if username_exists(username): raise HTTPException(409, "用户名已经存在，请换一个。")
    try: user_id = create_user(username, request.password, "member", 20, 20000)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    except sqlite3.IntegrityError: raise HTTPException(409, "用户名已经存在，请换一个。") from None
    token = create_session(user_id); response.set_cookie("ai_team_session", token, httponly=True, samesite="lax", max_age=7*24*3600)
    return {"username": username, "role": "member"}

@app.post("/api/logout")
async def logout(response: Response, ai_team_session: str | None = Cookie(default=None)):
    delete_session(ai_team_session); response.delete_cookie("ai_team_session"); return {"ok": True}

@app.get("/api/me")
async def me(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    with connect() as db: requests_used, tokens_used = usage(db, user["id"], __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat())
    return {"username": user["username"], "role": user["role"], "daily_requests": user["daily_requests"], "daily_tokens": user["daily_tokens"], "requests_used": requests_used, "tokens_used": tokens_used}

@app.get("/api/admin/users")
async def admin_users(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以管理账号。")
    return {"users": [dict(row) for row in list_users()]}

@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: UserAdminRequest, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以管理账号。")
    with connect() as db: target = db.execute("SELECT id,role FROM users WHERE id=?", (user_id,)).fetchone()
    if not target: raise HTTPException(404, "账号不存在。")
    if target["role"] == "admin" and request.active is False: raise HTTPException(400, "不能停用管理员账号。")
    update_user(user_id, request.daily_requests, request.daily_tokens, request.active)
    return {"ok": True}

@app.post("/api/chat")
async def chat(request: ChatRequest, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session); prompt = request.prompt.strip(); api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if not api_key: raise HTTPException(503, "服务尚未配置 MiniMax API Key。")
    day = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    try: call_id = reserve_call(user, MINIMAX_MODEL, day)
    except ValueError as exc: raise HTTPException(429, str(exc)) from None
    try:
        result = await run_orchestration(prompt)
    except ProviderError as exc:
        finish_call(call_id, "failed")
        raise HTTPException(exc.status, str(exc)) from None
    finish_call(call_id, "success", result.prompt_tokens, result.completion_tokens, result.total_tokens, result.latency_ms)
    return {"answer": result.answer, "model": result.model, "plan": result.plan, "stages": result.stages, "usage": {"total_tokens": result.total_tokens}, "latency_ms": result.latency_ms}

@app.get("/")
async def index(): return FileResponse(ROOT / "index.html")

@app.get("/styles.css")
async def styles(): return FileResponse(ROOT / "styles.css")

@app.get("/trial.js")
async def trial_script(): return FileResponse(ROOT / "trial.js")
