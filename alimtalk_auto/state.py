"""휴무일 / 일시정지 상태 저장 (state.json) - 관리 페이지에서 조작"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path

_lock = threading.Lock()
DEFAULT = {"paused": False, "paused_reason": "", "holidays": [], "notes": {}}


class State:
    def __init__(self, base_dir: str | Path):
        self.path = Path(base_dir, "state.json")

    def load(self) -> dict:
        with _lock:
            if not self.path.exists():
                return dict(DEFAULT)
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return dict(DEFAULT)
        out = dict(DEFAULT)
        out.update(d)
        return out

    def save(self, d: dict):
        with _lock:
            self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 조작 ----
    def pause(self, reason: str = ""):
        d = self.load(); d["paused"] = True; d["paused_reason"] = reason
        d["paused_at"] = datetime.now().isoformat(timespec="seconds"); self.save(d)

    def resume(self):
        d = self.load(); d["paused"] = False; d["paused_reason"] = ""; self.save(d)

    def add_holiday(self, day: str, note: str = ""):
        d = self.load()
        if day not in d["holidays"]:
            d["holidays"].append(day)
        d["holidays"].sort()
        if note:
            d["notes"][day] = note
        self.save(d)

    def del_holiday(self, day: str):
        d = self.load()
        d["holidays"] = [x for x in d["holidays"] if x != day]
        d["notes"].pop(day, None)
        self.save(d)

    def cleanup_past(self):
        """지난 휴무일 자동 정리"""
        t = date.today().isoformat()
        d = self.load()
        keep = [x for x in d["holidays"] if x >= t]
        if len(keep) != len(d["holidays"]):
            d["holidays"] = keep
            d["notes"] = {k: v for k, v in d["notes"].items() if k in keep}
            self.save(d)
