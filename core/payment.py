"""易支付（YiPay）网关客户端。

支持常见的 ``mapi.php`` 创建收款与 ``api.php?act=order`` 查询订单两种接口。
HTTP 通过可注入的 ``http_get`` 进行，便于测试；默认使用 aiohttp。
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from .config import PAY_TYPE_AUTO, PaymentConfig
from .constants import parse_pay_type
from .models import Order

HttpGetter = Callable[[str, float], Awaitable[Mapping[str, Any]]]


class PaymentError(Exception):
    """支付网关调用失败。"""


@dataclass
class CreatePaymentResult:
    ok: bool
    qr_url: str = ""
    message: str = ""
    raw: dict | None = None


@dataclass
class PaymentStatusResult:
    paid: bool = False
    trade_no: str = ""
    message: str = ""
    raw: dict | None = None


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class YiPayClient:
    def __init__(self, cfg: PaymentConfig, http_get: HttpGetter | None = None) -> None:
        self.cfg = cfg
        self._http_get = http_get

    # ------------------------------------------------------------------
    # 签名
    # ------------------------------------------------------------------
    def _sign(self, params: Mapping[str, Any]) -> str:
        items = [
            (str(k), "" if v is None else str(v))
            for k, v in params.items()
            if str(k) not in ("sign", "sign_type") and v is not None and str(v) != ""
        ]
        items.sort(key=lambda kv: kv[0])
        if self.cfg.sign_urlencode:
            query = urllib.parse.urlencode(items)
        else:
            query = "&".join(f"{k}={v}" for k, v in items)
        return _md5(query + self.cfg.key)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    async def _get_json(self, url: str, timeout: float) -> dict:
        if self._http_get is not None:
            data = await self._http_get(url, timeout)
            return data if isinstance(data, dict) else {"_raw": data}
        return await self._aiohttp_get_json(url, timeout)

    async def _aiohttp_get_json(self, url: str, timeout: float) -> dict:
        try:
            import aiohttp
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise PaymentError("未安装 aiohttp，无法调用支付网关") from exc
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    text = await resp.text()
        except Exception as exc:  # noqa: BLE001
            raise PaymentError(f"请求支付网关失败：{exc}") from exc
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise PaymentError(f"支付网关返回非 JSON 内容：{text[:120]}") from exc
        if not isinstance(data, dict):
            raise PaymentError(f"支付网关返回格式异常：{text[:120]}")
        return data

    @staticmethod
    def _build_url(base: str, params: Mapping[str, Any]) -> str:
        cleaned = {str(k): str(v) for k, v in params.items() if v is not None and str(v) != ""}
        query = urllib.parse.urlencode(cleaned)
        return f"{base}?{query}" if query else base

    # ------------------------------------------------------------------
    # 创建收款
    # ------------------------------------------------------------------
    def _create_params(
        self, order: Order, shop_name: str, pay_type: str | None = None
    ) -> dict:
        name = f"{shop_name}-{order.order_id}"[:64]
        method = str(pay_type or self.cfg.pay_type or PAY_TYPE_AUTO).strip()
        parsed = parse_pay_type(method)
        if parsed:
            method = parsed
        params = {
            "pid": self.cfg.pid,
            "out_trade_no": order.order_id,
            "money": f"{order.total:.2f}",
            "name": name,
            "notify_url": self.cfg.notify_url,
            "return_url": self.cfg.return_url,
            "param": f"sam|{order.order_id}",
        }
        # auto（不限）时不传 type：网关会跳转收银台，让买家自选支付方式。
        if method and method != PAY_TYPE_AUTO:
            params["type"] = method
        return {k: v for k, v in params.items() if v not in (None, "")}

    async def create_payment(
        self,
        order: Order,
        shop_name: str = "山姆代购",
        pay_type: str | None = None,
    ) -> CreatePaymentResult:
        if not self.cfg.configured:
            return CreatePaymentResult(ok=False, message="未配置易支付网关（gateway/pid/key）")
        params = self._create_params(order, shop_name, pay_type)
        params["sign"] = self._sign(params)
        params["sign_type"] = self.cfg.sign_type
        url = self._build_url(self.cfg.create_url(), params)
        try:
            data = await self._get_json(url, self.cfg.create_timeout)
        except PaymentError as exc:
            return CreatePaymentResult(ok=False, message=str(exc))

        qr_url = self._extract_qr_url(data)
        code = data.get("code")
        ok_codes = {1, "1"}
        if qr_url:
            return CreatePaymentResult(ok=True, qr_url=qr_url, raw=data)
        if code not in ok_codes and qr_url is None:
            msg = str(data.get("msg") or data.get("message") or "未知错误")
            return CreatePaymentResult(ok=False, message=f"生成收款码失败：{msg}", raw=data)
        return CreatePaymentResult(ok=False, message="生成收款码失败：网关未返回二维码地址", raw=data)

    @staticmethod
    def _extract_qr_url(data: Mapping[str, Any]) -> str:
        for key in ("qrcode", "payurl", "code_url", "qr", "url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    # ------------------------------------------------------------------
    # 查询支付状态
    # ------------------------------------------------------------------
    def _query_params(self, order: Order) -> dict:
        params: dict[str, Any] = {
            "pid": self.cfg.pid,
            "out_trade_no": order.order_id,
        }
        if self.cfg.query_act:
            params["act"] = self.cfg.query_act
        if self.cfg.query_auth == "key":
            params["key"] = self.cfg.key
        else:
            params["sign"] = self._sign(params)
            params["sign_type"] = self.cfg.sign_type
        return params

    async def query_payment(self, order: Order) -> PaymentStatusResult:
        if not self.cfg.configured:
            return PaymentStatusResult(paid=False, message="未配置易支付网关")
        url = self._build_url(self.cfg.query_url(), self._query_params(order))
        try:
            data = await self._get_json(url, self.cfg.query_timeout)
        except PaymentError as exc:
            return PaymentStatusResult(paid=False, message=str(exc))

        code = data.get("code")
        if code is not None and code not in (1, "1", 0, "0", 200, "200"):
            msg = str(data.get("msg") or data.get("message") or "查询失败")
            return PaymentStatusResult(paid=False, message=f"查询订单失败：{msg}", raw=data)

        paid = self._is_paid(data)
        trade_no = str(data.get("trade_no") or data.get("trade_no_") or "")
        if paid:
            return PaymentStatusResult(paid=True, trade_no=trade_no, raw=data)
        return PaymentStatusResult(paid=False, trade_no=trade_no, raw=data)

    def _is_paid(self, data: Mapping[str, Any]) -> bool:
        trade_status = str(data.get("trade_status") or "").strip().upper()
        if trade_status and trade_status in self.cfg.paid_trade_status:
            return True
        status = data.get("status")
        if status is not None:
            try:
                if int(status) in self.cfg.paid_status_values:
                    return True
            except (TypeError, ValueError):
                pass
            if str(status).strip().upper() in self.cfg.paid_trade_status:
                return True
        if data.get("paid") is True:
            return True
        return False
