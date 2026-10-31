from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import urllib.request


PROJECT = Path(r"D:\Codex\AIA\ai-model-workbench")
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
DATA = PROJECT / "data"
STATE = DATA / "desktop-app.json"
LOG = DATA / "desktop-app.log"
ERR = DATA / "desktop-app-error.log"
EDGE_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
]


def find_free_port() -> int:
    for port in range(8000, 8011):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError("没有找到可用的本机端口（8000-8010）。")


def wait_until_ready(url: str, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except Exception:
            time.sleep(0.4)
    return False


def stop_backend(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            process.kill()
    try:
        STATE.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    if not PROJECT.exists():
        raise RuntimeError(f"项目目录不存在：{PROJECT}")
    if not PYTHON.exists():
        raise RuntimeError("Python 虚拟环境不存在，请先运行项目目录中的 run-local.ps1。")
    check = subprocess.run([str(PYTHON), "-c", "import uvicorn"], cwd=str(PROJECT), capture_output=True, timeout=10)
    if check.returncode != 0:
        raise RuntimeError("项目虚拟环境缺少 uvicorn，请先运行 run-local.ps1。")
    DATA.mkdir(parents=True, exist_ok=True)
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    log_handle = LOG.open("w", encoding="utf-8")
    err_handle = ERR.open("w", encoding="utf-8")
    backend = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(PROJECT), stdout=log_handle, stderr=err_handle,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    STATE.write_text(json.dumps({"pid": backend.pid, "port": port}, ensure_ascii=False), encoding="utf-8")
    try:
        if not wait_until_ready(url + "/api/health"):
            raise RuntimeError(f"后端启动失败，请查看：{ERR}")
        edge = next((p for p in EDGE_CANDIDATES if p.exists()), None)
        if edge is None:
            raise RuntimeError("没有找到 Microsoft Edge，无法打开桌面窗口。")
        profile = DATA / "desktop-edge-profile"
        profile.mkdir(parents=True, exist_ok=True)
        browser = subprocess.Popen(
            [str(edge), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        browser.wait()
        return 0
    finally:
        stop_backend(backend)
        log_handle.close()
        err_handle.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        DATA.mkdir(parents=True, exist_ok=True)
        ERR.write_text(str(exc), encoding="utf-8")
        raise
