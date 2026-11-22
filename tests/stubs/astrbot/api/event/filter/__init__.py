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


def command_group(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


def regex(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


def permission_type(*args, **kwargs):
    def decorator(func):
        return func

    return decorator
