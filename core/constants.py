"""插件级常量。

单独放一个模块是为了避免 ``main`` 与 ``core.messages`` 互相 import：
两个模块都需要官方指令组的名字（主指令 + 别名）。
"""
from __future__ import annotations

# 官方指令组：主指令「山姆」，别名 sam's / sam，三者等价。
COMMAND_GROUP_NAME = "山姆"
COMMAND_GROUP_ALIASES = ("sam's", "sam")
COMMAND_GROUP_NAMES = (COMMAND_GROUP_NAME,) + COMMAND_GROUP_ALIASES

# 子指令名（不含唤醒词/指令组前缀）
COMMAND_SUB_NAMES = ("help", "menu", "buy", "basket", "pay", "add")

# add 指令里用来占位「重量」的写法（表示使用默认重量）
WEIGHT_PLACEHOLDERS = {"-", "—", "–", "/", "\\", "无", "none", "null", "skip", "默认"}

# 配送方式关键词
CHANNEL_WORDS = {"express", "national", "极速达", "全国配"}

# 支付方式：auto 表示不指定 type，由网关跳转收银台让买家自选
PAY_TYPE_AUTO = "auto"
PAY_TYPES = (PAY_TYPE_AUTO, "alipay", "wxpay", "qqpay")

PAY_TYPE_LABELS = {
    PAY_TYPE_AUTO: "不限（收银台）",
    "alipay": "支付宝",
    "wxpay": "微信支付",
    "qqpay": "QQ钱包",
}

# 指令里识别支付方式的写法（中文别名友好）
PAY_TYPE_WORDS = {
    "alipay": "alipay",
    "zfb": "alipay",
    "支付宝": "alipay",
    "wxpay": "wxpay",
    "wx": "wxpay",
    "weixin": "wxpay",
    "微信": "wxpay",
    "微信支付": "wxpay",
    "qqpay": "qqpay",
    "qq": "qqpay",
    "qq钱包": "qqpay",
    "aq": "qqpay",
    "auto": PAY_TYPE_AUTO,
    "不限": PAY_TYPE_AUTO,
    "任意": PAY_TYPE_AUTO,
    "收银台": PAY_TYPE_AUTO,
    "自选": PAY_TYPE_AUTO,
}


def parse_pay_type(token: str | None) -> str:
    """识别指令里的支付方式写法（含中文别名），认不出返回空字符串。"""
    text = str(token or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in PAY_TYPE_WORDS:
        return PAY_TYPE_WORDS[lowered]
    for key, value in PAY_TYPE_WORDS.items():
        if key.lower() == lowered:
            return value
    return ""
