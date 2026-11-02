"""Windows launcher for the local AI Team Hub service."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


PROJECT = Path(os.environ.get("AI_TEAM_HUB_PROJECT", "D:/Codex/AIA/ai-model-workbench"))
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
DATA = PROJECT / "data"
EDGE = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def free_port(master: bool) -> int:
    choices = [9000] if master else range(8000, 8011)
    for port in choices:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError("没有可用端口。请关闭旧版 AI Team Hub 后重试。")


def open_window(port: int, master: bool) -> None:
    url = f"http://127.0.0.1:{port}"
    if not EDGE.exists():
        os.startfile(url)
        return
    profile = DATA / ("edge-master" if master else "edge-client")
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [str(EDGE), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", action="store_true")
    args = parser.parse_args()
    master = args.master or Path(sys.argv[0]).stem.lower() == "master"
    if not PYTHON.exists():
        raise RuntimeError("虚拟环境不存在，请先运行 run-local.ps1。")
    DATA.mkdir(parents=True, exist_ok=True)
    state_file = DATA / ("master-server.json" if master else "client-server.json")
    log_file = DATA / ("master-server.log" if master else "client-server.log")
    err_file = DATA / ("master-server-error.log" if master else "client-server-error.log")

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if healthy(int(state["port"])):
                open_window(int(state["port"]), master)
                return 0
        except Exception:
            pass
        state_file.unlink(missing_ok=True)

    if master and healthy(9000):
        open_window(9000, True)
        return 0
    port = free_port(master)
    env = os.environ.copy()
    if master:
        env["AI_TEAM_HUB_ADMIN_ONLY"] = "1"
    with log_file.open("w", encoding="utf-8") as out, err_file.open("w", encoding="utf-8") as err:
        process = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(PROJECT), stdout=out, stderr=err, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    for _ in range(40):
        if healthy(port):
            state_file.write_text(json.dumps({"pid": process.pid, "port": port}), encoding="utf-8")
            open_window(port, master)
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.5)
    error = err_file.read_text(encoding="utf-8", errors="replace") if err_file.exists() else ""
    raise RuntimeError("后端启动失败。请查看日志：" + str(err_file) + "\n" + error[-1500:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "launcher-error.log").write_text(str(exc), encoding="utf-8")
        raise
