"""옵션명 정리 (동광수산처럼 옵션명이 길고 지저분한 경우)"""
from __future__ import annotations

import re


def clean_option(name: str, rules: dict | None) -> str:
    if not rules or not rules.get("enabled"):
        return re.sub(r"\s+", " ", str(name)).strip()
    s = str(name)
    for pat in rules.get("remove_patterns") or []:
        s = re.sub(pat, " ", s)
    for src, dst in (rules.get("replace") or {}).items():
        s = s.replace(src, dst)
    s = re.sub(r"\s+", " ", s).strip(" ,/-·")
    mx = int(rules.get("max_length") or 0)
    if mx and len(s) > mx:
        s = s[: mx - 1].rstrip() + "…"
    return s


def product_label(names: list[str], rules: dict | None) -> str:
    """여러 옵션 → 알림톡에 넣을 한 줄 문자열"""
    cleaned = [clean_option(n, rules) for n in names if n]
    cleaned = [c for c in cleaned if c]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    join = (rules or {}).get("multi_join") or "외 {n}건"
    return f"{cleaned[0]} {join.format(n=len(cleaned) - 1)}"
