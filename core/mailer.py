"""SMTP 邮件发送（管理员通知）。

使用标准库 ``smtplib``，通过 ``asyncio.to_thread`` 避免阻塞事件循环。
密码只用于登录，不会被记录到日志或聊天。
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText
from typing import Awaitable, Callable

from .config import SmtpConfig

MailSender = Callable[[str, str], Awaitable["MailResult"]]


class MailResult:
    def __init__(self, ok: bool, error: str = "") -> None:
        self.ok = ok
        self.error = error

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"MailResult(ok={self.ok}, error={self.error!r})"


class Mailer:
    def __init__(self, cfg: SmtpConfig, sender: MailSender | None = None) -> None:
        self.cfg = cfg
        self._sender = sender

    @property
    def configured(self) -> bool:
        return self.cfg.configured

    async def send(self, subject: str, body: str) -> MailResult:
        if not self.cfg.configured:
            return MailResult(False, "SMTP 未配置（server/username/password/admin_email）")
        if self._sender is not None:
            return await self._sender(subject, body)
        return await asyncio.to_thread(self._sync_send, subject, body)

    def _sync_send(self, subject: str, body: str) -> MailResult:
        sender = self.cfg.sender or self.cfg.username
        try:
            if self.cfg.use_tls:
                server = smtplib.SMTP_SSL(self.cfg.server, self.cfg.port, timeout=20)
            else:
                server = smtplib.SMTP(self.cfg.server, self.cfg.port, timeout=20)
            with server:
                if not self.cfg.use_tls:
                    server.starttls()
                server.ehlo()
                server.login(self.cfg.username, self.cfg.password)
                message = MIMEText(body, "plain", "utf-8")
                message["Subject"] = subject
                message["From"] = sender
                message["To"] = self.cfg.admin_email
                server.sendmail(sender, [self.cfg.admin_email], message.as_string())
            return MailResult(True)
        except Exception as exc:  # noqa: BLE001 - 统一返回可理解错误
            return MailResult(False, f"{type(exc).__name__}: {exc}")
