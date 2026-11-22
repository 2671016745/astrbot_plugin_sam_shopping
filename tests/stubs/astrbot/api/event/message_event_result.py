"""消息事件与消息链存根。"""


class MessageChain:
    def __init__(self, chain=None):
        self.chain = list(chain or [])

    def message(self, text):
        self.chain.append(("plain", text))
        return self

    def file_image(self, path):
        self.chain.append(("image", path))
        return self


class MessageEventResult:
    pass


class AstrMessageEvent:
    """占位类型，测试用 FakeEvent 代替。"""
