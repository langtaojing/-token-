"""Create/list/disable trial accounts without putting passwords in shell history."""

from __future__ import annotations
import argparse, getpass, sqlite3
from .store import connect, create_user, initialize

parser=argparse.ArgumentParser(description="Manage invite-only trial accounts")
sub=parser.add_subparsers(dest="action",required=True)
add=sub.add_parser("add"); add.add_argument("username"); add.add_argument("--requests",type=int,default=20); add.add_argument("--tokens",type=int,default=20000)
disable=sub.add_parser("disable"); disable.add_argument("username")
sub.add_parser("list")
args=parser.parse_args(); initialize()
if args.action=="add":
    if not 1<=len(args.username)<=40 or not args.username.replace("_","").isalnum(): raise SystemExit("Username must be 1-40 letters, digits, or underscores.")
    if not 1<=args.requests<=1000 or not 1<=args.tokens<=1000000: raise SystemExit("Quota is outside allowed range.")
    password=getpass.getpass("Friend password (12+ chars): "); repeat=getpass.getpass("Repeat password: ")
    if password!=repeat: raise SystemExit("Passwords do not match.")
    try: create_user(args.username,password,"member",args.requests,args.tokens)
    except (ValueError,sqlite3.IntegrityError) as exc: raise SystemExit(str(exc))
    print("Account created. Share username and password privately.")
elif args.action=="disable":
    with connect() as db:
        user=db.execute("SELECT id,role FROM users WHERE username=?",(args.username,)).fetchone()
        if not user or user["role"]!="member": raise SystemExit("Member not found.")
        db.execute("UPDATE users SET active=0 WHERE id=?",(user["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?",(user["id"],))
    print("Account disabled and sessions revoked.")
else:
    with connect() as db:
        for u in db.execute("SELECT username,role,active,daily_requests,daily_tokens FROM users ORDER BY id"):
            print(u["username"],u["role"],"active" if u["active"] else "disabled",u["daily_requests"],u["daily_tokens"])
