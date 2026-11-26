"""测试用 stub：只提供权限过滤器需要的最小实现。"""
import enum


class PermissionType(enum.Flag):
    ADMIN = enum.auto()
    MEMBER = enum.auto()
    GROUP_ADMIN = enum.auto()
    SHARED_GROUP_ADMIN = enum.auto()


COMMAND_PERMISSION_TYPES = {
    "admin": PermissionType.ADMIN,
    "member": PermissionType.MEMBER,
    "group_admin": PermissionType.GROUP_ADMIN,
    "shared_group_admin": PermissionType.SHARED_GROUP_ADMIN,
}


class PermissionTypeFilter:
    def __init__(self, permission_type, raise_error=True):
        self.permission_type = permission_type
        self.raise_error = raise_error

    def filter(self, event, cfg):
        if self.permission_type == PermissionType.ADMIN:
            return bool(getattr(event, "is_admin", lambda: False)())
        return True
