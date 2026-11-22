"""astrbot.api.star 存根。"""
import os
from pathlib import Path


class Context:
    def __init__(self):
        self.sent = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, list(getattr(chain, "chain", []))))
        return True


class Star:
    def __init__(self, context, config=None):
        self.context = context
        self.config = config


class StarTools:
    _data_dir = None

    @classmethod
    def get_data_dir(cls, plugin_name=None):
        base = os.environ.get("SAM_TEST_DATA_DIR")
        if base:
            return Path(base)
        if cls._data_dir is None:
            cls._data_dir = Path("/tmp/sam_shopping_test_data")
        return cls._data_dir


def register(*args, **kwargs):
    def decorator(cls):
        return cls

    return decorator
