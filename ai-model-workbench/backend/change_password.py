"""Change an existing account password without putting it in shell history."""

import argparse
import getpass
import sqlite3

from .store import DB_PATH, hash_password, initialize

parser = argparse.ArgumentParser()
parser.add_argument("username")
args = parser.parse_args()
initialize()
password = getpass.getpass("New password: ")
repeat = getpass.getpass("Repeat new password: ")
if password != repeat:
    raise SystemExit("Passwords do not match.")
with sqlite3.connect(DB_PATH) as db:
    row = db.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
    if row is None:
        raise SystemExit("Account not found.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row[0]))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (row[0],))
print("Password changed; existing sessions have been revoked.")
