"""Run from a systemd timer every 30 minutes."""
import os
from dotenv import load_dotenv
from pathlib import Path

root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")
from .metrics import save_network_sample

url = os.getenv("MINIMAX_API_URL", "https://api.minimax.cn/v1/text/chatcompletion_v2")
result = save_network_sample(url)
print({"status": result["status"], "attempts": result["attempts"], "failed": result["failed"], "avg_connect_ms": result["avg_connect_ms"]})
