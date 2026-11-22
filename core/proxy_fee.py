"""代购费计算（纯函数，便于单元测试）。

规则：

- ``none``：不收代购费；
- ``per_order``：按次，整单固定 ``fee_per_order`` 元；
- ``per_weight``：按重量，总重量 × ``fee_per_weight`` 元/kg；
- ``per_item``：按件数，总件数 × ``fee_per_item`` 元/件。

单个商品可以在商品上设置 ``fee``（单件代购费，元/件）。设了之后该商品按
「数量 × 单件代购费」计算，优先于全局规则；未设置的商品仍按全局规则计算。

最后套用订单级 ``fee_min``（最低）与 ``fee_max``（封顶，0 表示不封顶）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .config import ProxyFeeConfig
from .freight import money, to_decimal

MODE_NONE = "none"
MODE_PER_ORDER = "per_order"
MODE_PER_WEIGHT = "per_weight"
MODE_PER_ITEM = "per_item"
MODES = (MODE_NONE, MODE_PER_ORDER, MODE_PER_WEIGHT, MODE_PER_ITEM)

MODE_LABELS = {
    MODE_NONE: "不收取",
    MODE_PER_ORDER: "按次",
    MODE_PER_WEIGHT: "按重量",
    MODE_PER_ITEM: "按件数",
}


class ProxyFeeError(Exception):
    """代购费计算参数不合法。"""


@dataclass
class ProxyFeeEntry:
    """一个商品行：名称、数量、重量、单件代购费（0 表示用全局规则）。"""

    name: str
    qty: int
    weight: Decimal
    product_fee: Decimal = Decimal("0")


@dataclass
class ProxyFeeLine:
    name: str
    detail: str
    amount: Decimal


@dataclass
class ProxyFeeResult:
    mode: str
    label: str
    lines: list[ProxyFeeLine] = field(default_factory=list)
    amount: Decimal = Decimal("0.00")
    minimum: Decimal = Decimal("0.00")
    maximum: Decimal = Decimal("0.00")
    floored: bool = False
    capped: bool = False
    notes: tuple[str, ...] = ()

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)

    def detail_lines(self) -> list[str]:
        out = [f"{self.label}（{self.mode_label}）："]
        if not self.lines:
            out.append(f"· 不收取（规则为“{MODE_LABELS[MODE_NONE]}”或费率为 0）")
        for line in self.lines:
            out.append(f"· {line.name}：{line.detail} = {line.amount} 元")
        if self.floored:
            out.append(f"· 已按最低{self.label} {self.minimum} 元收取")
        if self.capped:
            out.append(f"· 已按{self.label}封顶 {self.maximum} 元收取")
        out.append(f"{self.label}合计：{self.amount} 元")
        return out


def calc_proxy_fee(entries: list[ProxyFeeEntry], cfg: ProxyFeeConfig) -> ProxyFeeResult:
    mode = cfg.fee_mode
    if mode not in MODES:
        raise ProxyFeeError(f"代购费模式无效：{mode!r}")
    if mode == MODE_NONE:
        return ProxyFeeResult(
            mode=mode,
            label=cfg.fee_label or "代购费",
            amount=Decimal("0.00"),
        )

    label = cfg.fee_label or "代购费"
    lines: list[ProxyFeeLine] = []

    if mode == MODE_PER_ORDER:
        rate = money(to_decimal(cfg.fee_per_order, "fee_per_order"))
        amount = rate
        lines.append(
            ProxyFeeLine(
                name=f"整单（{MODE_LABELS[MODE_PER_ORDER]}）",
                detail=f"{rate} 元/单 × 1 单",
                amount=rate,
            )
        )
    else:
        per_item_rate = money(to_decimal(cfg.fee_per_item, "fee_per_item"))
        per_weight_rate = money(to_decimal(cfg.fee_per_weight, "fee_per_weight"))
        for entry in entries:
            product_fee = to_decimal(entry.product_fee, "product_fee")
            if product_fee > 0:
                fee = money(Decimal(entry.qty) * product_fee)
                detail = f"{product_fee} 元/件 × {entry.qty} 件（商品单独设置）"
                name = entry.name
            elif mode == MODE_PER_ITEM:
                fee = money(Decimal(entry.qty) * per_item_rate)
                detail = f"{per_item_rate} 元/件 × {entry.qty} 件"
                name = entry.name
            else:  # per_weight
                fee = money(to_decimal(entry.weight, "weight") * per_weight_rate)
                detail = f"{per_weight_rate} 元/kg × {entry.weight} kg"
                name = entry.name
            if fee > 0:
                lines.append(ProxyFeeLine(name=name, detail=detail, amount=fee))
        amount = money(sum((line.amount for line in lines), Decimal("0.00")))

    minimum = money(to_decimal(cfg.fee_min, "fee_min"))
    maximum = money(to_decimal(cfg.fee_max, "fee_max"))
    floored = minimum > 0 and amount < minimum
    capped = maximum > 0 and amount > maximum
    if floored:
        amount = minimum
    if capped:
        amount = maximum

    notes: list[str] = []
    if mode == MODE_PER_ORDER:
        notes.append(f"按次收取，与商品数量、重量无关")
    if any(to_decimal(e.product_fee, "product_fee") > 0 for e in entries):
        notes.append("带“商品单独设置”的商品按单件代购费计算，其余按全局规则")

    return ProxyFeeResult(
        mode=mode,
        label=label,
        lines=lines,
        amount=money(amount),
        minimum=minimum,
        maximum=maximum,
        floored=floored,
        capped=capped,
        notes=tuple(notes),
    )
