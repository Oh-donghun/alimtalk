"""공통 데이터 구조 / 설정 로더 / 로깅"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("alimtalk")


@dataclass
class Shipment:
    """알림톡 1건에 대응하는 발송 단위 (묶음배송 기준)."""
    shop: str                 # ojingeo_mom / donggwang
    channel: str              # naver / coupang / naver_excel / coupang_excel
    order_id: str             # 주문번호 (중복발송 방지 키)
    orderer_name: str         # 주문자
    phone: str                # 수신 번호 (숫자만)
    product_names: list[str] = field(default_factory=list)   # 옵션명들 (묶음이면 여러 개)
    quantity: int = 0
    courier: str = ""
    tracking_no: str = ""
    shipped_at: str = ""      # 발송/송장등록 시각 (YYYY-MM-DD ...)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def key(self) -> str:
        return f"{self.shop}:{self.channel}:{self.order_id}"

    def to_dict(self):
        d = asdict(self)
        d.pop("raw", None)
        return d


def normalize_phone(p: str | None) -> str:
    """전화번호 → 숫자만. +82 → 0 으로. 없으면 ''"""
    if not p:
        return ""
    s = str(p).strip()
    s = s.replace("+82", "0") if s.startswith("+82") else s
    s = re.sub(r"\D", "", s)
    if s.startswith("82") and len(s) >= 11:
        s = "0" + s[2:]
    return s


def load_config(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"설정 파일이 없습니다: {p}  (config.example.yaml 을 복사해서 만드세요)")
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_base_dir"] = str(p.resolve().parent)
    return cfg


def setup_logging(base_dir: str, verbose: bool = False):
    Path(base_dir, "logs").mkdir(exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(
        Path(base_dir, "logs", f"{date.today():%Y-%m}.log"), encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format=fmt, handlers=handlers)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ------------------------------------------------------------------
# 휴무일 저장소 (관리페이지에서 수정 → settings.json)
# ------------------------------------------------------------------
def settings_path(cfg: dict) -> Path:
    return Path(cfg.get("_base_dir", "."), "settings.json")


def load_settings(cfg: dict) -> dict:
    p = settings_path(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"paused": False, "holidays": [], "memo": {}}


def save_settings(cfg: dict, data: dict):
    settings_path(cfg).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def all_holidays(cfg: dict) -> list[str]:
    """config 의 extra_holidays + 관리페이지에서 추가한 휴무일"""
    a = {str(d) for d in (cfg.get("safety", {}).get("extra_holidays") or [])}
    a |= {str(d) for d in (load_settings(cfg).get("holidays") or [])}
    return sorted(a)


def set_pause(cfg: dict, on: bool):
    st = load_settings(cfg)
    st["paused"] = bool(on)
    save_settings(cfg, st)


def add_holiday(cfg: dict, day: str, memo: str = ""):
    st = load_settings(cfg)
    hs = set(st.get("holidays") or [])
    hs.add(day)
    st["holidays"] = sorted(hs)
    if memo:
        st.setdefault("memo", {})[day] = memo
    save_settings(cfg, st)


def del_holiday(cfg: dict, day: str):
    st = load_settings(cfg)
    st["holidays"] = [d for d in (st.get("holidays") or []) if d != day]
    (st.get("memo") or {}).pop(day, None)
    save_settings(cfg, st)


# ------------------------------------------------------------------
# 휴무일 / 일시정지 판단
# ------------------------------------------------------------------
def why_skip_today(cfg: dict, today: date | None = None) -> str | None:
    """오늘 발송을 건너뛰어야 하면 그 이유 문자열, 아니면 None"""
    from .state import State
    today = today or date.today()
    s = cfg.get("safety", {})
    base = cfg.get("_base_dir", ".")

    st = State(base).load()
    if st.get("paused"):
        r = st.get("paused_reason") or ""
        return f"일시정지 중{(' - ' + r) if r else ''}"

    pause = s.get("pause_file", "PAUSE")
    if pause and Path(base, pause).exists():
        return f"일시정지 파일({pause})이 있습니다"

    if s.get("skip_weekends", True) and today.weekday() >= 5:
        return "주말"

    t = today.isoformat()
    if t in set(st.get("holidays") or []):
        note = (st.get("notes") or {}).get(t, "")
        return f"지정 휴무일{(' - ' + note) if note else ''}"

    if t in {str(d) for d in (s.get("extra_holidays") or [])}:
        return "설정된 휴무일(extra_holidays)"

    if s.get("skip_kr_holidays", True):
        try:
            import holidays as _h
            kr = _h.KR(years=today.year)
            if today in kr:
                return f"공휴일({kr.get(today)})"
        except Exception as e:
            log.warning("공휴일 확인 실패(무시): %s", e)
    return None
