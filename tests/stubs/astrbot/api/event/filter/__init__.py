"""过滤器装饰器存根：只标记，不改变函数。"""


class _EventMessageType:
    GROUP_MESSAGE = "group"
    PRIVATE_MESSAGE = "private"
    OTHER_MESSAGE = "other"
    ALL = "all"


EventMessageType = _EventMessageType()


def event_message_type(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


def on_astrbot_loaded(**kwargs):
    def decorator(func):
        return func

    return decorator


def command(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


class RegisteringCommandable:
    """模拟 astrbot 的指令组返回对象，支持级联注册子指令。"""

    def __init__(self, name, alias=None):
        self.name = name
        self.alias = set(alias or ())
        self.sub_commands = []

    def command(self, *args, **kwargs):
        def decorator(func):
            self.sub_commands.append((args, kwargs, func))
            return func

        return decorator

    def group(self, *args, **kwargs):
        return self.command(*args, **kwargs)

    def custom_filter(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def command_group(*args, **kwargs):
    def decorator(func):
        return RegisteringCommandable(args[0] if args else None, kwargs.get("alias"))

    return decorator


def regex(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


def permission_type(*args, **kwargs):
    def decorator(func):
        return func

    return decorator
