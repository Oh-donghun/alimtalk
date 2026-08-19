"""쿠팡 WING Open API 발주서 조회 클라이언트
   문서: https://developers.coupang.com/ko/api/shipments/po-list-query-paging-by-day
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import date, timedelta
from urllib.parse import urlencode

import requests

from .common import Shipment, normalize_phone

log = logging.getLogger("alimtalk.coupang")
HOST = "https://api-gateway.coupang.com"


class CoupangError(RuntimeError):
    pass


class Coupang:
    def __init__(self, vendor_id: str, access_key: str, secret_key: str,
                 api_version: str = "v4", timeout: int = 60):
        self.vendor_id = vendor_id
        self.access_key = access_key
        self.secret_key = secret_key
        self.api_version = api_version
        self.timeout = timeout

    # ------------------------------------------------------------ 서명
    def _auth(self, method: str, path: str, query: str) -> str:
        dt = time.strftime("%y%m%d", time.gmtime()) + "T" + time.strftime("%H%M%S", time.gmtime()) + "Z"
        message = dt + method + path + query
        sig = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
        return (f"CEA algorithm=HmacSHA256, access-key={self.access_key}, "
                f"signed-date={dt}, signature={sig}")

    def _get(self, path: str, params: dict) -> dict:
        query = urlencode(params)
        url = f"{HOST}{path}?{query}"
        headers = {"Authorization": self._auth("GET", path, query),
                   "Content-Type": "application/json;charset=UTF-8"}
        r = requests.get(url, headers=headers, timeout=self.timeout)
        if r.status_code != 200:
            raise CoupangError(f"쿠팡 API 오류 {r.status_code}: {r.text[:300]}")
        j = r.json()
        if str(j.get("code")) not in ("200", "0"):
            raise CoupangError(f"쿠팡 API 응답 오류: {j}")
        return j

    # ------------------------------------------------------------ 조회
    def ordersheets(self, status: str = "DEPARTURE", lookback_days: int = 7) -> list[dict]:
        """발주서 목록 조회(일단위 페이징) - nextToken 자동 처리"""
        path = f"/v2/providers/openapi/apis/api/{self.api_version}/vendors/{self.vendor_id}/ordersheets"
        today = date.today()
        params = {"createdAtFrom": (today - timedelta(days=lookback_days)).isoformat(),
                  "createdAtTo": today.isoformat(),
                  "status": status, "maxPerPage": 50}
        out, token = [], None
        while True:
            if token:
                params["nextToken"] = token
            j = self._get(path, params)
            out.extend(j.get("data") or [])
            token = j.get("nextToken")
            if not token:
                break
        log.info("쿠팡 %s 발주서 %d건", status, len(out))
        return out

    # ------------------------------------------------------------ 변환
    def fetch_shipments(self, shop: str, status: str = "DEPARTURE",
                        lookback_days: int = 7) -> list[Shipment]:
        shipments = []
        for sheet in self.ordersheets(status, lookback_days):
            orderer = sheet.get("orderer") or {}
            names, qty = [], 0
            for it in sheet.get("orderItems") or []:
                if it.get("canceled"):
                    continue
                cnt = int(it.get("shippingCount") or 0) - int(it.get("cancelCount") or 0) \
                    - int(it.get("holdCountForCancel") or 0)
                if cnt <= 0:
                    continue
                # 등록옵션명(sellerProductItemName) 우선, 없으면 노출상품명
                names.append((it.get("sellerProductItemName") or it.get("vendorItemName") or "").strip())
                qty += cnt
            if not names:
                continue
            phone = normalize_phone(orderer.get("ordererNumber") or orderer.get("safeNumber"))
            shipments.append(Shipment(
                shop=shop, channel="coupang",
                order_id=str(sheet.get("orderId")),
                orderer_name=orderer.get("name") or "",
                phone=phone, product_names=names, quantity=qty,
                courier=sheet.get("deliveryCompanyName") or "",
                tracking_no=str(sheet.get("invoiceNumber") or ""),
                shipped_at=(sheet.get("inTrasitDateTime") or
                            (sheet.get("orderItems") or [{}])[0].get("invoiceNumberUploadDate") or "")[:19].replace("T", " "),
                raw=sheet))
        return shipments
