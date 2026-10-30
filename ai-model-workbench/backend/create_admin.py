from __future__ import annotations
import getpass, sqlite3
from .store import connect, create_user, initialize

initialize()
with connect() as db:
    exists = db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()
if exists:
    print('An admin already exists.')
else:
    username=input('Admin username: ').strip(); password=getpass.getpass('Admin password (12+ chars): '); repeat=getpass.getpass('Repeat password: ')
    if password != repeat: raise SystemExit('Passwords do not match.')
    try: create_user(username,password,'admin',100,100000); print('Admin created.')
    except (ValueError,sqlite3.IntegrityError) as exc: raise SystemExit(str(exc))
