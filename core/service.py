"""业务逻辑：商品、购物车、订单、运费试算。

该模块不依赖 AstrBot，方便单元测试与复用。
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from decimal import Decimal

from . import freight
from .config import (
    AMOUNT_BASE_GOODS,
    CHANNEL_EXPRESS,
    CHANNEL_NATIONAL,
    CHANNELS,
    AppConfig,
)
from .models import (
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_PAID,
    ORDER_PENDING,
    CartItem,
    Order,
    OrderItem,
    Product,
    new_id,
)
from .store import Repository

MAX_CATEGORY_LEN = 50
MAX_NAME_LEN = 50
MAX_PRICE = Decimal("1000000")
MAX_WEIGHT = Decimal("1000")
MAX_QTY = 999


class ServiceError(Exception):
    """业务校验失败，消息可直接展示给用户。"""


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(value, max_len: int, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ServiceError(f"{field}不能为空")
    if len(text) > max_len:
        raise ServiceError(f"{field}过长（最多 {max_len} 个字符）")
    if any(ch in text for ch in ("\n", "\r", "\t")):
        text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return text


def _parse_price(value) -> Decimal:
    if value is None:
        raise ServiceError("价格不能为空")
    text = str(value).strip()
    if not text:
        raise ServiceError("价格不能为空")
    try:
        price = Decimal(text)
    except Exception as exc:  # noqa: BLE001 - 统一转成业务错误
        raise ServiceError(f"价格无效：{value}") from exc
    if not price.is_finite() or price <= 0:
        raise ServiceError("价格必须是大于 0 的数字")
    if price > MAX_PRICE:
        raise ServiceError(f"价格不能超过 {MAX_PRICE} 元")
    return price


def _parse_weight(value, default: float) -> Decimal:
    if value is None:
        return Decimal(str(default))
    text = str(value).strip()
    if not text:
        return Decimal(str(default))
    try:
        weight = Decimal(text)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"重量无效：{value}") from exc
    if not weight.is_finite() or weight <= 0:
        raise ServiceError("重量必须是大于 0 的数字")
    if weight > MAX_WEIGHT:
        raise ServiceError(f"重量不能超过 {MAX_WEIGHT} kg")
    return weight


def _parse_qty(value) -> int:
    if value is None:
        raise ServiceError("数量不能为空")
    text = str(value).strip()
    if not text:
        raise ServiceError("数量不能为空")
    if not text.isdigit():
        raise ServiceError("数量必须是正整数")
    qty = int(text)
    if qty <= 0:
        raise ServiceError("数量必须是正整数")
    if qty > MAX_QTY:
        raise ServiceError(f"单次购买数量不能超过 {MAX_QTY}")
    return qty


class SamService:
    def __init__(self, repo: Repository, config: AppConfig, clock=None) -> None:
        self.repo = repo
        self.config = config
        self._clock = clock or time.time

    # ------------------------------------------------------------------
    # 商品
    # ------------------------------------------------------------------
    def _categories(self) -> dict:
        cats = self.repo.products.get("categories")
        return cats if isinstance(cats, dict) else {}

    def categories(self) -> list[str]:
        return sorted(self._categories().keys())

    def subcategories(self, category: str) -> list[str]:
        cats = self._categories()
        if category not in cats:
            raise ServiceError(f"未找到大分类「{category}」，使用 menu 查看全部大分类")
        subs = cats[category]
        if not isinstance(subs, dict):
            return []
        return sorted(subs.keys())

    def products(self, category: str | None = None, subcategory: str | None = None) -> list[Product]:
        cats = self._categories()
        out: list[Product] = []
        for cat_name, subs in cats.items():
            if category is not None and cat_name != category:
                continue
            if not isinstance(subs, dict):
                continue
            for sub_name, items in subs.items():
                if subcategory is not None and sub_name != subcategory:
                    continue
                if not isinstance(items, list):
                    continue
                for item in items:
                    try:
                        out.append(Product.from_dict(item))
                    except Exception:  # noqa: BLE001 - 跳过损坏数据
                        continue
        return out

    def find_product(self, keyword: str) -> Product | None:
        """按 ID 精确、名称精确、名称包含的顺序查找商品。"""
        text = str(keyword or "").strip()
        if not text:
            raise ServiceError("请提供商品名称")
        products = self.products()
        for product in products:
            if product.id == text:
                return product
        for product in products:
            if product.name == text:
                return product
        lowered = text.lower()
        for product in products:
            if lowered in product.name.lower():
                return product
        return None

    def add_product(
        self,
        category: str,
        subcategory: str,
        name: str,
        price,
        weight_kg=None,
    ) -> Product:
        cat = _clean_text(category, MAX_CATEGORY_LEN, "大分类")
        sub = _clean_text(subcategory, MAX_CATEGORY_LEN, "小分类")
        prod_name = _clean_text(name, MAX_NAME_LEN, "商品名称")
        prod_price = _parse_price(price)
        weight = _parse_weight(weight_kg, self.config.default_weight_kg)

        cats = self._categories()
        if cat not in cats or not isinstance(cats[cat], dict):
            cats[cat] = {}
        subs = cats[cat]
        if sub not in subs or not isinstance(subs[sub], list):
            subs[sub] = []

        for item in subs[sub]:
            if str(item.get("name", "")).strip() == prod_name:
                raise ServiceError(f"「{cat}/{sub}」下已存在同名商品「{prod_name}」")

        product = Product(
            id=new_id("p"),
            name=prod_name,
            price=prod_price,
            weight_kg=weight,
            category=cat,
            subcategory=sub,
            created_at=_now_str(),
        )
        subs[sub].append(product.to_dict())
        self.repo.save_products()
        return product

    # ------------------------------------------------------------------
    # 购物车
    # ------------------------------------------------------------------
    def _cart_raw(self, user_id: str) -> dict:
        cart = self.repo.carts.get(user_id)
        if not isinstance(cart, dict):
            cart = {"items": {}, "updated_at": ""}
            self.repo.carts[user_id] = cart
        if not isinstance(cart.get("items"), dict):
            cart["items"] = {}
        return cart

    def cart(self, user_id: str) -> list[CartItem]:
        cart = self._cart_raw(user_id)
        items: list[CartItem] = []
        for pid, qty in list(cart["items"].items()):
            product = self._find_product_by_id(str(pid))
            if product is None:
                cart["items"].pop(pid, None)
                continue
            try:
                count = int(qty)
            except (TypeError, ValueError):
                cart["items"].pop(pid, None)
                continue
            if count <= 0:
                cart["items"].pop(pid, None)
                continue
            items.append(CartItem(product=product, qty=min(count, MAX_QTY)))
        return items

    def _find_product_by_id(self, product_id: str) -> Product | None:
        for product in self.products():
            if product.id == product_id:
                return product
        return None

    def cart_add(self, user_id: str, product: Product, qty: int) -> list[CartItem]:
        count = _parse_qty(qty)
        cart = self._cart_raw(user_id)
        current = cart["items"].get(product.id, 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        new_qty = min(current + count, MAX_QTY)
        cart["items"][product.id] = new_qty
        cart["updated_at"] = _now_str()
        self.repo.save_carts()
        return self.cart(user_id)

    def cart_remove_at(self, user_id: str, index: int) -> list[CartItem]:
        items = self.cart(user_id)
        if not items:
            raise ServiceError("购物车是空的")
        if index < 1 or index > len(items):
            raise ServiceError(f"序号无效，请输入 1 ~ {len(items)} 之间的数字")
        target = items[index - 1]
        cart = self._cart_raw(user_id)
        cart["items"].pop(target.product.id, None)
        cart["updated_at"] = _now_str()
        self.repo.save_carts()
        return self.cart(user_id)

    def cart_clear(self, user_id: str) -> None:
        self.repo.carts[user_id] = {"items": {}, "updated_at": _now_str()}
        self.repo.save_carts()

    def cart_total_qty(self, user_id: str) -> int:
        return sum(item.qty for item in self.cart(user_id))

    # ------------------------------------------------------------------
    # 运费 / 订单
    # ------------------------------------------------------------------
    def resolve_channel(self, requested: str | None = None) -> str:
        enabled = self.config.enabled_channels()
        if requested:
            key = str(requested).strip().lower()
            alias = {
                "极速达": CHANNEL_EXPRESS,
                "全国配": CHANNEL_NATIONAL,
                "express": CHANNEL_EXPRESS,
                "national": CHANNEL_NATIONAL,
            }.get(key)
            if alias is None:
                raise ServiceError("配送方式只能是「极速达」或「全国配」")
            if alias not in enabled:
                raise ServiceError(f"配送方式「{self.config.channel_label(alias)}」未启用")
            return alias
        default = self.config.default_channel if self.config.default_channel in enabled else enabled[0]
        return default

    def freight_rules(self) -> dict:
        return {
            CHANNEL_EXPRESS: freight.build_rule(CHANNEL_EXPRESS, self.config.express),
            CHANNEL_NATIONAL: freight.build_rule(CHANNEL_NATIONAL, self.config.national),
        }

    def calc_cart_freight(self, user_id: str, channel: str | None = None) -> freight.FreightResult:
        items = self.cart(user_id)
        if not items:
            raise ServiceError("购物车是空的")
        goods = sum((item.subtotal for item in items), Decimal("0.00"))
        weight = sum((item.weight for item in items), Decimal("0.00"))
        resolved = self.resolve_channel(channel)
        rule = self.freight_rules()[resolved]
        return freight.calc_freight(
            goods,
            weight,
            rule,
            amount_base=self.config.freight_amount_base or AMOUNT_BASE_GOODS,
        )

    def _compose_order(
        self,
        user_id: str,
        user_name: str,
        channel: str | None = None,
        umo: str = "",
    ) -> Order:
        items = self.cart(user_id)
        if not items:
            raise ServiceError("购物车是空的，无法下单")
        resolved = self.resolve_channel(channel)
        result = self.calc_cart_freight(user_id, resolved)
        return Order(
            order_id=self._new_order_id(),
            user_id=user_id,
            user_name=user_name or user_id,
            items=[
                OrderItem(
                    product_id=item.product.id,
                    name=item.product.name,
                    price=item.product.price,
                    weight_kg=item.product.weight_kg,
                    qty=item.qty,
                )
                for item in items
            ],
            channel=resolved,
            goods_amount=result.goods_amount,
            weight=result.weight,
            freight=result.freight,
            total=result.total,
            status=ORDER_PENDING,
            created_at=_now_str(),
            created_ts=self._clock(),
            umo=umo,
        )

    def preview_order(
        self,
        user_id: str,
        user_name: str,
        channel: str | None = None,
    ) -> Order:
        """生成一份未持久化的订单预览（用于下单前展示费用明细）。"""
        return self._compose_order(user_id, user_name, channel)

    def build_order(
        self,
        user_id: str,
        user_name: str,
        channel: str | None = None,
        umo: str = "",
    ) -> Order:
        order = self._compose_order(user_id, user_name, channel, umo)
        self.repo.orders[order.order_id] = order.to_dict()
        self.repo.save_orders()
        # 下单后清空购物车，避免重复下单
        self.cart_clear(user_id)
        return order

    def _new_order_id(self) -> str:
        prefix = self.config.order.id_prefix or "SAM"
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}{stamp}{random.randint(0, 9999):04d}"

    def get_order(self, order_id: str) -> Order | None:
        data = self.repo.orders.get(order_id)
        if not isinstance(data, dict):
            return None
        try:
            return Order.from_dict(data)
        except Exception:  # noqa: BLE001
            return None

    def orders_of_user(self, user_id: str) -> list[Order]:
        out = []
        for data in self.repo.orders.values():
            if not isinstance(data, dict):
                continue
            if str(data.get("user_id")) != str(user_id):
                continue
            order = self.get_order(str(data.get("order_id")))
            if order is not None:
                out.append(order)
        out.sort(key=lambda o: o.created_ts, reverse=True)
        return out

    def pending_orders(self) -> list[Order]:
        out = []
        for data in self.repo.orders.values():
            if not isinstance(data, dict):
                continue
            if str(data.get("status")) != ORDER_PENDING:
                continue
            order = self.get_order(str(data.get("order_id")))
            if order is not None:
                out.append(order)
        out.sort(key=lambda o: o.created_ts)
        return out

    def mark_paid(self, order_id: str, trade_no: str = "", paid_at: str | None = None) -> Order | None:
        order = self.get_order(order_id)
        if order is None:
            return None
        order.status = ORDER_PAID
        order.trade_no = trade_no or order.trade_no
        order.paid_at = paid_at or _now_str()
        self.repo.orders[order_id] = order.to_dict()
        self.repo.save_orders()
        return order

    def mark_email_sent(self, order_id: str, error: str = "") -> None:
        order = self.get_order(order_id)
        if order is None:
            return
        order.email_attempts += 1
        if error:
            order.email_error = error
        else:
            order.email_sent = True
            order.email_error = ""
        self.repo.orders[order_id] = order.to_dict()
        self.repo.save_orders()

    def mark_query_failure(self, order_id: str, delta: int = 1) -> None:
        order = self.get_order(order_id)
        if order is None:
            return
        order.consecutive_failures = max(0, order.consecutive_failures + delta)
        self.repo.orders[order_id] = order.to_dict()
        self.repo.save_orders()

    def mark_query_success(self, order_id: str) -> None:
        order = self.get_order(order_id)
        if order is None:
            return
        if order.consecutive_failures:
            order.consecutive_failures = 0
            self.repo.orders[order_id] = order.to_dict()
            self.repo.save_orders()

    def close_order(self, order_id: str, status: str, reason: str = "") -> Order | None:
        order = self.get_order(order_id)
        if order is None:
            return None
        if order.status != ORDER_PENDING:
            return order
        order.status = status
        order.remark = reason
        self.repo.orders[order_id] = order.to_dict()
        self.repo.save_orders()
        return order

    def cancel_order(self, order_id: str, reason: str = "用户取消") -> Order | None:
        return self.close_order(order_id, ORDER_CANCELLED, reason)

    def expire_order(self, order_id: str) -> Order | None:
        return self.close_order(order_id, ORDER_EXPIRED, "支付超时")

    def order_age(self, order: Order) -> float:
        return max(0.0, self._clock() - order.created_ts)


def is_channel_enabled(config: AppConfig, channel: str) -> bool:
    return channel in CHANNELS and channel in config.enabled_channels()
