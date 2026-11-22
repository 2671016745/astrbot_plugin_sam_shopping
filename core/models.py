"""数据模型：商品、购物车项、订单。

金额与重量统一用 ``Decimal`` 表示，JSON 序列化时转成字符串以避免浮点误差。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

ORDER_PENDING = "pending"
ORDER_PAID = "paid"
ORDER_EXPIRED = "expired"
ORDER_CANCELLED = "cancelled"

ORDER_STATUS_LABELS = {
    ORDER_PENDING: "待支付",
    ORDER_PAID: "已支付",
    ORDER_EXPIRED: "已过期",
    ORDER_CANCELLED: "已取消",
}


def _dec(value, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str = "p") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@dataclass
class Product:
    id: str
    name: str
    price: Decimal
    weight_kg: Decimal
    category: str
    subcategory: str
    created_at: str = ""
    fee: Decimal = Decimal("0")
    """单件代购费（元/件）；大于 0 时优先于全局代购费规则。"""

    def __post_init__(self) -> None:
        self.price = _dec(self.price)
        self.weight_kg = _dec(self.weight_kg)
        self.fee = _dec(self.fee)

    @property
    def weight(self) -> Decimal:
        return self.weight_kg

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "price": str(self.price),
            "weight_kg": str(self.weight_kg),
            "category": self.category,
            "subcategory": self.subcategory,
            "created_at": self.created_at,
            "fee": str(self.fee),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            price=_dec(data.get("price")),
            weight_kg=_dec(data.get("weight_kg")),
            category=str(data.get("category") or ""),
            subcategory=str(data.get("subcategory") or ""),
            created_at=str(data.get("created_at") or ""),
            fee=_dec(data.get("fee")),
        )


@dataclass
class CartItem:
    product: Product
    qty: int

    @property
    def subtotal(self) -> Decimal:
        return self.product.price * self.qty

    @property
    def weight(self) -> Decimal:
        return self.product.weight_kg * self.qty


@dataclass
class OrderItem:
    product_id: str
    name: str
    price: Decimal
    weight_kg: Decimal
    qty: int

    def __post_init__(self) -> None:
        self.price = _dec(self.price)
        self.weight_kg = _dec(self.weight_kg)

    @property
    def subtotal(self) -> Decimal:
        return self.price * self.qty

    @property
    def weight(self) -> Decimal:
        return self.weight_kg * self.qty

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "price": str(self.price),
            "weight_kg": str(self.weight_kg),
            "qty": self.qty,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrderItem":
        return cls(
            product_id=str(data.get("product_id") or ""),
            name=str(data.get("name") or ""),
            price=_dec(data.get("price")),
            weight_kg=_dec(data.get("weight_kg")),
            qty=int(data.get("qty") or 0),
        )


@dataclass
class Order:
    order_id: str
    user_id: str
    user_name: str
    items: list[OrderItem]
    channel: str
    goods_amount: Decimal
    weight: Decimal
    freight: Decimal
    total: Decimal
    proxy_fee: Decimal = Decimal("0")
    """代购费（元）。"""
    proxy_fee_detail: list[str] = field(default_factory=list)
    """代购费计算明细（已格式化的文本行），用于账单与邮件回显。"""
    status: str = ORDER_PENDING
    created_at: str = ""
    created_ts: float = 0.0
    paid_at: str = ""
    trade_no: str = ""
    email_sent: bool = False
    email_attempts: int = 0
    email_error: str = ""
    consecutive_failures: int = 0
    umo: str = ""
    remark: str = ""

    def __post_init__(self) -> None:
        self.goods_amount = _dec(self.goods_amount)
        self.weight = _dec(self.weight)
        self.freight = _dec(self.freight)
        self.total = _dec(self.total)
        self.proxy_fee = _dec(self.proxy_fee)
        self.proxy_fee_detail = list(self.proxy_fee_detail or [])

    @property
    def status_label(self) -> str:
        return ORDER_STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "items": [item.to_dict() for item in self.items],
            "channel": self.channel,
            "goods_amount": str(self.goods_amount),
            "weight": str(self.weight),
            "freight": str(self.freight),
            "total": str(self.total),
            "proxy_fee": str(self.proxy_fee),
            "proxy_fee_detail": list(self.proxy_fee_detail),
            "status": self.status,
            "created_at": self.created_at,
            "created_ts": self.created_ts,
            "paid_at": self.paid_at,
            "trade_no": self.trade_no,
            "email_sent": self.email_sent,
            "email_attempts": self.email_attempts,
            "email_error": self.email_error,
            "consecutive_failures": self.consecutive_failures,
            "umo": self.umo,
            "remark": self.remark,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        return cls(
            order_id=str(data.get("order_id") or ""),
            user_id=str(data.get("user_id") or ""),
            user_name=str(data.get("user_name") or ""),
            items=[OrderItem.from_dict(x) for x in (data.get("items") or [])],
            channel=str(data.get("channel") or ""),
            goods_amount=_dec(data.get("goods_amount")),
            weight=_dec(data.get("weight")),
            freight=_dec(data.get("freight")),
            total=_dec(data.get("total")),
            proxy_fee=_dec(data.get("proxy_fee")),
            proxy_fee_detail=[str(x) for x in (data.get("proxy_fee_detail") or [])],
            status=str(data.get("status") or ORDER_PENDING),
            created_at=str(data.get("created_at") or ""),
            created_ts=float(data.get("created_ts") or 0.0),
            paid_at=str(data.get("paid_at") or ""),
            trade_no=str(data.get("trade_no") or ""),
            email_sent=bool(data.get("email_sent") or False),
            email_attempts=int(data.get("email_attempts") or 0),
            email_error=str(data.get("email_error") or ""),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            umo=str(data.get("umo") or ""),
            remark=str(data.get("remark") or ""),
        )
