"""把支付链接渲染成二维码图片。"""
from __future__ import annotations

import os


def render_qr(content: str, path: str | os.PathLike) -> str | None:
    """生成二维码 PNG，返回文件路径；失败返回 None（调用方应回退为文本链接）。"""
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None
    try:
        img = qrcode.make(content)
        target = str(path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        img.save(target)
        return target
    except Exception:  # noqa: BLE001 - 渲染失败不应影响下单流程
        return None
