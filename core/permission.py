"""指令权限过滤器。

AstrBot 的 ``@filter.permission_type(PermissionType.ADMIN)`` 判定的是**平台管理员**
（``event.is_admin()``，即群主/群管理或 AstrBot 配置的管理员）。
本插件的 ``general.admins`` 是另一份名单，两者不一致时会出现
「指令页写着仅管理员、实际配置里的管理员却用不了」的情况。

所以这里给 ``add`` 子指令单独挂一个 ``PermissionTypeFilter``：
- ``permission_type`` 仍是 ``ADMIN``，WebUI 的权限列照常显示「仅管理员」；
- ``filter()`` 改为调用插件自己的判断函数。
"""
from __future__ import annotations

import logging
from typing import Callable

from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter

logger = logging.getLogger("astrbot.plugins.sam_shopping")

_HANDLER_NAME = "sam_add"
_MODULE_SUFFIX = "astrbot_plugin_sam_shopping.main"


class ConfigAdminFilter(PermissionTypeFilter):
    """显示为「仅管理员」，实际按插件配置的管理员名单校验。"""

    def __init__(self, check: Callable[[object], bool]) -> None:
        super().__init__(PermissionType.ADMIN)
        self._check = check

    def filter(self, event, cfg) -> bool:  # noqa: ANN001, ARG002
        try:
            return bool(self._check(event))
        except Exception:  # noqa: BLE001
            logger.exception("add 指令管理员校验失败")
            return False


def install_admin_permission(checker: Callable[[object], bool]) -> None:
    """把 ``add`` 子指令的权限改为按 ``checker(event)`` 判断。

    找不到 handler 或框架模块缺失（例如测试 stub）时静默跳过，不影响插件加载。
    """
    try:
        from astrbot.core.star.star_handler import star_handlers_registry
    except Exception:  # noqa: BLE001
        return

    for handler in star_handlers_registry:
        if handler.handler_name != _HANDLER_NAME:
            continue
        if not str(handler.handler_module_path).endswith(_MODULE_SUFFIX):
            continue
        if any(isinstance(f, ConfigAdminFilter) for f in handler.event_filters):
            return  # 幂等，重复初始化不会叠加
        handler.event_filters.append(ConfigAdminFilter(checker))
        return
