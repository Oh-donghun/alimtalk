"""설정 저장소 - 휴무일/일시정지 상태를 파일 하나(settings.json)로 관리.
   웹 관리페이지에서 고치면 다음 자동실행이 바로 반영됩니다.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Lock

_lock = Lock()
DEFAULT = {"paused": False, "paused_reason": "", "holidays": [], "notes": {}}


class Settings:
    def __init__(self, base_dir: str | Path):
        self.path = Path(base_dir, "settings.json")

    def load(self) -> dict:
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

    # ---- 편의 함수 ----
    def pause(self, reason: str = ""):
        d = self.load(); d["paused"] = True; d["paused_reason"] = reason; self.save(d)

    def resume(self):
        d = self.load(); d["paused"] = False; d["paused_reason"] = ""; self.save(d)

    def add_holiday(self, ymd: str, note: str = ""):
        d = self.load()
        if ymd not in d["holidays"]:
            d["holidays"].append(ymd)
        d["holidays"] = sorted(x for x in d["holidays"] if x >= date.today().isoformat()[:4] + "-01-01")
        if note:
            d["notes"][ymd] = note
        self.save(d)

    def del_holiday(self, ymd: str):
        d = self.load()
        d["holidays"] = [x for x in d["holidays"] if x != ymd]
        d["notes"].pop(ymd, None)
        self.save(d)

    def upcoming(self, n: int = 12) -> list[tuple[str, str]]:
        d = self.load(); t = date.today().isoformat()
        return [(h, d["notes"].get(h, "")) for h in sorted(d["holidays"]) if h >= t][:n]
