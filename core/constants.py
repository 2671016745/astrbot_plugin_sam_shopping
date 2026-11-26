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
