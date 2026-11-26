"""山姆代购 AstrBot 插件入口。

两种指令入口，行为完全一致：

1. 可配置唤醒词（默认 ``sam's``）：

       sam's help
       sam's menu 水果 车厘子
       sam's buy 牛奶 2
       sam's basket
       sam's basket delete 1
       sam's basket clear
       sam's pay 极速达
       sam's add 水果 车厘子 智利车厘子 89.9 1.5

2. 官方指令组（出现在 AstrBot WebUI 的「指令」页，可改名 / 加别名 / 禁用）。
   主指令 `山姆`，别名 `sam's` 与 `sam`，三者等价：

       /山姆 menu 水果 车厘子
       /sam's buy 牛奶 2
       /sam pay 极速达
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

from .core import messages
from .core.config import AppConfig, ConfigError
from .core.mailer import Mailer
from .core.models import ORDER_PAID, ORDER_PENDING
from .core.payment import YiPayClient
from .core.qrcode_util import render_qr
from .core.service import SamService, ServiceError
from .core.store import Repository

PLUGIN_DIR_NAME = "astrbot_plugin_sam_shopping"

WAKE_PREFIX_CHARS = "/。｡.!！#~·、-—"

SUB_COMMAND_ALIASES = {
    "help": "help",
    "帮助": "help",
    "h": "help",
    "menu": "menu",
    "菜单": "menu",
    "商品": "menu",
    "buy": "buy",
    "购买": "buy",
    "加购": "buy",
    "basket": "basket",
    "cart": "basket",
    "购物车": "basket",
    "pay": "pay",
    "支付": "pay",
    "下单": "pay",
    "add": "add",
    "添加": "add",
    "上架": "add",
    "confirm": "confirm",
    "确认": "confirm",
    "cancel": "cancel",
    "取消": "cancel",
}

BARE_CONFIRM = {"确认", "确定", "是的", "yes", "y", "ok", "好", "好哒"}
BARE_CLEAR = {"确认清空", "清空确认", "确定清空"}
BARE_CANCEL = {"取消", "cancel", "no", "n", "算了"}

from .core.constants import (
    CHANNEL_WORDS,
    COMMAND_GROUP_ALIASES,
    COMMAND_GROUP_NAME,
    COMMAND_GROUP_NAMES,
    COMMAND_SUB_NAMES,
    WEIGHT_PLACEHOLDERS,
)


class SamShoppingPlugin(Star):
    """山姆代购插件。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        try:
            self.config = AppConfig.from_dict(config or {})
        except ConfigError as exc:
            logger.error("山姆代购配置无效，已回退到默认配置：%s", exc)
            self.config = AppConfig.from_dict({})

        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_DIR_NAME))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.qr_dir = self.data_dir / "qr"

        self.repo = Repository(self.data_dir, self.config.storage)
        self.service = SamService(self.repo, self.config)
        self.payment = YiPayClient(self.config.payment)
        self.mailer = Mailer(self.config.smtp)

        self._pending: dict[str, dict] = {}
        self._poll_task: asyncio.Task | None = None
        self._paid_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        self._paid_lock = asyncio.Lock()
        self._start_polling()

    def terminate(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def _start_polling(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            return
        try:
            self._poll_task = asyncio.create_task(self._poll_loop())
        except RuntimeError:
            # 没有正在运行的事件循环时忽略，待下次机会再启动
            logger.warning("山姆代购：当前没有事件循环，支付轮询未启动")

    # ------------------------------------------------------------------
    # 指令解析
    # ------------------------------------------------------------------
    def _parse(self, text: str):
        s = text.strip()
        s = s.lstrip(WAKE_PREFIX_CHARS).strip()
        s = re.sub(r"^@[^\s]+\s*", "", s).strip()
        if not s:
            return None

        words = [self.config.wake_word, *self.config.wake_aliases]
        for word in words:
            if not word:
                continue
            if s.lower().startswith(word.lower()):
                rest = s[len(word):]
                legacy_prefix = False
                probe = rest.lstrip()
                # 兼容「唤醒词 + sam's + 子指令」的写法
                if probe.lower().startswith("sam's") and (
                    len(probe) == 5 or probe[5:6].isspace()
                ):
                    rest = probe[5:]
                    legacy_prefix = True
                if rest and not rest[0].isspace() and not legacy_prefix:
                    continue
                parts = rest.split()
                if not parts:
                    return ("help", [], s)
                sub = SUB_COMMAND_ALIASES.get(parts[0].lower())
                if sub is None:
                    return ("help", [], s)
                return (sub, parts[1:], s)

        key = s.lower()
        if key in BARE_CONFIRM:
            return ("confirm", [], s)
        if key in BARE_CLEAR:
            return ("confirm_clear", [], s)
        if key in BARE_CANCEL:
            return ("cancel", [], s)
        if re.fullmatch(r"\d{1,3}", s):
            return ("delete_index", [s], s)
        return None

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """所有消息入口：识别唤醒词后分发到具体指令。"""
        try:
            text = (event.get_message_str() or "").strip()
        except Exception:  # noqa: BLE001
            return
        if not text:
            return
        parsed = self._parse(text)
        if parsed is None:
            return
        # 唤醒词与官方指令同名时（例如唤醒词配成 sam's），官方指令交给 command handler，
        # 这里不再回复，避免同一条消息被两套逻辑各回一次。
        if getattr(event, "is_at_or_wake_command", False) and self._is_official_command(text):
            return
        try:
            async for item in self._dispatch(parsed, event):
                yield item
        except ServiceError as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("山姆代购指令处理异常")
            yield event.plain_result(f"指令处理出错：{exc}")

    @staticmethod
    def _is_official_command(text: str) -> bool:
        """判断是否是官方指令组（主指令或别名开头），避免唤醒词与官方指令重复响应。"""
        tokens = re.sub(r"\s+", " ", text.strip()).split(" ")
        if not tokens or tokens[0].lower() not in {
            name.lower() for name in COMMAND_GROUP_NAMES
        }:
            return False
        if len(tokens) == 1:
            return True
        return tokens[1].lower() in COMMAND_SUB_NAMES

    @staticmethod
    def _command_args(event: AstrMessageEvent, depth: int = 2) -> list[str]:
        """取出官方指令 ``sam <sub> ...`` 中 ``...`` 部分的参数。"""
        text = re.sub(r"\s+", " ", str(event.get_message_str() or "").strip())
        tokens = [token for token in text.split(" ") if token]
        return tokens[depth:]

    # ------------------------------------------------------------------
    # 官方指令（WebUI「指令」页可见，可改名 / 加别名 / 禁用）
    # ------------------------------------------------------------------
    @filter.command_group(COMMAND_GROUP_NAME, alias=COMMAND_GROUP_ALIASES)
    async def sam(self, event: AstrMessageEvent) -> None:
        """山姆代购：menu / buy / basket / pay / add / help"""

    @sam.command("help")
    async def sam_help(self, event: AstrMessageEvent):
        """查看指令帮助、配送方式与运费规则"""
        async for item in self._cmd_help(self._command_args(event), event):
            yield item

    @sam.command("menu")
    async def sam_menu(self, event: AstrMessageEvent):
        """浏览商品分类与商品"""
        async for item in self._cmd_menu(self._command_args(event), event):
            yield item

    @sam.command("buy")
    async def sam_buy(self, event: AstrMessageEvent):
        """把商品加入购物车"""
        async for item in self._cmd_buy(self._command_args(event), event):
            yield item

    @sam.command("basket")
    async def sam_basket(self, event: AstrMessageEvent):
        """查看 / 删除 / 清空购物车"""
        async for item in self._cmd_basket(self._command_args(event), event):
            yield item

    @sam.command("pay")
    async def sam_pay(self, event: AstrMessageEvent):
        """确认购物车并生成收款二维码"""
        async for item in self._cmd_pay(self._command_args(event), event):
            yield item

    @sam.command("add")
    async def sam_add(self, event: AstrMessageEvent):
        """管理员添加商品"""
        async for item in self._cmd_add(self._command_args(event), event):
            yield item

    async def _dispatch(self, parsed, event: AstrMessageEvent):
        sub, args, _raw = parsed
        handler = getattr(self, f"_cmd_{sub}", None)
        if handler is None:
            return
        async for item in handler(list(args), event):
            yield item

    # ------------------------------------------------------------------
    # 待确认操作
    # ------------------------------------------------------------------
    def _set_pending(self, user_id: str, kind: str, data: dict) -> None:
        self._pending[user_id] = {"type": kind, "ts": time.time(), **data}

    def _get_pending(self, user_id: str) -> dict | None:
        pending = self._pending.get(user_id)
        if pending is None:
            return None
        ttl = max(1, self.config.order.expire_minutes) * 60
        if time.time() - pending.get("ts", 0) > ttl:
            self._pending.pop(user_id, None)
            return None
        return pending

    def _pop_pending(self, user_id: str) -> None:
        self._pending.pop(user_id, None)

    # ------------------------------------------------------------------
    # 指令实现
    # ------------------------------------------------------------------
    async def _cmd_help(self, args, event: AstrMessageEvent):
        yield event.plain_result(messages.format_help(self.config, self._has_products()))

    async def _cmd_menu(self, args, event: AstrMessageEvent):
        if not args:
            yield event.plain_result(messages.format_menu_categories(self.service.categories()))
            return
        if len(args) == 1:
            subs = self.service.subcategories(args[0])
            yield event.plain_result(messages.format_menu_subcategories(args[0], subs))
            return
        products = self.service.products(args[0], args[1])
        yield event.plain_result(messages.format_menu_products(args[0], args[1], products))

    async def _cmd_buy(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        if not args:
            yield event.plain_result(
                "请指定商品名称（可带数量），例如：buy 牛奶 2。发送「menu」查看商品。"
            )
            return
        qty = 1
        name_parts = list(args)
        if len(args) >= 2 and args[-1].isdigit():
            qty = int(args[-1])
            name_parts = args[:-1]
        name = " ".join(name_parts).strip()
        product = self.service.find_product(name)
        if product is None:
            yield event.plain_result(
                f"未找到商品「{name}」。请发送「menu」查看商品列表，或确认商品名称后重试。"
            )
            return
        items = self.service.cart_add(user_id, product, qty)
        yield event.plain_result(
            f"已加入购物车：{product.name} × {qty}\n\n{messages.format_cart(items)}"
        )

    async def _cmd_basket(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        sub = args[0].lower() if args else ""
        if sub == "clear":
            rest = args[1:]
            if rest and rest[0].lower() in {"confirm", "确认", "确定"}:
                self.service.cart_clear(user_id)
                self._pop_pending(user_id)
                yield event.plain_result("购物车已清空。")
                return
            items = self.service.cart(user_id)
            if not items:
                yield event.plain_result("购物车已经是空的。")
                return
            self._set_pending(user_id, "clear", {})
            yield event.plain_result(
                f"确定要清空购物车吗？当前共 {len(items)} 种商品。\n"
                "回复「确认清空」执行，回复「取消」放弃。"
            )
            return
        if sub == "delete":
            rest = args[1:]
            if rest and rest[0].isdigit():
                items = self.service.cart_remove_at(user_id, int(rest[0]))
                self._pop_pending(user_id)
                yield event.plain_result(f"已删除。\n\n{messages.format_cart(items)}")
                return
            items = self.service.cart(user_id)
            if not items:
                yield event.plain_result("购物车是空的。")
                return
            self._set_pending(user_id, "delete", {})
            yield event.plain_result(messages.format_cart_numbered(items))
            return
        if sub in {"", "view", "list"}:
            yield event.plain_result(messages.format_cart(self.service.cart(user_id)))
            return
        yield event.plain_result("无法识别的购物车指令，发送「help」查看帮助。")

    async def _cmd_pay(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        user_name = str(event.get_sender_name() or "") or user_id

        if args and args[0].lower() in BARE_CANCEL:
            self._pop_pending(user_id)
            yield event.plain_result("已取消下单。")
            return

        channel = None
        if args and args[0].lower() in CHANNEL_WORDS:
            channel = args[0]
            args = args[1:]

        if args and args[0].lower() in {"confirm", "确认", "确定"}:
            async for item in self._do_pay(event, {"type": "pay", "channel": channel, "ts": time.time()}):
                yield item
            return

        items = self.service.cart(user_id)
        if not items:
            yield event.plain_result("购物车是空的，无法下单。发送「menu」浏览商品。")
            return

        order = self.service.preview_order(user_id, user_name, channel)
        freight, proxy = self.service.preview_fees(user_id, channel)
        self._set_pending(user_id, "pay", {"channel": channel})
        yield event.plain_result(
            messages.format_order_preview(order, messages.format_fee_lines(freight, proxy))
        )

    async def _do_pay(self, event: AstrMessageEvent, pending: dict):
        user_id = str(event.get_sender_id() or "")
        user_name = str(event.get_sender_name() or "") or user_id
        umo = event.unified_msg_origin
        channel = pending.get("channel")

        try:
            order = self.service.build_order(user_id, user_name, channel, umo=umo)
        except ServiceError as exc:
            self._pop_pending(user_id)
            yield event.plain_result(str(exc))
            return

        result = await self.payment.create_payment(order, self.config.shop_name)
        if not result.ok:
            self.service.cancel_order(order.order_id, "生成收款码失败")
            self._pop_pending(user_id)
            logger.error("订单 %s 生成收款码失败：%s", order.order_id, result.message)
            yield event.plain_result(
                f"生成收款二维码失败：{result.message}\n订单已取消，请稍后重试。"
            )
            return

        self._pop_pending(user_id)
        qr_path = render_qr(result.qr_url, self.qr_dir / f"{order.order_id}.png")
        if qr_path:
            yield event.image_result(qr_path)
            yield event.plain_result(
                messages.format_order_created(order, self.config.order.expire_minutes)
            )
        else:
            logger.warning("订单 %s 二维码渲染失败，改为发送收款链接", order.order_id)
            yield event.plain_result(
                messages.format_order_created(order, self.config.order.expire_minutes)
                + f"\n收款链接：{result.qr_url}"
            )

    async def _cmd_confirm(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        pending = self._get_pending(user_id)
        if pending is None:
            yield event.plain_result("当前没有待确认的操作。")
            return
        if pending.get("type") == "pay":
            async for item in self._do_pay(event, pending):
                yield item
            return
        if pending.get("type") == "clear":
            self.service.cart_clear(user_id)
            self._pop_pending(user_id)
            yield event.plain_result("购物车已清空。")
            return
        if pending.get("type") == "delete":
            yield event.plain_result("请回复要删除的商品序号（数字）。")
            return
        self._pop_pending(user_id)
        yield event.plain_result("当前没有待确认的操作。")

    async def _cmd_confirm_clear(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        self.service.cart_clear(user_id)
        self._pop_pending(user_id)
        yield event.plain_result("购物车已清空。")

    async def _cmd_cancel(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        self._pop_pending(user_id)
        yield event.plain_result("已取消。")

    async def _cmd_delete_index(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        pending = self._get_pending(user_id)
        if pending is None or pending.get("type") != "delete":
            # 裸数字不是指令，忽略
            return
        if not args or not args[0].isdigit():
            yield event.plain_result("请回复有效的商品序号。")
            return
        items = self.service.cart_remove_at(user_id, int(args[0]))
        self._pop_pending(user_id)
        yield event.plain_result(f"已删除。\n\n{messages.format_cart(items)}")

    async def _cmd_add(self, args, event: AstrMessageEvent):
        user_id = str(event.get_sender_id() or "")
        try:
            platform_admin = bool(event.is_admin())
        except Exception:  # noqa: BLE001
            platform_admin = False
        if not self.config.is_admin(user_id, platform_admin):
            yield event.plain_result("该指令仅管理员可用。")
            return
        if len(args) < 4:
            yield event.plain_result(
                "格式：add <大分类> <小分类> <商品名称> <价格> [重量kg] [代购费元/件]\n"
                "例如：add 水果 车厘子 智利车厘子 89.9 1.5\n"
                "      add 水果 车厘子 智利车厘子 89.9 1.5 5\n"
                "      add 水果 车厘子 智利车厘子 89.9 - 5（重量用默认值）"
            )
            return
        category, subcategory = args[0], args[1]
        # 末尾最多三个数字依次是「价格」「重量」「代购费」，其余是商品名称。
        # 重量可用「-」占位，表示使用默认重量。
        slots: list[str] = []
        index = len(args) - 1
        while len(slots) < 3 and index >= 3:
            token = args[index]
            if self._is_number(token) or token in WEIGHT_PLACEHOLDERS:
                slots.append(token)
                index -= 1
            else:
                break
        slots.reverse()
        if not slots or not self._is_number(slots[0]):
            yield event.plain_result("无法识别价格，请在商品名称之后填写价格。")
            return
        price_index = len(args) - len(slots)
        name = " ".join(args[2:price_index]).strip()
        if not name:
            yield event.plain_result("商品名称不能为空。")
            return
        weight = slots[1] if len(slots) >= 2 and self._is_number(slots[1]) else None
        fee = slots[2] if len(slots) >= 3 and self._is_number(slots[2]) else None
        product = self.service.add_product(
            category, subcategory, name, slots[0], weight, fee
        )
        lines = [
            f"已添加商品：{product.name}",
            f"分类：{product.category}/{product.subcategory}",
            f"价格：{product.price} 元",
            f"重量：{product.weight_kg} kg",
        ]
        if product.fee > 0:
            lines.append(f"代购费：{product.fee} 元/件（优先于全局规则）")
        yield event.plain_result("\n".join(lines))

    @staticmethod
    def _is_number(text: str) -> bool:
        try:
            float(text)
        except (TypeError, ValueError):
            return False
        return True

    def _has_products(self) -> bool:
        try:
            return bool(self.service.products())
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # 支付状态轮询
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        interval = max(1.0, float(self.config.poll.interval))
        while True:
            try:
                await self._check_pending_orders()
            except Exception:  # noqa: BLE001
                logger.exception("山姆代购支付轮询异常")
            await asyncio.sleep(interval)

    async def _check_pending_orders(self) -> None:
        for order in list(self.service.pending_orders()):
            if self.service.order_age(order) > self.config.poll.timeout:
                closed = self.service.expire_order(order.order_id)
                if closed is not None:
                    logger.info("订单 %s 支付超时，已关闭", order.order_id)
                    await self._notify_user(
                        order,
                        f"订单 {order.order_id} 超过 {int(self.config.poll.timeout)} 秒未支付，已自动关闭。",
                    )
                continue

            status = await self.payment.query_payment(order)
            if status.paid:
                await self._handle_paid(order, status.trade_no)
                continue
            if status.message:
                # 查询失败（网络/网关错误），记录并累计失败次数
                self.service.mark_query_failure(order.order_id)
                logger.warning(
                    "订单 %s 查询支付状态失败：%s", order.order_id, status.message
                )
                fresh = self.service.get_order(order.order_id)
                if (
                    fresh is not None
                    and fresh.consecutive_failures >= self.config.poll.max_consecutive_failures
                ):
                    logger.error(
                        "订单 %s 连续 %s 次查询失败，请检查易支付网关配置",
                        order.order_id,
                        fresh.consecutive_failures,
                    )
            else:
                self.service.mark_query_success(order.order_id)

    async def _handle_paid(self, order, trade_no: str) -> None:
        if self._paid_lock is None:  # pragma: no cover - 理论上不会发生
            self._paid_lock = asyncio.Lock()
        async with self._paid_lock:
            fresh = self.service.get_order(order.order_id)
            if fresh is None or fresh.status != ORDER_PENDING:
                return
            paid = self.service.mark_paid(fresh.order_id, trade_no)
        if paid is None:
            return
        logger.info("订单 %s 支付成功，交易号 %s", paid.order_id, trade_no or "-")
        await self._notify_user(paid, messages.format_order_paid(paid))
        await self._notify_admin(paid)

    async def _notify_user(self, order, text: str) -> None:
        if not order.umo:
            return
        try:
            await self.context.send_message(order.umo, MessageChain().message(text))
        except Exception as exc:  # noqa: BLE001
            logger.error("订单 %s 通知用户失败：%s", order.order_id, exc)

    async def _notify_admin(self, order) -> None:
        if order.email_sent:
            return
        if not self.mailer.configured:
            self.service.mark_email_sent(order.order_id, error="SMTP 未配置")
            logger.error("订单 %s 支付成功，但 SMTP 未配置，无法发送代购通知邮件", order.order_id)
            return
        if order.email_attempts >= max(1, self.config.order.max_email_attempts):
            self.service.mark_email_sent(order.order_id, error="超过邮件重试次数")
            logger.error("订单 %s 代购通知邮件重试次数用尽，不再发送", order.order_id)
            return

        subject = messages.format_email_subject(order, self.config.shop_name)
        body = messages.format_email_body(order, self.config.shop_name)
        result = await self.mailer.send(subject, body)
        if result.ok:
            self.service.mark_email_sent(order.order_id)
            logger.info("订单 %s 代购通知邮件已发送至 %s", order.order_id, self.config.smtp.admin_email)
        else:
            self.service.mark_email_sent(order.order_id, error=result.error)
            logger.error(
                "订单 %s 代购通知邮件发送失败：%s", order.order_id, result.error
            )
