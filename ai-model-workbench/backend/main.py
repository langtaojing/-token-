from __future__ import annotations

import os
import asyncio
import sqlite3
import subprocess
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .orchestrator import ProviderError, run_orchestration
from .rate_limit import check_and_record, initialize as initialize_rate_limit
from .metrics import network_history, usage_snapshot
from .plans import PLANS
from .store import add_file, add_message, authenticate, connect, create_plan_order, create_session, create_user, decide_plan_order, delete_session, finish_call, get_file, get_or_create_conversation, initialize, list_files, list_plan_orders, list_users, recent_messages, remove_file, reserve_call, today, update_user, usage, user_for_session, username_exists
from .speech import CONVERTIBLE_SUFFIXES, MAX_AUDIO_BYTES, SpeechError, transcribe

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DATA_DIR = Path(os.getenv("AI_TEAM_HUB_DATA_DIR", str(ROOT / "data")))
PRODUCTION = os.getenv("AI_TEAM_HUB_PRODUCTION") == "1"
MINIMAX_URL = os.getenv("MINIMAX_API_URL", "https://api.minimax.cn/v1/text/chatcompletion_v2")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
app = FastAPI(title="AI Team Hub", docs_url=None, redoc_url=None)
initialize()
initialize_rate_limit()

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)

class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    mode: str = "fast"

class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)
    repeat: str = Field(min_length=1, max_length=200)

class UserAdminRequest(BaseModel):
    daily_requests: int = Field(ge=1, le=1000)
    daily_tokens: int = Field(ge=1, le=1_000_000)
    active: bool | None = None

class PlanRequest(BaseModel):
    plan_id: str

class PlanDecision(BaseModel):
    approve: bool

ALLOWED_UPLOADS = {".pdf", ".docx", ".txt", ".md", ".mp4", ".mov", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".aiff", ".webm", ".png", ".jpg", ".jpeg", ".webp"}
AUDIO_UPLOADS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".aiff", ".webm", ".mp4", ".mov"}
IMAGE_UPLOADS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

def extract_document_text(path: Path, suffix: str) -> str:
    if suffix in {'.txt','.md'}: return path.read_text(encoding='utf-8', errors='replace')[:200000]
    if suffix == '.pdf':
        from pypdf import PdfReader
        return '\\n'.join((page.extract_text() or '') for page in PdfReader(str(path)).pages)[:200000]
    if suffix == '.docx':
        from docx import Document
        return '\\n'.join(p.text for p in Document(str(path)).paragraphs)[:200000]
    return ''

def current_user(session: str | None):
    user = user_for_session(session)
    if not user: raise HTTPException(401, "请先登录。")
    if os.getenv("AI_TEAM_HUB_ADMIN_ONLY") == "1" and user["role"] != "admin":
        raise HTTPException(403, "此入口仅限管理员使用。")
    return user

@app.get("/api/health")
async def health():
    return {"mode": "live" if os.getenv("MINIMAX_API_KEY", "").strip() else "unconfigured", "model": MINIMAX_MODEL}

@app.post("/api/login")
async def login(request: LoginRequest, response: Response, http_request: Request):
    if PRODUCTION and not check_and_record(http_request.client.host if http_request.client else "unknown", "login", 30):
        raise HTTPException(429, "登录尝试过多，请稍后再试。")
    user = authenticate(request.username.strip(), request.password)
    if not user: raise HTTPException(401, "用户名或密码错误。")
    token = create_session(user["id"])
    response.set_cookie("ai_team_session", token, httponly=True, secure=PRODUCTION, samesite="lax", max_age=7*24*3600)
    return {"username": user["username"], "role": user["role"]}

@app.post("/api/register")
async def register(request: RegisterRequest, response: Response, http_request: Request):
    if PRODUCTION and not check_and_record(http_request.client.host if http_request.client else "unknown", "register", 5):
        raise HTTPException(429, "注册过于频繁，请稍后再试。")
    if os.getenv("AI_TEAM_HUB_ADMIN_ONLY") == "1": raise HTTPException(403, "管理员入口不开放注册。")
    username = request.username.strip()
    if request.password != request.repeat: raise HTTPException(400, "两次密码不一致。")
    if not username: raise HTTPException(400, "用户名不能为空。")
    if username_exists(username): raise HTTPException(409, "用户名已经存在，请换一个。")
    try: user_id = create_user(username, request.password, "member", 20, 20000)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    except sqlite3.IntegrityError: raise HTTPException(409, "用户名已经存在，请换一个。") from None
    token = create_session(user_id); response.set_cookie("ai_team_session", token, httponly=True, secure=PRODUCTION, samesite="lax", max_age=7*24*3600)
    return {"username": username, "role": "member"}

@app.post("/api/logout")
async def logout(response: Response, ai_team_session: str | None = Cookie(default=None)):
    delete_session(ai_team_session); response.delete_cookie("ai_team_session"); return {"ok": True}

@app.get("/api/me")
async def me(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    with connect() as db: requests_used, tokens_used = usage(db, user["id"], today())
    return {"username": user["username"], "role": user["role"], "daily_requests": user["daily_requests"], "daily_tokens": user["daily_tokens"], "requests_used": requests_used, "tokens_used": tokens_used}

@app.get("/api/files")
async def files(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    return {"files": [dict(row) for row in list_files(user["id"])]}

@app.post("/api/files")
async def upload_file(file: UploadFile = File(...), ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOADS: raise HTTPException(400, "暂不支持这种文件类型。")
    upload_dir = DATA_DIR / "uploads" / str(user["id"]); upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{__import__('secrets').token_hex(12)}{suffix}"; destination = upload_dir / safe_name; total = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                destination.unlink(missing_ok=True); raise HTTPException(413, "文件不能超过 500 MB。")
            output.write(chunk)
    status='uploaded'; text=''
    try:
        text=extract_document_text(destination, suffix)
        if text: status='parsed'
        elif suffix in AUDIO_UPLOADS: status='uploaded_audio_pending'
    except Exception: status='parse_failed'
    if not text and suffix in AUDIO_UPLOADS:
        try:
            spoken=await transcribe(destination.read_bytes(), safe_name)
            if spoken['text']:
                text=spoken['text']; status='transcribed'
        except Exception:
            status='uploaded_audio_pending'
    file_id = add_file(user["id"], file.filename or "unnamed", safe_name, file.content_type or "application/octet-stream", total)
    if text:
        with connect() as db: db.execute("INSERT OR REPLACE INTO file_text(file_id,text,created_at) VALUES(?,?,?)",(file_id,text,__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
    return {"id": file_id, "name": file.filename, "size_bytes": total, "status": status, "text_chars": len(text)}

@app.get("/api/files/{file_id}/text")
async def file_text(file_id: int, ai_team_session: str | None = Cookie(default=None)):
    user=current_user(ai_team_session)
    row=get_file(user["id"],file_id)
    if not row: raise HTTPException(404,"文件不存在。")
    with connect() as db: text=db.execute("SELECT text FROM file_text WHERE file_id=?",(file_id,)).fetchone()
    if not text: raise HTTPException(409,"该文件还没有可提取文本；音频转写可能未完成，请稍后重试，或确认服务器可调用语音识别。")
    return {"text":text["text"]}

@app.delete("/api/files/{file_id}")
async def delete_uploaded_file(file_id: int, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session); row = get_file(user["id"], file_id)
    if not row: raise HTTPException(404, "文件不存在。")
    (DATA_DIR / "uploads" / str(user["id"]) / row["stored_name"]).unlink(missing_ok=True); remove_file(user["id"], file_id)
    return {"ok": True}

@app.post("/api/analyze-image")
async def analyze_image(prompt: str = Form(default="请分析这张图片，描述其中的重要内容、文字和可能的上下文。", max_length=4000), file: UploadFile = File(...), ai_team_session: str | None = Cookie(default=None)):
    user=current_user(ai_team_session); suffix=Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_UPLOADS: raise HTTPException(400, "请选择 PNG、JPG 或 WEBP 图片。")
    image_bytes=await file.read()
    if len(image_bytes)>10*1024*1024: raise HTTPException(413, "图片不能超过 10 MB。")
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"): mime="image/png"
    elif image_bytes.startswith(b"\xff\xd8\xff"): mime="image/jpeg"
    elif image_bytes.startswith(b"RIFF") and image_bytes[8:12]==b"WEBP": mime="image/webp"
    else: raise HTTPException(400, "文件内容不是有效的 PNG、JPG 或 WEBP 图片。")
    try: call_id=reserve_call(user, "MiniMax-M3.1-Flash-vision", today())
    except ValueError as exc: raise HTTPException(429, str(exc)) from None
    try:
        from .orchestrator import MiniMaxProvider
        result=await MiniMaxProvider().analyze_image(image_bytes,mime,prompt)
    except ProviderError as exc:
        finish_call(call_id,"failed"); raise HTTPException(exc.status,str(exc)) from None
    except Exception:
        finish_call(call_id,"failed"); raise HTTPException(502,"图片分析失败，请稍后重试。") from None
    finish_call(call_id,"success",result.prompt_tokens,result.completion_tokens,result.total_tokens,result.latency_ms)
    return {"answer":result.text,"model":result.model,"usage":{"total_tokens":result.total_tokens},"latency_ms":result.latency_ms}

@app.post("/api/speech-to-text")
async def speech_to_text(file: UploadFile = File(...), language: str = Form(default=""), ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if not os.getenv("MINIMAX_API_KEY", "").strip(): raise HTTPException(503, "服务尚未配置 MiniMax API Key。")
    suffix = Path(file.filename or "").suffix.lower() or ".wav"
    if suffix not in CONVERTIBLE_SUFFIXES: raise HTTPException(400, "暂不支持这种音频格式。")
    audio = await file.read()
    if len(audio) > MAX_AUDIO_BYTES: raise HTTPException(413, "录音不能超过 25 MB。")
    if len(audio) < 800: raise HTTPException(400, "录音太短，没有识别到语音。")
    try: call_id = reserve_call(user, "asr-1.0", today())
    except ValueError as exc: raise HTTPException(429, str(exc)) from None
    try:
        result = await transcribe(audio, file.filename or f"audio{suffix}", language.strip())
    except SpeechError as exc:
        finish_call(call_id, "failed"); raise HTTPException(exc.status, str(exc)) from None
    except Exception:
        finish_call(call_id, "failed"); raise HTTPException(502, "语音识别未完成，请稍后重试。") from None
    finish_call(call_id, "success", 0, 0, 0, result["latency_ms"])
    return {"text": result["text"], "duration": result["duration"], "model": result["model"], "latency_ms": result["latency_ms"], "trace_id": result["trace_id"]}

@app.get("/api/admin/users")
async def admin_users(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以管理账号。")
    return {"users": [dict(row) for row in list_users()]}

@app.get("/api/admin/metrics")
async def admin_metrics(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以查看监测数据。")
    snapshot = usage_snapshot()
    history = network_history()
    latest = history[-1] if history else None
    snapshot["provider_network"] = {
        "status": latest["status"] if latest else "no_samples",
        "target": latest["target"] if latest else None,
        "attempts": latest["attempts"] if latest else 0,
        "failed": latest["failed"] if latest else 0,
        "probe_failure_rate_pct": round(latest["failed"] * 100 / latest["attempts"], 1) if latest and latest["attempts"] else None,
        "avg_connect_ms": latest["avg_connect_ms"] if latest else None,
        "sampled_at": latest["sampled_at"] if latest else None,
        "note": "TCP 连通探测失败率，不是网络层丢包率",
    }
    return snapshot

@app.get("/api/admin/network-history")
async def admin_network_history(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以查看监测数据。")
    return {"interval_minutes": 30, "samples": network_history()}

@app.get("/api/plans")
async def plans():
    return {"plans": [{"id": key, **value} for key, value in PLANS.items()], "payment_mode": "manual_review", "notice": "仅提交申请，尚未接入在线支付。"}

@app.get("/api/plan-orders")
async def my_plan_orders(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    return {"orders": [dict(row) for row in list_plan_orders(user["id"])]}

@app.post("/api/plan-orders")
async def request_plan(request: PlanRequest, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if request.plan_id not in PLANS: raise HTTPException(400, "套餐不存在。")
    try: order_id = create_plan_order(user["id"], request.plan_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from None
    return {"id": order_id, "status": "pending", "notice": "申请已提交，等待管理员处理；尚未产生付款。"}

@app.get("/api/admin/plan-orders")
async def admin_plan_orders(ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以查看套餐申请。")
    return {"orders": [dict(row) for row in list_plan_orders()]}

@app.post("/api/admin/plan-orders/{order_id}/decision")
async def admin_plan_decision(order_id: int, decision: PlanDecision, ai_team_session: str | None = Cookie(default=None)):
    user = current_user(ai_team_session)
    if user["role"] != "admin": raise HTTPException(403, "只有管理员可以处理套餐申请。")
    orders = [row for row in list_plan_orders() if row["id"] == order_id]
    if not orders: raise HTTPException(404, "申请不存在。")
    plan = PLANS.get(orders[0]["plan_id"])
    if not plan: raise HTTPException(400, "套餐配置不存在。")
    try: decide_plan_order(order_id, decision.approve, plan["daily_requests"], plan["daily_tokens"])
    except ValueError as exc: raise HTTPException(409, str(exc)) from None
    return {"ok": True, "status": "approved" if decision.approve else "rejected"}

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
    if request.mode not in ("fast", "deep"): raise HTTPException(400, "不支持的处理模式。")
    day = today()
    try: call_id = reserve_call(user, MINIMAX_MODEL, day)
    except ValueError as exc: raise HTTPException(429, str(exc)) from None
    conversation=get_or_create_conversation(user["id"])
    context=recent_messages(conversation["id"], 12)
    context_text="\n".join(f"{row['role']}: {row['content']}" for row in context)
    enriched_prompt=("这是同一位用户的连续对话，请参考历史上下文。\n"+context_text+"\n\n当前问题：\n"+prompt) if context_text else prompt
    try:
        result = await run_orchestration(enriched_prompt, mode=request.mode)
    except ProviderError as exc:
        finish_call(call_id, "failed")
        raise HTTPException(exc.status, str(exc)) from None
    except Exception:
        finish_call(call_id, "failed")
        raise HTTPException(502, "模型请求未完成，请稍后重试。") from None
    finish_call(call_id, "success", result.prompt_tokens, result.completion_tokens, result.total_tokens, result.latency_ms)
    add_message(conversation["id"], "user", prompt)
    add_message(conversation["id"], "assistant", result.answer)
    return {"answer": result.answer, "model": result.model, "plan": result.plan, "stages": result.stages, "usage": {"total_tokens": result.total_tokens}, "latency_ms": result.latency_ms}

@app.get("/")
async def index(): return FileResponse(ROOT / "index.html")

@app.get("/styles.css")
async def styles(): return FileResponse(ROOT / "styles.css")

@app.get("/trial.js")
async def trial_script(): return FileResponse(ROOT / "trial.js")

@app.get("/manifest.webmanifest")
async def manifest(): return FileResponse(ROOT / "manifest.webmanifest", media_type="application/manifest+json")

@app.get("/ai-team-hub-icon.png")
async def app_icon(): return FileResponse(ROOT / "ai-team-hub-icon.png", media_type="image/png")

