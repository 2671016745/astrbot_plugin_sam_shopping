"""聊天消息与邮件文案的格式化。"""
from __future__ import annotations

from decimal import Decimal

from .config import CHANNEL_LABELS, AppConfig
from .models import ORDER_PENDING, CartItem, Order, OrderItem, Product


def _money(value) -> str:
    try:
        return f"{Decimal(str(value)):.2f}"
    except Exception:  # noqa: BLE001
        return str(value)


def format_help(config: AppConfig, has_products: bool, is_admin: bool = False) -> str:
    """帮助文案。``add`` 只对管理员展示。"""
    wake = config.wake_word
    commands = [
        (f"{wake} menu [大分类] [小分类]", "浏览商品分类与商品"),
        (f"{wake} buy <商品名称> [数量]", "加入购物车（数量省略时为 1）"),
        (f"{wake} basket", "查看购物车"),
        (f"{wake} basket delete [序号]", "删除购物车中的商品"),
        (f"{wake} basket clear", "清空购物车（需二次确认）"),
        (f"{wake} pay [极速达|全国配]", "查看费用明细，随后回复「确认支付」下单"),
    ]
    if is_admin:
        commands.append(
            (
                f"{wake} add <大分类> <小分类> <商品名称> <价格> "
                "[重量kg] [代购费元/件]",
                "管理员添加商品",
            )
        )

    lines = [f"【{config.shop_name}】指令帮助", ""]
    lines.extend(f"· {cmd} —— {desc}" for cmd, desc in commands)
    lines.append("")

    lines.append("运费规则（满减按%s计算，结果保留两位小数）：" % _amount_base_text(config))
    channels = config.enabled_channels()
    if not channels:
        lines.append("· 未启用任何配送方式，请联系管理员")
    for channel in channels:
        rule = config.rule_for(channel)
        label = CHANNEL_LABELS.get(channel, channel)
        parts = [
            f"满 {_money(rule.free_amount)} 元免 {_money(rule.free_weight)}kg 以内运费，"
            f"未满收 {_money(rule.base_fee)} 元",
            f"超出免费重量部分加 {_money(rule.overweight_rate)} 元/kg",
        ]
        if rule.per_100_discount > 0:
            parts.append(f"每满 100 元减 {_money(rule.per_100_discount)} 元")
        if rule.per_100_free_weight > 0:
            parts.append(f"每满 100 元增加 {_money(rule.per_100_free_weight)}kg 免重")
        parts.append("最低 0 元")
        lines.append(f"· {label}：{'；'.join(parts)}。")

    lines.append("")
    fee = config.proxy_fee
    label = config.fee_label or "代购费"
    if fee.fee_mode == "none":
        lines.append(f"代购费：当前不收取。")
    else:
        mode_names = {"per_order": "按次", "per_weight": "按重量", "per_item": "按件数"}
        if fee.fee_mode == "per_order":
            detail = f"每单固定 {_money(fee.fee_per_order)} 元"
        elif fee.fee_mode == "per_weight":
            detail = f"{_money(fee.fee_per_weight)} 元/kg × 总重量"
        else:
            detail = f"{_money(fee.fee_per_item)} 元/件 × 总件数"
        extra = []
        if fee.fee_min > 0:
            extra.append(f"最低 {_money(fee.fee_min)} 元")
        if fee.fee_max > 0:
            extra.append(f"最高 {_money(fee.fee_max)} 元")
        suffix = f"（{'，'.join(extra)}）" if extra else ""
        lines.append(
            f"{label}：{mode_names.get(fee.fee_mode, fee.fee_mode)}，{detail}{suffix}；"
            "单个商品可单独设置元/件，优先于全局规则。"
        )

    if not has_products:
        lines.append("")
        lines.append(
            "当前还没有商品，可用 add 添加。"
            if is_admin
            else "当前还没有商品，请联系管理员添加。"
        )
    return "\n".join(lines)


def _amount_base_text(config: AppConfig) -> str:
    return "商品总金额" if config.freight_amount_base == "goods" else "含运费金额"


def format_menu_categories(categories: list[str]) -> str:
    if not categories:
        return "还没有商品分类。管理员可使用 add 指令添加商品。"
    lines = ["商品大分类：", ""]
    for index, name in enumerate(categories, start=1):
        lines.append(f"{index}. {name}")
    lines.append("")
    lines.append("发送「menu <大分类>」查看小分类，或「menu <大分类> <小分类>」查看商品。")
    return "\n".join(lines)


def format_menu_subcategories(category: str, subcategories: list[str]) -> str:
    if not subcategories:
        return f"大分类「{category}」下暂时没有小分类。"
    lines = [f"「{category}」下的小分类：", ""]
    for index, name in enumerate(subcategories, start=1):
        lines.append(f"{index}. {name}")
    lines.append("")
    lines.append(f"发送「menu {category} <小分类>」查看商品。")
    return "\n".join(lines)


def format_menu_products(category: str, subcategory: str, products: list[Product]) -> str:
    if not products:
        return f"「{category}/{subcategory}」下暂时没有商品。"
    lines = [f"「{category}/{subcategory}」商品：", ""]
    for index, product in enumerate(products, start=1):
        extra = f"（{_money(product.weight_kg)} kg）"
        if product.fee > 0:
            extra += f"，单件代购费 {_money(product.fee)} 元/件"
        lines.append(f"{index}. {product.name} —— {_money(product.price)} 元{extra}")
    lines.append("")
    lines.append("发送「buy <商品名称> <数量>」加入购物车。")
    return "\n".join(lines)


def format_cart(items: list[CartItem]) -> str:
    if not items:
        return "购物车是空的。发送「menu」浏览商品。"
    lines = ["购物车：", ""]
    total = Decimal("0.00")
    for index, item in enumerate(items, start=1):
        subtotal = item.subtotal
        total += subtotal
        lines.append(
            f"{index}. {item.product.name} × {item.qty} —— {_money(subtotal)} 元"
        )
    lines.append("")
    lines.append(f"合计：{_money(total)} 元（未含运费与代购费）")
    return "\n".join(lines)


def format_cart_numbered(items: list[CartItem]) -> str:
    lines = ["请选择要删除的商品序号：", ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.product.name} × {item.qty}")
    lines.append("")
    lines.append("回复序号即可删除，例如「2」；或发送「basket delete 2」。")
    return "\n".join(lines)


def format_fee_lines(freight, proxy) -> list[str]:
    """把运费明细与代购费明细拼成一段，末行为应付总额。

    ``freight`` 为 ``FreightResult``，``proxy`` 为 ``ProxyFeeResult``。
    """
    lines = list(freight.detail_lines()[:-1])
    lines.extend(proxy.detail_lines())
    lines.append(f"应付总额：{_money(freight.total + proxy.amount)} 元")
    return lines


def format_proxy_fee_detail(order: Order) -> list[str]:
    """订单/邮件里回显代购费的计算明细。"""
    return [str(line) for line in order.proxy_fee_detail]


def format_order_preview(order: Order, freight_lines: list[str]) -> str:
    lines = [f"订单预览（{order.status_label}）", ""]
    for item in order.items:
        lines.append(
            f"· {item.name} × {item.qty} —— {_money(item.price)} 元/件，"
            f"小计 {_money(item.subtotal)} 元"
        )
    lines.append("")
    lines.extend(freight_lines)
    lines.append("")
    lines.append("请核对以上信息。确认无误请回复「确认支付」，取消请回复「取消」。")
    return "\n".join(lines)


def format_order_created(order: Order, expire_minutes: int = 30) -> str:
    return (
        f"订单 {order.order_id} 已创建，应付总额 {_money(order.total)} 元。\n"
        f"请扫描上方二维码完成支付，支付成功后我会自动通知你。\n"
        f"订单 {expire_minutes} 分钟内未支付将自动关闭。"
    )


def format_order_paid(order: Order) -> str:
    lines = [
        f"订单 {order.order_id} 已支付成功，实付 {_money(order.total)} 元。",
        f"配送方式：{CHANNEL_LABELS.get(order.channel, order.channel)}，"
        f"我们会尽快为你处理，感谢购买！",
        "",
        "费用明细：",
        f"· 商品金额 {_money(order.goods_amount)} 元",
        f"· 运费 {_money(order.freight)} 元",
    ]
    if order.proxy_fee > 0:
        lines.append(f"· 代购费 {_money(order.proxy_fee)} 元")
        lines.extend(f"  {line}" for line in format_proxy_fee_detail(order))
    lines.append(f"· 应付总额 {_money(order.total)} 元")
    return "\n".join(lines)


def format_order(order: Order) -> str:
    lines = [
        f"订单 {order.order_id}（{order.status_label}）",
        f"下单时间：{order.created_at or '-'}",
        f"配送方式：{CHANNEL_LABELS.get(order.channel, order.channel)}",
        "",
    ]
    for item in order.items:
        lines.append(
            f"· {item.name} × {item.qty} —— {_money(item.subtotal)} 元"
        )
    lines.append("")
    lines.append(f"商品金额：{_money(order.goods_amount)} 元")
    lines.append(f"商品重量：{_money(order.weight)} kg")
    lines.append(f"运费：{_money(order.freight)} 元")
    if order.proxy_fee > 0:
        lines.append(f"代购费：{_money(order.proxy_fee)} 元")
        lines.extend(f"  {line}" for line in format_proxy_fee_detail(order))
    lines.append(f"应付总额：{_money(order.total)} 元")
    if order.paid_at:
        lines.append(f"支付时间：{order.paid_at}")
    return "\n".join(lines)


def format_email_subject(order: Order, shop_name: str) -> str:
    return f"【{shop_name}】有新的代购消息 - 订单 {order.order_id}"


def format_email_body(order: Order, shop_name: str) -> str:
    lines = [
        f"【{shop_name}】有新的代购消息",
        "",
        f"订单号：{order.order_id}",
        f"用户 ID：{order.user_id}",
        f"用户昵称：{order.user_name}",
        f"下单时间：{order.created_at or '-'}",
        f"支付时间：{order.paid_at or '-'}",
        f"交易号：{order.trade_no or '-'}",
        "",
        "商品明细：",
    ]
    for item in order.items:
        lines.append(
            f"  - {item.name} × {item.qty}，单价 {_money(item.price)} 元，"
            f"小计 {_money(item.subtotal)} 元"
        )
    lines.append("")
    lines.append(f"商品金额：{_money(order.goods_amount)} 元")
    lines.append(f"配送方式：{CHANNEL_LABELS.get(order.channel, order.channel)}")
    lines.append(f"商品重量：{_money(order.weight)} kg")
    lines.append(f"运费：{_money(order.freight)} 元")
    if order.proxy_fee > 0:
        lines.append(f"代购费：{_money(order.proxy_fee)} 元")
        lines.extend(f"  {line}" for line in format_proxy_fee_detail(order))
    lines.append(f"应付总额：{_money(order.total)} 元")
    if order.remark:
        lines.append(f"备注：{order.remark}")
    return "\n".join(lines)


def format_payment_pending(order: Order) -> str:
    if order.status == ORDER_PENDING:
        return "该订单仍在等待支付。"
    return f"该订单状态：{order.status_label}。"


def order_items_text(items: list[OrderItem]) -> str:
    return "、".join(f"{item.name}×{item.qty}" for item in items)
