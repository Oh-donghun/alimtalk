"""네이버 커머스API (스마트스토어) 주문 조회 클라이언트
   문서: https://apicenter.commerce.naver.com/ko/basic/commerce-api
"""
from __future__ import annotations

import base64
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
import requests

from .common import Shipment, normalize_phone

log = logging.getLogger("alimtalk.naver")
BASE = "https://api.commerce.naver.com/external"
KST = timezone(timedelta(hours=9))

# 네이버 택배사 코드 → 한글명
COURIER = {
    "CJGLS": "CJ대한통운", "HANJIN": "한진택배", "LOTTE": "롯데택배", "EPOST": "우체국택배",
    "LOGEN": "로젠택배", "KDEXP": "경동택배", "CVSNET": "GS편의점택배", "CU": "CU편의점택배",
    "HDEXP": "합동택배", "DAESIN": "대신택배", "ILYANG": "일양로지스", "KGB": "KGB택배",
    "CHUNIL": "천일택배", "KUNYOUNG": "건영택배", "HYUNDAI": "롯데택배", "DHL": "DHL",
    "FEDEX": "FEDEX", "UPS": "UPS", "SLX": "SLX택배", "GSPOSTBOX": "GS편의점택배",
    "SEBANG": "세방택배", "HANIPS": "한의사랑택배", "HONAM": "호남택배", "GTX": "GTX로지스",
    "DAEWOON": "대운택배",
}


class NaverError(RuntimeError):
    pass


class NaverCommerce:
    def __init__(self, client_id: str, client_secret: str, timeout: int = 30):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._token = None
        self._token_exp = 0

    # ------------------------------------------------------------ 인증
    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        ts = int(time.time() * 1000)
        pw = f"{self.client_id}_{ts}".encode()
        hashed = bcrypt.hashpw(pw, self.client_secret.encode())
        sign = base64.b64encode(hashed).decode()
        r = requests.post(f"{BASE}/v1/oauth2/token", data={
            "client_id": self.client_id, "timestamp": ts,
            "grant_type": "client_credentials", "client_secret_sign": sign,
            "type": "SELF"}, timeout=self.timeout)
        if r.status_code != 200:
            raise NaverError(f"네이버 토큰 발급 실패 {r.status_code}: {r.text[:300]}")
        j = r.json()
        self._token = j["access_token"]
        self._token_exp = time.time() + int(j.get("expires_in", 10800))
        return self._token

    def _h(self):
        return {"Authorization": f"Bearer {self.token()}",
                "Content-Type": "application/json"}

    # ------------------------------------------------------------ 조회
    def changed_product_order_ids(self, since: datetime, until: datetime | None = None,
                                  changed_type: str = "DISPATCHED") -> list[str]:
        """변경 상품 주문 내역 조회 → 상품주문번호 목록 (자동 페이징)"""
        ids, more_seq = [], None
        until = until or datetime.now(KST)
        params = {"lastChangedFrom": since.astimezone(KST).isoformat(timespec="milliseconds"),
                  "lastChangedTo": until.astimezone(KST).isoformat(timespec="milliseconds"),
                  "lastChangedType": changed_type, "limitCount": 300}
        while True:
            if more_seq:
                params["moreSequence"] = more_seq
            r = requests.get(f"{BASE}/v1/pay-order/seller/product-orders/last-changed-statuses",
                             headers=self._h(), params=params, timeout=self.timeout)
            if r.status_code != 200:
                raise NaverError(f"변경주문 조회 실패 {r.status_code}: {r.text[:300]}")
            data = (r.json() or {}).get("data") or {}
            for it in data.get("lastChangeStatuses") or []:
                ids.append(it["productOrderId"])
            more = data.get("more")
            if more and more.get("moreSequence"):
                more_seq = more["moreSequence"]
                params["lastChangedFrom"] = more.get("moreFrom", params["lastChangedFrom"])
            else:
                break
        log.info("네이버 %s 변경 상품주문 %d건", changed_type, len(ids))
        return ids

    def product_orders(self, product_order_ids: list[str]) -> list[dict]:
        """상품주문 상세 조회 (300건씩)"""
        out = []
        for i in range(0, len(product_order_ids), 300):
            chunk = product_order_ids[i:i + 300]
            r = requests.post(f"{BASE}/v1/pay-order/seller/product-orders/query",
                              headers=self._h(), json={"productOrderIds": chunk},
                              timeout=self.timeout)
            if r.status_code != 200:
                raise NaverError(f"상품주문 상세 조회 실패 {r.status_code}: {r.text[:300]}")
            out.extend((r.json() or {}).get("data") or [])
        return out

    # ------------------------------------------------------------ 변환
    def fetch_shipments(self, shop: str, since: datetime, changed_type: str = "DISPATCHED",
                        courier_map: dict | None = None) -> list[Shipment]:
        cmap = dict(COURIER)
        cmap.update(courier_map or {})
        ids = self.changed_product_order_ids(since, changed_type=changed_type)
        if not ids:
            return []
        rows = self.product_orders(ids)
        # 주문번호(orderId) 기준으로 묶음 → 알림톡 1건
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            po = row.get("productOrder", {})
            od = row.get("order", {})
            grouped[str(od.get("orderId") or po.get("orderId"))].append(row)

        shipments = []
        for order_id, items in grouped.items():
            first = items[0]
            po, od, dv = first.get("productOrder", {}), first.get("order", {}), first.get("delivery", {})
            names, qty = [], 0
            for it in items:
                p = it.get("productOrder", {})
                opt = (p.get("productOption") or "").strip()
                names.append(opt if opt else (p.get("productName") or ""))
                qty += int(p.get("quantity") or 0)
            # 여러 상품주문이 서로 다른 송장일 수도 있어 첫 번째를 대표로 씀
            tracking = dv.get("trackingNumber") or ""
            courier = cmap.get(dv.get("deliveryCompany"), dv.get("deliveryCompany") or "")
            phone = normalize_phone(od.get("ordererTel"))
            shipments.append(Shipment(
                shop=shop, channel="naver", order_id=order_id,
                orderer_name=od.get("ordererName") or "",
                phone=phone, product_names=names, quantity=qty,
                courier=courier, tracking_no=tracking,
                shipped_at=(dv.get("sendDate") or "")[:19].replace("T", " "),
                raw={"items": items}))
        return shipments
