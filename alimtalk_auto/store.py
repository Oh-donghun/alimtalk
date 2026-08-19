"""발송 이력 저장 (같은 주문에 두 번 보내지 않기 위해)"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class SentLog:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("""CREATE TABLE IF NOT EXISTS sent(
            key TEXT PRIMARY KEY, shop TEXT, channel TEXT, order_id TEXT,
            phone TEXT, orderer TEXT, product TEXT, tracking TEXT,
            sent_at TEXT, mid TEXT, dry_run INTEGER, payload TEXT)""")
        self.conn.commit()

    def has(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

    def add(self, sh, product: str, mid: str = "", dry_run: bool = False):
        self.conn.execute(
            "INSERT OR REPLACE INTO sent VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sh.key(), sh.shop, sh.channel, sh.order_id, sh.phone, sh.orderer_name,
             product, sh.tracking_no, datetime.now().isoformat(timespec="seconds"),
             str(mid), 1 if dry_run else 0, json.dumps(sh.to_dict(), ensure_ascii=False)))
        self.conn.commit()

    def recent(self, n: int = 50):
        return self.conn.execute(
            "SELECT sent_at, shop, channel, order_id, orderer, phone, product, tracking, dry_run "
            "FROM sent ORDER BY sent_at DESC LIMIT ?", (n,)).fetchall()
