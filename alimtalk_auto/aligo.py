"""알리고 알림톡 API 클라이언트  (https://smartsms.aligo.in/alimapi.html)"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

log = logging.getLogger("alimtalk.aligo")
BASE = "https://kakaoapi.aligo.in"


class AligoError(RuntimeError):
    pass


class Aligo:
    def __init__(self, userid: str, apikey: str, sender: str,
                 senderkey: str, tpl_code: str,
                 failover: str = "Y", testmode: str = "N",
                 template_text: str | None = None, timeout: int = 20):
        self.userid = userid
        self.apikey = apikey
        self.sender = re.sub(r"\D", "", str(sender))
        self.senderkey = senderkey
        self.tpl_code = tpl_code
        self.failover = failover
        self.testmode = testmode
        self.timeout = timeout
        self._tpl: dict | None = None
        if template_text:
            self._tpl = {"templtContent": template_text, "templtName": "배송안내",
                         "buttons": [], "templateEmType": "NONE"}

    # ------------------------------------------------------------ 기본 호출
    def _post(self, path: str, data: dict) -> dict:
        payload = {"apikey": self.apikey, "userid": self.userid}
        payload.update(data)
        r = requests.post(BASE + path, data=payload, timeout=self.timeout)
        r.raise_for_status()
        try:
            res = r.json()
        except Exception:
            raise AligoError(f"알리고 응답 파싱 실패: {r.text[:200]}")
        return res

    # ------------------------------------------------------------ 템플릿
    def template(self) -> dict:
        """알리고에 등록된 템플릿(본문/버튼) 조회 - 1회만 호출 후 캐시"""
        if self._tpl:
            return self._tpl
        res = self._post("/akv10/template/list/",
                         {"senderkey": self.senderkey, "tpl_code": self.tpl_code})
        if res.get("code") != 0 or not res.get("list"):
            raise AligoError(f"템플릿 조회 실패: {res}")
        # tpl_code 로 필터했지만 전체가 올 수도 있으니 한번 더 고름
        for t in res["list"]:
            if t.get("templtCode") == self.tpl_code:
                self._tpl = t
                break
        else:
            self._tpl = res["list"][0]
        if self._tpl.get("inspStatus") not in (None, "APR"):
            log.warning("템플릿 %s 승인상태가 %s 입니다 (APR 이어야 발송 가능)",
                        self.tpl_code, self._tpl.get("inspStatus"))
        log.info("템플릿 [%s] %s 로드됨", self.tpl_code, self._tpl.get("templtName"))
        return self._tpl

    @property
    def variables(self) -> list[str]:
        """템플릿 본문에 들어있는 #{변수} 목록"""
        return re.findall(r"#\{([^}]+)\}", self.template().get("templtContent", ""))

    @staticmethod
    def fill(text: str, values: dict[str, str]) -> str:
        def rep(m):
            k = m.group(1)
            if k not in values:
                raise AligoError(f"템플릿 변수 #{{{k}}} 값이 없습니다")
            return str(values[k])
        return re.sub(r"#\{([^}]+)\}", rep, text)

    def render(self, values: dict[str, str]) -> tuple[str, str, str | None, str | None]:
        """(제목, 본문, 강조타이틀, 버튼JSON) 반환"""
        tpl = self.template()
        content = tpl.get("templtContent", "")
        # 알리고 조회결과는 \r\n 이 섞여 올 수 있음 → \n 로 통일 (알리고가 매칭해줌)
        content = content.replace("\r\n", "\n")
        msg = self.fill(content, values)
        subject = (tpl.get("templtName") or "배송안내")[:40]
        emtitle = None
        if tpl.get("templateEmType") == "TEXT" and tpl.get("templtTitle"):
            emtitle = self.fill(tpl["templtTitle"], values)
        button = None
        btns = tpl.get("buttons") or []
        if btns:
            filled = []
            for b in btns:
                bb = {k: (self.fill(v, values) if isinstance(v, str) else v)
                      for k, v in b.items()}
                filled.append(bb)
            button = json.dumps({"button": filled}, ensure_ascii=False)
        return subject, msg, emtitle, button

    # ------------------------------------------------------------ 발송
    def send_batch(self, items: list[dict[str, Any]], dry_run: bool = False) -> dict:
        """
        items: [{"receiver": "0101234...", "recvname": "홍길동", "values": {...}}, ...]  (최대 500)
        """
        if not items:
            return {"code": 0, "message": "no items"}
        if len(items) > 500:
            raise AligoError("한 번에 500건까지만 발송 가능")
        data = {"senderkey": self.senderkey, "tpl_code": self.tpl_code,
                "sender": self.sender, "failover": self.failover,
                "testMode": self.testmode}
        for i, it in enumerate(items, start=1):
            subject, msg, emtitle, button = self.render(it["values"])
            data[f"receiver_{i}"] = it["receiver"]
            data[f"recvname_{i}"] = it.get("recvname", "")
            data[f"subject_{i}"] = subject
            data[f"message_{i}"] = msg
            if emtitle:
                data[f"emtitle_{i}"] = emtitle
            if button:
                data[f"button_{i}"] = button
            if self.failover == "Y":
                data[f"fsubject_{i}"] = subject
                data[f"fmessage_{i}"] = msg
        if dry_run:
            log.info("[DRY-RUN] 알리고 발송 생략 (%d건). 첫 메시지 미리보기:\n%s",
                     len(items), data["message_1"])
            return {"code": 0, "message": "dry-run", "info": {"scnt": len(items), "fcnt": 0}}
        res = self._post("/akv10/alimtalk/send/", data)
        if res.get("code") != 0:
            raise AligoError(f"알림톡 발송 실패: {res}")
        info = res.get("info", {})
        log.info("알리고 발송요청 완료: 정상 %s건 / 오류 %s건 / 잔여포인트 %s (mid=%s)",
                 info.get("scnt"), info.get("fcnt"), info.get("current"), info.get("mid"))
        return res

    def remaining(self) -> dict:
        return self._post("/akv10/heartinfo/", {})

    def remaining_alimtalk(self) -> int | None:
        """알림톡으로 보낼 수 있는 잔여 건수 (ALT_CNT). 못 읽으면 None"""
        try:
            res = self.remaining()
        except Exception as e:
            log.warning("잔여건수 조회 실패: %s", e)
            return None
        d = res.get("list") or res
        for k in ("ALT_CNT", "alt_cnt", "SMS_CNT"):
            if isinstance(d, dict) and k in d:
                try:
                    return int(d[k])
                except Exception:
                    pass
        log.warning("잔여건수 응답 형식을 알 수 없음: %s", res)
        return None


def send_sms(userid: str, apikey: str, sender: str, receivers: list[str],
             message: str, title: str = "", timeout: int = 20) -> dict:
    """알리고 문자 API로 관리자에게 알림 문자 발송 (템플릿 불필요)"""
    import requests as _rq
    sender = re.sub(r"\D", "", str(sender))
    recv = ",".join(re.sub(r"\D", "", str(r)) for r in receivers if r)
    if not recv:
        return {"result_code": 0, "message": "no receiver"}
    msg_type = "LMS" if len(message.encode("euc-kr", "ignore")) > 90 else "SMS"
    data = {"key": apikey, "user_id": userid, "sender": sender, "receiver": recv,
            "msg": message, "msg_type": msg_type}
    if msg_type == "LMS":
        data["title"] = (title or "알림")[:30]
    r = _rq.post("https://apis.aligo.in/send/", data=data, timeout=timeout)
    try:
        res = r.json()
    except Exception:
        raise AligoError(f"문자 발송 응답 오류: {r.text[:200]}")
    if str(res.get("result_code")) not in ("1", "0"):
        log.error("관리자 알림 문자 발송 실패: %s", res)
    return res
