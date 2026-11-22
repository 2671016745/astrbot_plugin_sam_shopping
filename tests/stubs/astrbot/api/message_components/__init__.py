"""astrbot.api.message_components 存根。"""


class Plain:
    def __init__(self, text=""):
        self.text = text


class Image:
    def __init__(self, file=None, url=None):
        self.file = file
        self.url = url

    @classmethod
    def fromFileSystem(cls, path):
        return cls(file=path)

    @classmethod
    def fromURL(cls, url):
        return cls(url=url)


class At:
    def __init__(self, qq=None, name=None):
        self.qq = qq
        self.name = name
