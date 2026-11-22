"""测试用的 astrbot.api.event 存根。"""
from . import filter
from .message_event_result import AstrMessageEvent, MessageChain, MessageEventResult

__all__ = ["filter", "AstrMessageEvent", "MessageChain", "MessageEventResult"]
