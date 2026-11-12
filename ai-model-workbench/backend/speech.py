"""MiniMax 语音识别（ASR）封装。

- 接口：POST {MINIMAX_ASR_URL}，模型 asr-1.0，multipart 上传音频。
- 浏览器端已把录音统一编码成 16 kHz 单声道 WAV；服务器在有 ffmpeg 时再统一转码，
  以便兼容 mp3 / m4a / webm / mp4 等上传格式，并避免超出接口的大小与时长上限。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter

import httpx

ASR_URL = os.getenv("MINIMAX_ASR_URL", "https://api.minimax.cn/v1/speech_to_text")
ASR_MODEL = os.getenv("MINIMAX_ASR_MODEL", "asr-1.0")
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_AUDIO_SECONDS = 300
DIRECT_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".aiff"}
NEEDS_CONVERSION = {".webm", ".mp4", ".mov", ".m4b", ".wma"}
CONVERTIBLE_SUFFIXES = DIRECT_SUFFIXES | NEEDS_CONVERSION


class SpeechError(Exception):
    def __init__(self, message: str, status: int = 502):
        self.status = status
        super().__init__(message)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _convert_to_wav(src: Path, dst: Path) -> None:
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise SpeechError("音频转码超时，请换一段更短的录音。", 400) from exc
    if result.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        raise SpeechError("音频格式无法转换，请改用 WAV、MP3 或 M4A。", 400)


def _friendly_error(response: httpx.Response) -> tuple[str, int]:
    status = response.status_code
    detail = ""
    try:
        payload = response.json()
        detail = ((payload.get("error") or {}).get("message") or payload.get("message") or "")
    except Exception:
        detail = response.text[:200]
    if status == 401:
        return "MiniMax API Key 无效或已失效，请联系管理员。", 502
    if status == 402:
        return "语音识别额度不足，请在 MiniMax 控制台开通语音识别或充值。", 502
    if status == 413:
        return "音频太大，请控制在 25 MB 以内。", 413
    if status == 422:
        return "音频内容未通过审核，请换一段录音。", 422
    if status == 429:
        return "语音识别请求过于频繁，请稍后重试。", 429
    if status == 400:
        return f"音频无法识别：{detail or '格式或时长不符合要求'}", 400
    if status >= 500:
        return "语音识别服务异常，请稍后重试。", 502
    return f"语音识别失败：{detail or status}", 502


async def transcribe(audio_bytes: bytes, filename: str, language: str = "") -> dict:
    api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise SpeechError("服务尚未配置 MiniMax API Key。", 503)
    suffix = Path(filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in CONVERTIBLE_SUFFIXES:
        raise SpeechError("暂不支持这种音频格式。", 400)
    started = perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / f"input{suffix}"
        source.write_bytes(audio_bytes)
        target = source
        if suffix in NEEDS_CONVERSION:
            if not ffmpeg_available():
                raise SpeechError("服务器缺少音频转换组件，请改用 WAV、MP3 或 M4A。", 503)
            normalized = Path(temp_dir) / "normalized.wav"
            _convert_to_wav(source, normalized)
            target = normalized
        elif suffix == ".wav" and ffmpeg_available():
            normalized = Path(temp_dir) / "normalized.wav"
            _convert_to_wav(source, normalized)
            target = normalized
        payload = {"model": ASR_MODEL}
        if language:
            payload["language"] = language
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                with target.open("rb") as audio_file:
                    response = await client.post(
                        ASR_URL,
                        data=payload,
                        files={"file": (target.name, audio_file, "application/octet-stream")},
                        headers=headers,
                    )
        except httpx.TimeoutException as exc:
            raise SpeechError("语音识别超时，请缩短录音后重试。", 504) from exc
        except httpx.RequestError as exc:
            raise SpeechError("无法连接语音识别服务，请稍后重试。", 502) from exc
        if response.status_code != 200:
            message, status = _friendly_error(response)
            raise SpeechError(message, status)
        try:
            result = response.json()
        except ValueError as exc:
            raise SpeechError("语音识别返回格式无效，请稍后重试。", 502) from exc
        text = (result.get("text") or "").strip()
        return {
            "text": text,
            "duration": result.get("duration"),
            "trace_id": result.get("trace_id"),
            "model": ASR_MODEL,
            "latency_ms": round((perf_counter() - started) * 1000),
        }
