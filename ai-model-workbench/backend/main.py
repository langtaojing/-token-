"""Local-only MiniMax chat backend for AI Team Hub."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MINIMAX_URL = os.getenv(
    "MINIMAX_API_URL", "https://api.minimax.cn/v1/text/chatcompletion_v2"
)
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")

app = FastAPI(title="AI Team Hub Local API", docs_url=None, redoc_url=None)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)


@app.get("/api/health")
async def health() -> dict:
    return {
        "mode": "live" if os.getenv("MINIMAX_API_KEY", "").strip() else "unconfigured",
        "model": MINIMAX_MODEL,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "MiniMax API Key 尚未配置。请查看 README.md。")

    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(422, "请输入问题。")

    payload = {
        "model": MINIMAX_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                MINIMAX_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        raise HTTPException(504, "MiniMax 请求超时，请稍后重试。") from None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            detail = "MiniMax 认证失败，请检查 API Key 和账户权限。"
        elif exc.response.status_code == 429:
            detail = "MiniMax 当前限流，请稍后重试。"
        else:
            detail = f"MiniMax 返回 HTTP {exc.response.status_code}。"
        raise HTTPException(502, detail) from None
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, "连接 MiniMax 失败或返回格式无效。") from None

    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code", 0) != 0:
        raise HTTPException(502, "MiniMax 拒绝了本次请求，请检查模型权限或输入内容。")
    choices = data.get("choices") or []
    answer = (choices[0].get("message") or {}).get("content") if choices else None
    if not isinstance(answer, str) or not answer.strip():
        raise HTTPException(502, "MiniMax 未返回文本回答。")

    usage = data.get("usage") or {}
    return {
        "answer": answer,
        "model": data.get("model") or MINIMAX_MODEL,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "latency_ms": round((perf_counter() - started) * 1000),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(ROOT / "styles.css")


@app.get("/app.js")
async def script() -> FileResponse:
    return FileResponse(ROOT / "app.js")
