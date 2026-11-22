"""插件配置：默认值、解析与校验。

配置来源是 AstrBot 根据 ``_conf_schema.json`` 生成的
``data/config/<插件目录名>_config.json``，以 ``AstrBotConfig``（dict 子类）
形式传入插件 ``__init__``。这里把它转换成强类型的 ``AppConfig``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CHANNEL_EXPRESS = "express"
CHANNEL_NATIONAL = "national"
CHANNELS = (CHANNEL_EXPRESS, CHANNEL_NATIONAL)

CHANNEL_LABELS = {
    CHANNEL_EXPRESS: "极速达",
    CHANNEL_NATIONAL: "全国配",
}

AMOUNT_BASE_GOODS = "goods"
AMOUNT_BASE_TOTAL = "total"


class ConfigError(Exception):
    """配置不合法。"""


def _section(raw: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    if not raw:
        return {}
    value = raw.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _str_list(value: Any) -> tuple[str, ...]:
    """把 list / 逗号或空白分隔的字符串统一成字符串元组。"""
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.replace(",", " ").replace("，", " ").split()
        return tuple(p.strip() for p in parts if p.strip())
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return tuple(out)
    return (str(value).strip(),) if str(value).strip() else ()


def _int_list(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return tuple(out)
    return ()


@dataclass(frozen=True)
class FreightRuleConfig:
    """单条配送渠道的运费规则参数。"""

    free_amount: float = 99.0
    """满额免基础运费门槛（元）。"""
    base_fee: float = 10.0
    """未达门槛且未超重时的固定运费（元）。"""
    free_weight: float = 15.0
    """免费重量（kg）。"""
    overweight_rate: float = 1.0
    """续重费率（元/kg）。"""
    per_100_discount: float = 10.0
    """每满 100 元减免金额（元）。"""
    per_100_free_weight: float = 0.0
    """每满 100 元额外增加的免重（kg）。"""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, defaults: "FreightRuleConfig | None" = None) -> "FreightRuleConfig":
        data = data or {}
        d = defaults or cls()
        return cls(
            free_amount=_float(data.get("free_amount"), d.free_amount),
            base_fee=_float(data.get("base_fee"), d.base_fee),
            free_weight=_float(data.get("free_weight"), d.free_weight),
            overweight_rate=_float(data.get("overweight_rate"), d.overweight_rate),
            per_100_discount=_float(data.get("per_100_discount"), d.per_100_discount),
            per_100_free_weight=_float(data.get("per_100_free_weight"), d.per_100_free_weight),
        )


@dataclass(frozen=True)
class PaymentConfig:
    gateway: str = ""
    pid: str = ""
    key: str = ""
    pay_type: str = "wxpay"
    sign_type: str = "MD5"
    create_path: str = "/mapi.php"
    query_path: str = "/api.php"
    query_act: str = "order"
    query_auth: str = "key"
    notify_url: str = ""
    return_url: str = ""
    sign_urlencode: bool = False
    paid_status_values: tuple[int, ...] = (2,)
    paid_trade_status: tuple[str, ...] = ("TRADE_SUCCESS", "PAID", "SUCCESS")
    create_timeout: float = 15.0
    query_timeout: float = 10.0

    @property
    def configured(self) -> bool:
        return bool(self.gateway and self.pid and self.key)

    @property
    def gateway_normalized(self) -> str:
        return self.gateway.rstrip("/")

    def create_url(self) -> str:
        path = self.create_path or "/mapi.php"
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.gateway_normalized}{path}"

    def query_url(self) -> str:
        path = self.query_path or "/api.php"
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.gateway_normalized}{path}"


@dataclass(frozen=True)
class SmtpConfig:
    server: str = ""
    port: int = 465
    username: str = ""
    password: str = ""
    sender: str = ""
    use_tls: bool = True
    admin_email: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.server and self.username and self.password and self.admin_email)


@dataclass(frozen=True)
class PollConfig:
    interval: float = 5.0
    timeout: float = 600.0
    max_consecutive_failures: int = 20


@dataclass(frozen=True)
class StorageConfig:
    products_path: str = ""
    orders_path: str = ""
    carts_path: str = ""


@dataclass(frozen=True)
class OrderConfig:
    id_prefix: str = "SAM"
    expire_minutes: int = 30
    max_email_attempts: int = 3


@dataclass(frozen=True)
class AppConfig:
    wake_word: str = "sam's"
    wake_aliases: tuple[str, ...] = ()
    admins: tuple[str, ...] = ()
    fallback_platform_admin: bool = False
    default_channel: str = CHANNEL_EXPRESS
    enable_express: bool = True
    enable_national: bool = True
    shop_name: str = "山姆代购"
    freight_amount_base: str = AMOUNT_BASE_GOODS
    default_weight_kg: float = 1.0
    express: FreightRuleConfig = FreightRuleConfig()
    national: FreightRuleConfig = FreightRuleConfig(
        free_amount=299.0,
        base_fee=15.0,
        free_weight=15.0,
        overweight_rate=1.0,
        per_100_discount=10.0,
        per_100_free_weight=5.0,
    )
    payment: PaymentConfig = PaymentConfig()
    smtp: SmtpConfig = SmtpConfig()
    poll: PollConfig = PollConfig()
    storage: StorageConfig = StorageConfig()
    order: OrderConfig = OrderConfig()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "AppConfig":
        raw = raw or {}
        general = _section(raw, "general")
        freight = _section(raw, "freight")
        payment = _section(raw, "payment")
        smtp = _section(raw, "smtp")
        poll = _section(raw, "poll")
        storage = _section(raw, "storage")
        order = _section(raw, "order")

        wake_word = _str(general.get("wake_word"), "sam's")
        default_channel = _str(general.get("default_channel"), CHANNEL_EXPRESS).lower()
        amount_base = _str(freight.get("amount_base"), AMOUNT_BASE_GOODS).lower()
        enable_express = _bool(general.get("enable_express"), True)
        enable_national = _bool(general.get("enable_national"), True)

        cfg = cls(
            wake_word=wake_word,
            wake_aliases=_str_list(general.get("wake_aliases")),
            admins=_str_list(general.get("admins")),
            fallback_platform_admin=_bool(general.get("fallback_platform_admin"), False),
            default_channel=default_channel,
            enable_express=enable_express,
            enable_national=enable_national,
            shop_name=_str(general.get("shop_name"), "山姆代购"),
            freight_amount_base=amount_base,
            default_weight_kg=_float(freight.get("default_weight_kg"), 1.0),
            express=FreightRuleConfig.from_dict(_section(freight, "express"), FreightRuleConfig()),
            national=FreightRuleConfig.from_dict(
                _section(freight, "national"),
                FreightRuleConfig(
                    free_amount=299.0,
                    base_fee=15.0,
                    free_weight=15.0,
                    overweight_rate=1.0,
                    per_100_discount=10.0,
                    per_100_free_weight=5.0,
                ),
            ),
            payment=PaymentConfig(
                gateway=_str(payment.get("gateway"), ""),
                pid=_str(payment.get("pid"), ""),
                key=_str(payment.get("key"), ""),
                pay_type=_str(payment.get("pay_type"), "wxpay"),
                sign_type=_str(payment.get("sign_type"), "MD5").upper(),
                create_path=_str(payment.get("create_path"), "/mapi.php"),
                query_path=_str(payment.get("query_path"), "/api.php"),
                query_act=_str(payment.get("query_act"), "order"),
                query_auth=_str(payment.get("query_auth"), "key").lower(),
                notify_url=_str(payment.get("notify_url"), ""),
                return_url=_str(payment.get("return_url"), ""),
                sign_urlencode=_bool(payment.get("sign_urlencode"), False),
                paid_status_values=_int_list(payment.get("paid_status_values")) or (2,),
                paid_trade_status=tuple(
                    s.upper()
                    for s in _str_list(payment.get("paid_trade_status"))
                )
                or ("TRADE_SUCCESS", "PAID", "SUCCESS"),
                create_timeout=_float(payment.get("create_timeout"), 15.0),
                query_timeout=_float(payment.get("query_timeout"), 10.0),
            ),
            smtp=SmtpConfig(
                server=_str(smtp.get("server"), ""),
                port=_int(smtp.get("port"), 465),
                username=_str(smtp.get("username"), ""),
                password=_str(smtp.get("password"), ""),
                sender=_str(smtp.get("sender"), ""),
                use_tls=_bool(smtp.get("use_tls"), True),
                admin_email=_str(smtp.get("admin_email"), ""),
            ),
            poll=PollConfig(
                interval=_float(poll.get("interval"), 5.0),
                timeout=_float(poll.get("timeout"), 600.0),
                max_consecutive_failures=_int(poll.get("max_consecutive_failures"), 20),
            ),
            storage=StorageConfig(
                products_path=_str(storage.get("products_path"), ""),
                orders_path=_str(storage.get("orders_path"), ""),
                carts_path=_str(storage.get("carts_path"), ""),
            ),
            order=OrderConfig(
                id_prefix=_str(order.get("id_prefix"), "SAM"),
                expire_minutes=_int(order.get("expire_minutes"), 30),
                max_email_attempts=_int(order.get("max_email_attempts"), 3),
            ),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.wake_word:
            raise ConfigError("唤醒词 wake_word 不能为空")
        if self.default_channel not in CHANNELS:
            raise ConfigError(
                f"默认配送方式 default_channel 只能是 express 或 national，当前为 {self.default_channel!r}"
            )
        if self.freight_amount_base not in (AMOUNT_BASE_GOODS, AMOUNT_BASE_TOTAL):
            raise ConfigError(
                f"满减计算基数 amount_base 只能是 goods 或 total，当前为 {self.freight_amount_base!r}"
            )
        if not self.enable_express and not self.enable_national:
            raise ConfigError("极速达与全国配至少要启用一种配送方式")
        if self.default_channel == CHANNEL_EXPRESS and not self.enable_express:
            raise ConfigError("默认配送方式为极速达，但极速达未启用")
        if self.default_channel == CHANNEL_NATIONAL and not self.enable_national:
            raise ConfigError("默认配送方式为全国配，但全国配未启用")
        if self.poll.interval <= 0:
            raise ConfigError("轮询间隔 interval 必须大于 0")
        if self.default_weight_kg < 0:
            raise ConfigError("默认重量 default_weight_kg 不能为负数")

    def rule_for(self, channel: str) -> FreightRuleConfig:
        if channel == CHANNEL_NATIONAL:
            return self.national
        return self.express

    def channel_label(self, channel: str) -> str:
        return CHANNEL_LABELS.get(channel, channel)

    def enabled_channels(self) -> tuple[str, ...]:
        out = []
        if self.enable_express:
            out.append(CHANNEL_EXPRESS)
        if self.enable_national:
            out.append(CHANNEL_NATIONAL)
        return tuple(out)

    def is_admin(self, sender_id: str, platform_admin: bool = False) -> bool:
        if sender_id and sender_id in self.admins:
            return True
        if self.fallback_platform_admin and platform_admin:
            return True
        return False
