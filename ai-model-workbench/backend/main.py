from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .store import authenticate, connect, create_session, delete_session, finish_call, initialize, reserve_call, usage, user_for_session

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

@app.post("/api/logout")
async def logout(response: Response, ai_team_session: str | None = Cookie(default=None)):
    delete_session(ai_team_session); response.delete_cookie("ai_team_session"); return {"ok": True}

@app.get("/api/me")
async def me(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    with connect() as db: requests_used, tokens_used = usage(db, user["id"], __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat())
    return {"username": user["username"], "role": user["role"], "daily_requests": user["daily_requests"], "daily_tokens": user["daily_tokens"], "requests_used": requests_used, "tokens_used": tokens_used}

@app.post("/api/chat")
async def chat(request: ChatRequest, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session); prompt = request.prompt.strip(); api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if not api_key: raise HTTPException(503, "服务尚未配置 MiniMax API Key。")
    day = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    try: call_id = reserve_call(user, MINIMAX_MODEL, day)
    except ValueError as exc: raise HTTPException(429, str(exc)) from None
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(MINIMAX_URL, json={"model": MINIMAX_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False}, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}); r.raise_for_status(); data = r.json()
    except httpx.TimeoutException:
        finish_call(call_id, "failed"); raise HTTPException(504, "模型请求超时。") from None
    except httpx.HTTPStatusError:
        finish_call(call_id, "failed"); raise HTTPException(502, "模型服务返回错误，请稍后重试。") from None
    except (httpx.RequestError, ValueError):
        finish_call(call_id, "failed"); raise HTTPException(502, "无法连接模型服务。") from None
    choices = data.get("choices") or []; answer = (choices[0].get("message") or {}).get("content") if choices else None; usage_data = data.get("usage") or {}
    if not isinstance(answer, str) or not answer.strip():
        finish_call(call_id, "failed"); raise HTTPException(502, "模型没有返回文本回答。")
    total = int(usage_data.get("total_tokens") or 0); latency = round((perf_counter()-started)*1000)
    finish_call(call_id, "success", int(usage_data.get("prompt_tokens") or 0), int(usage_data.get("completion_tokens") or 0), total, latency)
    return {"answer": answer, "model": data.get("model") or MINIMAX_MODEL, "usage": {"total_tokens": total}, "latency_ms": latency}

@app.get("/")
async def index(): return FileResponse(ROOT / "index.html")

@app.get("/styles.css")
async def styles(): return FileResponse(ROOT / "styles.css")
