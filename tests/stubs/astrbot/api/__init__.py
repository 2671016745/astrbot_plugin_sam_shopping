"""测试用的 astrbot.api 存根。"""
import logging

logger = logging.getLogger("astrbot.stub")


class AstrBotConfig(dict):
    def save_config(self) -> None:
        pass


sp = None
