"""运费计算（纯函数，便于单元测试）。

计算顺序（对两种配送方式一致）：

1. ``n100 = floor(计费金额 / 100)``；
2. 基础运费：``计费金额 >= 免邮门槛`` 时为 0，否则为固定运费 ``base_fee``；
3. 有效免重 ``= free_weight + n100 * per_100_free_weight``；
4. 续重费 ``= max(0, 重量 - 有效免重) * overweight_rate``；
5. 满减 ``= n100 * per_100_discount``；
6. 运费 ``= max(0, 基础运费 + 续重费 - 满减)``，四舍五入保留两位小数。

其中「计费金额」默认取商品总金额（``amount_base = goods``），
也可配置为含运费金额（``amount_base = total``，用不动点迭代求解）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

from .config import AMOUNT_BASE_GOODS, CHANNEL_EXPRESS, CHANNEL_LABELS, FreightRuleConfig

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class FreightError(Exception):
    """运费计算参数不合法。"""


def to_decimal(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FreightError(f"{name} 不是有效数值: {value!r}") from exc
    if not result.is_finite():
        raise FreightError(f"{name} 必须是有限数值: {value!r}")
    return result


def money(value: Decimal) -> Decimal:
    """按分四舍五入。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FreightRule:
    """不可变的运费规则（内部使用 Decimal 保证精度）。"""

    channel: str
    label: str
    free_amount: Decimal
    base_fee: Decimal
    free_weight: Decimal
    overweight_rate: Decimal
    per_100_discount: Decimal
    per_100_free_weight: Decimal


def build_rule(channel: str, cfg: FreightRuleConfig) -> FreightRule:
    label = CHANNEL_LABELS.get(channel, channel)
    return FreightRule(
        channel=channel,
        label=label,
        free_amount=to_decimal(cfg.free_amount, "free_amount"),
        base_fee=to_decimal(cfg.base_fee, "base_fee"),
        free_weight=to_decimal(cfg.free_weight, "free_weight"),
        overweight_rate=to_decimal(cfg.overweight_rate, "overweight_rate"),
        per_100_discount=to_decimal(cfg.per_100_discount, "per_100_discount"),
        per_100_free_weight=to_decimal(cfg.per_100_free_weight, "per_100_free_weight"),
    )


@dataclass(frozen=True)
class FreightResult:
    channel: str
    label: str
    goods_amount: Decimal
    """商品总金额。"""
    billing_amount: Decimal
    """参与满减计算的金额（goods 或 goods+freight）。"""
    amount_base: str
    weight: Decimal
    base_fee: Decimal
    free_weight: Decimal
    overweight_fee: Decimal
    discount: Decimal
    freight: Decimal
    notes: tuple[str, ...]

    @property
    def total(self) -> Decimal:
        return money(self.goods_amount + self.freight)

    def detail_lines(self) -> list[str]:
        lines = [
            f"配送方式：{self.label}",
            f"商品金额：{self.goods_amount} 元",
            f"商品重量：{self.weight} kg",
        ]
        lines.extend(f"· {note}" for note in self.notes)
        lines.append(f"运费：{self.freight} 元")
        lines.append(f"应付总额：{self.total} 元")
        return lines


def _compute(
    goods_amount: Decimal,
    weight: Decimal,
    rule: FreightRule,
    billing_amount: Decimal,
    amount_base: str,
) -> FreightResult:
    if goods_amount < 0:
        raise FreightError("商品金额不能为负数")
    if weight < 0:
        raise FreightError("重量不能为负数")
    if billing_amount < 0:
        raise FreightError("计费金额不能为负数")

    n100_decimal = (billing_amount / HUNDRED).to_integral_value(rounding=ROUND_FLOOR)
    n100 = int(n100_decimal)

    if billing_amount >= rule.free_amount:
        base_fee = Decimal("0.00")
        base_note = f"满 {money(rule.free_amount)} 元，免基础运费"
    else:
        base_fee = money(rule.base_fee)
        base_note = f"未满 {money(rule.free_amount)} 元，收取基础运费 {base_fee} 元"

    free_weight = rule.free_weight + rule.per_100_free_weight * n100
    excess = weight - free_weight
    overweight_fee = money((excess if excess > 0 else Decimal("0")) * rule.overweight_rate)
    if overweight_fee > 0:
        over_note = (
            f"超出免费重量 {money(excess)} kg，"
            f"续重费 {overweight_fee} 元（{money(rule.overweight_rate)} 元/kg）"
        )
    else:
        over_note = f"未超过免费重量 {money(free_weight)} kg"

    discount = money(rule.per_100_discount * n100)
    if discount > 0:
        discount_note = f"每满 100 元减 {money(rule.per_100_discount)} 元，共减 {discount} 元"
    else:
        discount_note = "未满 100 元，无满减"

    raw = base_fee + overweight_fee - discount
    freight = money(raw) if raw > 0 else Decimal("0.00")

    notes = [base_note, over_note, discount_note]
    if raw <= 0 and raw != 0:
        notes.append("运费已减免至 0 元（最低不低于 0 元）")

    return FreightResult(
        channel=rule.channel,
        label=rule.label,
        goods_amount=money(goods_amount),
        billing_amount=money(billing_amount),
        amount_base=amount_base,
        weight=weight,
        base_fee=base_fee,
        free_weight=free_weight,
        overweight_fee=overweight_fee,
        discount=discount,
        freight=freight,
        notes=tuple(notes),
    )


def calc_freight(
    goods_amount,
    weight,
    rule: FreightRule,
    amount_base: str = "goods",
) -> FreightResult:
    """计算运费。

    :param goods_amount: 商品总金额（元）。
    :param weight: 商品总重量（kg）。
    :param rule: 运费规则。
    :param amount_base: ``goods`` 用商品金额参与满减；``total`` 用「商品金额 + 运费」参与满减。
    """
    goods = money(to_decimal(goods_amount, "goods_amount"))
    w = to_decimal(weight, "weight")
    if amount_base not in ("goods", "total"):
        raise FreightError(f"amount_base 只能是 goods 或 total，当前为 {amount_base!r}")

    if amount_base == "total":
        # 「含运费金额」先用商品金额算出基础运费，再把它计入满减基数（单步，避免迭代振荡）
        base_result = _compute(goods, w, rule, goods, AMOUNT_BASE_GOODS)
        billing_amount = goods + base_result.freight
        return _compute(goods, w, rule, billing_amount, amount_base)

    return _compute(goods, w, rule, goods, amount_base)


def calc_freight_for_channel(
    channel: str,
    goods_amount,
    weight,
    cfg: FreightRuleConfig,
    amount_base: str = "goods",
) -> FreightResult:
    """按渠道与规则配置直接计算运费。"""
    return calc_freight(goods_amount, weight, build_rule(channel, cfg), amount_base)


# 便于外部快速引用的默认规则构建器
def default_rules(config) -> dict[str, FreightRule]:
    return {
        CHANNEL_EXPRESS: build_rule(CHANNEL_EXPRESS, config.express),
    }
