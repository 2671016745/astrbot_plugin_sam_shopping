"""山姆代购插件测试入口：python3 tests/run_tests.py"""
from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import sys
import tempfile
import traceback
from decimal import Decimal
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

import harness  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="sam_test_"))
os.environ["SAM_TEST_DATA_DIR"] = str(TMP / "data" / "plugin_data")

main_module = harness.load_plugin(TMP)
SamShoppingPlugin = main_module.SamShoppingPlugin


def _core(name: str):
    return importlib.import_module(f"{harness.FULL_PKG}.core.{name}")


messages = _core("messages")
config_mod = _core("config")
freight_mod = _core("freight")
mailer_mod = _core("mailer")
models_mod = _core("models")
payment_mod = _core("payment")
service_mod = _core("service")
store_mod = _core("store")

AppConfig = config_mod.AppConfig
build_rule = freight_mod.build_rule
calc_freight = freight_mod.calc_freight
MailResult = mailer_mod.MailResult
ORDER_PAID = models_mod.ORDER_PAID
ORDER_PENDING = models_mod.ORDER_PENDING
CreatePaymentResult = payment_mod.CreatePaymentResult
PaymentStatusResult = payment_mod.PaymentStatusResult
SamService = service_mod.SamService
ServiceError = service_mod.ServiceError
Repository = store_mod.Repository

from astrbot.api.star import Context  # noqa: E402

RESULTS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    suffix = f"  -> {detail}" if detail and not condition else ""
    print(f"[{mark}] {name}{suffix}")


def eq(name: str, actual, expected) -> None:
    check(name, actual == expected, f"实际 {actual!r} != 期望 {expected!r}")


# ----------------------------------------------------------------------
# 假事件 / 假支付 / 假邮件
# ----------------------------------------------------------------------
class FakeEvent:
    def __init__(self, text, sender_id="u1", sender_name="测试用户", umo="umo|u1", admin=False):
        self._text = text
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.umo = umo
        self.admin_flag = admin
        self.results = []

    def get_message_str(self):
        return self._text

    def get_sender_id(self):
        return self.sender_id

    def get_sender_name(self):
        return self.sender_name

    @property
    def unified_msg_origin(self):
        return self.umo

    def plain_result(self, text):
        result = {"type": "plain", "text": text}
        self.results.append(result)
        return result

    def image_result(self, path):
        result = {"type": "image", "path": str(path)}
        self.results.append(result)
        return result

    def chain_result(self, chain):
        result = {"type": "chain", "chain": chain}
        self.results.append(result)
        return result

    def is_admin(self):
        return self.admin_flag


class FakePayment:
    def __init__(self, ok=True, qr_url="https://pay.example.com/qr/abc", message=""):
        self.ok = ok
        self.qr_url = qr_url
        self.message = message
        self.created = []
        self.queries = 0
        self.paid = False
        self.trade_no = "TRADE123"

    async def create_payment(self, order, shop_name="山姆代购"):
        self.created.append(order)
        if self.ok:
            return CreatePaymentResult(ok=True, qr_url=self.qr_url)
        return CreatePaymentResult(ok=False, message=self.message or "生成失败")

    async def query_payment(self, order):
        self.queries += 1
        return PaymentStatusResult(paid=self.paid, trade_no=self.trade_no)


class FakeMailer:
    def __init__(self, ok=True, error=""):
        self.ok = ok
        self.error = error
        self.sent = []

    @property
    def configured(self):
        return True

    async def send(self, subject, body):
        self.sent.append((subject, body))
        return MailResult(self.ok, self.error)


async def run_cmd(plugin, text, **kwargs):
    event = FakeEvent(text, **kwargs)
    out = []
    async for item in plugin.on_message(event):
        out.append(item)
    return event, out


def make_plugin(config: dict, name: str, ctx=None):
    """创建插件实例，并给它一个独立的测试数据目录，避免用例之间互相污染。"""
    os.environ["SAM_TEST_DATA_DIR"] = str(TMP / "data" / "plugin_data" / name)
    return SamShoppingPlugin(ctx or Context(), config)


def texts(out):
    return "\n".join(item.get("text", "") for item in out if item.get("type") == "plain")


# ----------------------------------------------------------------------
# 1. 运费规则
# ----------------------------------------------------------------------
def test_freight():
    cfg = AppConfig.from_dict({})
    express = build_rule("express", cfg.express)
    national = build_rule("national", cfg.national)

    cases_express = [
        ((50, 10), "10.00"),
        ((99, 10), "0.00"),
        ((50, 20), "15.00"),
        ((99, 20), "5.00"),
        ((150, 10), "0.00"),
        ((150, 20), "0.00"),
        ((250, 40), "5.00"),
        ((99.99, 15), "0.00"),
        ((0, 0), "10.00"),
    ]
    for (amount, weight), expected in cases_express:
        result = calc_freight(amount, weight, express)
        eq(f"极速达 {amount}元/{weight}kg 运费", f"{result.freight:.2f}", expected)

    cases_national = [
        ((50, 10), "15.00"),
        ((100, 10), "5.00"),
        ((200, 10), "0.00"),
        ((299, 10), "0.00"),
        ((50, 20), "20.00"),
        ((150, 20), "5.00"),
        ((299, 20), "0.00"),
    ]
    for (amount, weight), expected in cases_national:
        result = calc_freight(amount, weight, national)
        eq(f"全国配 {amount}元/{weight}kg 运费", f"{result.freight:.2f}", expected)

    result_goods = calc_freight(90, 10, express, "goods")
    result_total = calc_freight(90, 10, express, "total")
    check(
        "含运费基数与商品基数结果不同",
        result_goods.freight != result_total.freight,
        f"goods={result_goods.freight} total={result_total.freight}",
    )
    check(
        "含运费基数 = 商品金额 + 商品基数运费",
        result_total.billing_amount == result_total.goods_amount + result_goods.freight,
        f"billing={result_total.billing_amount}",
    )

    try:
        calc_freight(-1, 10, express)
        check("负金额应报错", False)
    except Exception:  # noqa: BLE001
        check("负金额应报错", True)


# ----------------------------------------------------------------------
# 2. 业务逻辑与持久化
# ----------------------------------------------------------------------
def test_service():
    data_dir = TMP / "svc"
    cfg = AppConfig.from_dict({})
    repo = Repository(data_dir, cfg.storage)
    svc = SamService(repo, cfg)

    p1 = svc.add_product("水果", "车厘子", "智利车厘子", "89.9", "1.5")
    p2 = svc.add_product("水果", "车厘子", "蓝莓", "29.9", "0.5")
    p3 = svc.add_product("乳品", "牛奶", "鲜牛奶", "19.9", "1")
    eq("商品数量", len(svc.products()), 3)
    eq("大分类", svc.categories(), ["乳品", "水果"])
    eq("小分类", svc.subcategories("水果"), ["车厘子"])
    eq("按名称查找", svc.find_product("蓝莓").id, p2.id)
    eq("模糊查找", svc.find_product("车厘").name, "智利车厘子")

    try:
        svc.add_product("水果", "车厘子", "蓝莓", "10", "1")
        check("重复商品应报错", False)
    except ServiceError:
        check("重复商品应报错", True)

    try:
        svc.add_product("水果", "车厘子", "坏商品", "-5", "1")
        check("负价格应报错", False)
    except ServiceError:
        check("负价格应报错", True)

    svc.cart_add("u1", p1, 2)
    svc.cart_add("u1", p2, 3)
    svc.cart_add("u2", p3, 1)
    eq("u1 购物车种类", len(svc.cart("u1")), 2)
    eq("u2 购物车隔离", len(svc.cart("u2")), 1)

    svc.cart_remove_at("u1", 1)
    eq("删除后 u1 种类", len(svc.cart("u1")), 1)

    svc.cart_add("u1", p1, 1)
    items = svc.cart("u1")
    eq("重新添加后 u1 种类", len(items), 2)
    merged = {item.product.name: item.qty for item in items}
    eq("同一商品合并数量", merged.get("智利车厘子"), 1)
    eq("未删除商品数量保持", merged.get("蓝莓"), 3)

    order = svc.build_order("u1", "测试用户", umo="umo|u1")
    eq("订单状态", order.status, ORDER_PENDING)
    eq("下单后购物车清空", len(svc.cart("u1")), 0)
    eq("订单商品数", len(order.items), 2)
    check("订单金额正确", f"{order.goods_amount:.2f}" == "179.60", str(order.goods_amount))
    check("订单重量正确", f"{order.weight:.2f}" == "3.00", str(order.weight))
    check("订单运费正确", f"{order.freight:.2f}" == "0.00", str(order.freight))
    check("订单总额正确", f"{order.total:.2f}" == "179.60", str(order.total))

    repo2 = Repository(data_dir, cfg.storage)
    svc2 = SamService(repo2, cfg)
    eq("重启后商品不丢失", len(svc2.products()), 3)
    eq("重启后订单不丢失", len(svc2.pending_orders()), 1)
    eq("重启后购物车为空", len(svc2.cart("u1")), 0)

    paid = svc2.mark_paid(order.order_id, "T999")
    eq("标记已支付", paid.status, ORDER_PAID)
    svc2.mark_email_sent(order.order_id)
    svc2.mark_email_sent(order.order_id)
    again = svc2.get_order(order.order_id)
    eq("邮件标记为已发送", again.email_sent, True)
    eq("邮件尝试次数累计", again.email_attempts, 2)


# ----------------------------------------------------------------------
# 2.5 代购费规则
# ----------------------------------------------------------------------
def test_proxy_fee():
    proxy_mod = _core("proxy_fee")
    entries = [proxy_mod.ProxyFeeEntry("智利车厘子", 2, Decimal("3.0"), Decimal("0"))]

    cfg = AppConfig.from_dict({})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("默认不收取代购费", f"{result.amount:.2f}", "0.00")
    check("不收时代价明细为空", result.detail_lines()[0].startswith("代购费"))

    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_order", "fee_per_order": 5}})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("按次代购费", f"{result.amount:.2f}", "5.00")
    check("按次明细说明计算方式", any("元/单" in line for line in result.detail_lines()))

    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_weight", "fee_per_weight": 2}})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("按重量代购费", f"{result.amount:.2f}", "6.00")
    check("按重量明细含 kg", any("kg" in line for line in result.detail_lines()))

    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_item", "fee_per_item": 3}})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("按件数代购费", f"{result.amount:.2f}", "6.00")

    mixed = [
        proxy_mod.ProxyFeeEntry("车厘子", 2, Decimal("3.0"), Decimal("1.5")),
        proxy_mod.ProxyFeeEntry("蓝莓", 3, Decimal("1.5"), Decimal("0")),
    ]
    result = proxy_mod.calc_proxy_fee(mixed, cfg.proxy_fee)
    # 车厘子 2×1.5 = 3；蓝莓 3×3 = 9
    eq("单商品代购费覆盖全局规则", f"{result.amount:.2f}", "12.00")
    check("覆盖时标注商品单独设置", any("商品单独设置" in line for line in result.detail_lines()))

    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_item", "fee_per_item": 1, "fee_min": 10}})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("代购费最低", f"{result.amount:.2f}", "10.00")
    check("代购费最低已标记", result.floored)

    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_item", "fee_per_item": 100, "fee_max": 5}})
    result = proxy_mod.calc_proxy_fee(entries, cfg.proxy_fee)
    eq("代购费封顶", f"{result.amount:.2f}", "5.00")
    check("代购费封顶已标记", result.capped)

    try:
        AppConfig.from_dict({"fee": {"fee_mode": "bogus"}})
        check("非法代购费模式应报错", False)
    except Exception:  # noqa: BLE001
        check("非法代购费模式应报错", True)

    try:
        AppConfig.from_dict({"fee": {"fee_mode": "per_weight", "fee_per_weight": 0}})
        check("按重量但费率为 0 应报错", False)
    except Exception:  # noqa: BLE001
        check("按重量但费率为 0 应报错", True)


def test_proxy_fee_service():
    data_dir = TMP / "fee"
    cfg = AppConfig.from_dict({"fee": {"fee_mode": "per_item", "fee_per_item": 2, "fee_min": 1}})
    repo = Repository(data_dir, cfg.storage)
    svc = SamService(repo, cfg)

    p1 = svc.add_product("水果", "车厘子", "车厘子", "89.9", "1.5", "5")
    p2 = svc.add_product("水果", "车厘子", "蓝莓", "29.9", "0.5")
    eq("商品保存单件代购费", f"{p1.fee:.2f}", "5.00")
    eq("未填时代购费为 0", f"{p2.fee:.2f}", "0.00")

    svc.cart_add("u1", p1, 2)
    svc.cart_add("u1", p2, 3)
    result = svc.calc_proxy_fee("u1")
    # 车厘子 2×5 = 10；蓝莓 3×2 = 6
    eq("服务层代购费", f"{result.amount:.2f}", "16.00")
    check("服务层明细含单件说明", any("5 元/件" in line for line in result.detail_lines()))

    order = svc.build_order("u1", "测试用户")
    eq("订单记录代购费", f"{order.proxy_fee:.2f}", "16.00")
    expected_total = f"{order.goods_amount + order.freight + order.proxy_fee:.2f}"
    eq("订单总额含代购费", f"{order.total:.2f}", expected_total)
    check("订单保存代购费明细", any("代购费" in line for line in order.proxy_fee_detail))

    repo2 = Repository(data_dir, cfg.storage)
    svc2 = SamService(repo2, cfg)
    restored = svc2.get_order(order.order_id)
    eq("重启后订单代购费不丢失", f"{restored.proxy_fee:.2f}", "16.00")


# ----------------------------------------------------------------------
# 3. 指令流程
# ----------------------------------------------------------------------
async def test_commands():
    ctx = Context()
    plugin = make_plugin({"general": {"admins": ["admin1"]}}, "cmd", ctx)
    plugin.payment = FakePayment()
    plugin.mailer = FakeMailer()

    _, out = await run_cmd(plugin, "sam's help")
    check("help 输出", "指令帮助" in texts(out))
    check("help 含极速达规则", "极速达" in texts(out) and "99" in texts(out))
    check("help 含全国配规则", "全国配" in texts(out) and "299" in texts(out))
    check("help 含满减说明", "每满 100 元" in texts(out))
    check("help 含代购费规则", "代购费" in texts(out))

    _, out = await run_cmd(plugin, "sam's menu")
    check("空菜单提示", "还没有商品分类" in texts(out))

    _, out = await run_cmd(plugin, "sam's add 水果 车厘子 智利车厘子 89.9 1.5")
    check("普通用户 add 被拒绝", "仅管理员" in texts(out))

    _, out = await run_cmd(
        plugin, "sam's add 水果 车厘子 智利车厘子 89.9 1.5", sender_id="admin1"
    )
    check("管理员 add 成功", "已添加商品" in texts(out))

    _, out = await run_cmd(
        plugin, "sam's add 水果 车厘子 蓝莓 29.9 0.5", sender_id="admin1"
    )
    check("管理员 add 第二个商品", "已添加商品" in texts(out))

    _, out = await run_cmd(
        plugin, "sam's add 水果 车厘子 坏果子 10", sender_id="admin1"
    )
    check("缺少重量时用默认重量", "已添加商品" in texts(out))

    _, out = await run_cmd(plugin, "sam's menu")
    check("menu 列出大分类", "水果" in texts(out))

    _, out = await run_cmd(plugin, "sam's menu 水果")
    check("menu 列出小分类", "车厘子" in texts(out))

    _, out = await run_cmd(plugin, "sam's menu 水果 车厘子")
    menu_text = texts(out)
    check("menu 列出商品与价格", "智利车厘子" in menu_text and "89.90" in menu_text)

    _, out = await run_cmd(plugin, "sam's buy 智利车厘子 2")
    check("buy 成功", "已加入购物车" in texts(out))

    _, out = await run_cmd(plugin, "sam's buy 蓝莓 3")
    check("buy 第二件商品", "已加入购物车" in texts(out))

    _, out = await run_cmd(plugin, "sam's buy 不存在的商品 1")
    check("buy 不存在商品提示", "未找到商品" in texts(out))

    _, out = await run_cmd(plugin, "sam's buy 蓝莓 0")
    check("buy 数量非法提示", "数量必须是正整数" in texts(out))

    _, out = await run_cmd(plugin, "sam's basket")
    basket_text = texts(out)
    check("basket 显示商品", "智利车厘子" in basket_text and "蓝莓" in basket_text)

    _, out = await run_cmd(plugin, "sam's basket delete")
    check("basket delete 提示序号", "序号" in texts(out))
    _, out = await run_cmd(plugin, "1")
    check("裸序号删除", "已删除" in texts(out))
    _, out = await run_cmd(plugin, "sam's basket")
    check("删除后只剩蓝莓", "蓝莓" in texts(out) and "智利车厘子" not in texts(out))

    _, out = await run_cmd(plugin, "sam's basket clear")
    check("clear 需要确认", "确定要清空" in texts(out))
    _, out = await run_cmd(plugin, "sam's basket")
    check("确认前未清空", "蓝莓" in texts(out))
    _, out = await run_cmd(plugin, "确认清空")
    check("确认后清空", "购物车已清空" in texts(out))

    await run_cmd(plugin, "sam's buy 智利车厘子 2")
    _, out = await run_cmd(plugin, "sam's pay")
    preview = texts(out)
    check("pay 预览含费用明细", "运费" in preview and "应付总额" in preview)
    check("pay 预览含确认提示", "确认支付" in preview)

    _, out = await run_cmd(plugin, "确认")
    types = [item.get("type") for item in out]
    check("确认后生成二维码图片", "image" in types, str(types))
    check("确认后创建订单", len(plugin.payment.created) == 1)
    if "image" in types:
        check("二维码文件存在", Path(out[types.index("image")]["path"]).exists())
    order = plugin.payment.created[0]
    check("下单后购物车清空", len(plugin.service.cart("u1")) == 0)

    plugin.payment.paid = False
    await plugin._check_pending_orders()
    check("未支付不通知", len(plugin.mailer.sent) == 0)

    plugin.payment.paid = True
    await plugin._check_pending_orders()
    eq("支付成功后发送一封邮件", len(plugin.mailer.sent), 1)
    subject, body = plugin.mailer.sent[0]
    check("邮件主题包含“有新的代购消息”", "有新的代购消息" in subject)
    for key in ("订单号", "商品明细", "配送方式", "运费", "应付总额", "支付时间"):
        check(f"邮件正文包含 {key}", key in body)
    eq("用户收到支付成功通知", len(ctx.sent), 1)

    await plugin._check_pending_orders()
    eq("重复轮询不重复发邮件", len(plugin.mailer.sent), 1)
    eq("重复轮询不重复通知用户", len(ctx.sent), 1)

    eq("订单已支付", plugin.service.get_order(order.order_id).status, ORDER_PAID)


# ----------------------------------------------------------------------
# 4. 支付失败
# ----------------------------------------------------------------------
async def test_payment_failure():
    plugin = make_plugin({"general": {"admins": ["admin1"]}}, "payfail")
    plugin.payment = FakePayment(ok=False, message="网关超时")
    plugin.mailer = FakeMailer()

    await run_cmd(plugin, "sam's add 水果 车厘子 智利车厘子 89.9 1.5", sender_id="admin1")
    await run_cmd(plugin, "sam's buy 智利车厘子 1")
    await run_cmd(plugin, "sam's pay")
    _, out = await run_cmd(plugin, "确认")
    check("支付失败给出提示", "生成收款二维码失败" in texts(out))
    eq("支付失败不发送邮件", len(plugin.mailer.sent), 0)
    eq("支付失败订单被取消", len(plugin.service.pending_orders()), 0)


# ----------------------------------------------------------------------
# 4.5 代购费指令流程
# ----------------------------------------------------------------------
async def test_proxy_fee_commands():
    plugin = make_plugin(
        {
            "general": {"admins": ["admin1"]},
            "fee": {"fee_mode": "per_item", "fee_per_item": 2, "fee_label": "跑腿费"},
        },
        "fee",
    )
    plugin.payment = FakePayment()
    plugin.mailer = FakeMailer()

    _, out = await run_cmd(plugin, "sam's help")
    check("help 说明代购费计费方式", "跑腿费" in texts(out) and "按件数" in texts(out))

    _, out = await run_cmd(
        plugin, "sam's add 水果 车厘子 车厘子 89.9 1.5 5", sender_id="admin1"
    )
    check("add 带单件代购费", "代购费" in texts(out))

    _, out = await run_cmd(
        plugin, "sam's add 水果 车厘子 蓝莓 29.9 0.5", sender_id="admin1"
    )
    check("add 不填代购费", "已添加商品" in texts(out))

    _, out = await run_cmd(plugin, "sam's menu 水果 车厘子")
    check("menu 显示单件代购费", "单件代购费" in texts(out))

    _, out = await run_cmd(plugin, "sam's buy 车厘子 2")
    _, out = await run_cmd(plugin, "sam's buy 蓝莓 3")

    _, out = await run_cmd(plugin, "sam's pay")
    preview = texts(out)
    check("pay 展示代购费费目", "跑腿费" in preview)
    check("pay 展示单件代购费计算", "5 元/件" in preview)
    check("pay 展示全局按件计算", "2.00 元/件" in preview)
    check("pay 展示代购费合计", "跑腿费合计" in preview)
    check("pay 展示应付总额", "应付总额" in preview)

    _, out = await run_cmd(plugin, "确认")
    check("下单成功", "已创建" in texts(out))
    orders = plugin.service.pending_orders()
    eq("下单数量", len(orders), 1)
    order = orders[0]
    eq("下单后代购费", f"{order.proxy_fee:.2f}", "16.00")
    expected_total = f"{order.goods_amount + order.freight + order.proxy_fee:.2f}"
    eq("下单后总额含代购费", f"{order.total:.2f}", expected_total)

    plugin.payment.paid = True
    await plugin._check_pending_orders()
    eq("支付成功发送邮件", len(plugin.mailer.sent), 1)
    subject, body = plugin.mailer.sent[0]
    check("邮件主题含代购消息", "有新的代购消息" in subject)
    check("邮件正文含代购费", "跑腿费" in body)
    check("邮件正文含代购费明细", "5 元/件" in body)


# ----------------------------------------------------------------------
# 5. 配置与指令解析
# ----------------------------------------------------------------------
def test_config():
    cfg = AppConfig.from_dict(
        {"general": {"wake_word": "山姆", "admins": ["a1", "a2"], "enable_national": False}}
    )
    eq("唤醒词解析", cfg.wake_word, "山姆")
    eq("管理员解析", cfg.admins, ("a1", "a2"))
    eq("启用渠道", cfg.enabled_channels(), ("express",))
    check("管理员判定", cfg.is_admin("a1") and not cfg.is_admin("u1"))

    try:
        AppConfig.from_dict({"general": {"default_channel": "rocket"}})
        check("非法配送方式应报错", False)
    except Exception:  # noqa: BLE001
        check("非法配送方式应报错", True)

    plugin = make_plugin({"general": {"wake_word": "山姆", "admins": []}}, "parse")
    eq("解析唤醒词", plugin._parse("山姆 menu")[0], "menu")
    eq("解析唤醒词带斜杠", plugin._parse("/山姆 menu")[0], "menu")
    eq("解析 @ 前缀", plugin._parse("@机器人 山姆 menu")[0], "menu")
    eq("解析唤醒词+sam's 写法", plugin._parse("山姆sam's menu")[0], "menu")
    eq("解析唤醒词空格 sam's 写法", plugin._parse("山姆 sam's menu")[0], "menu")
    eq("解析裸确认", plugin._parse("确认")[0], "confirm")
    eq("解析裸序号", plugin._parse("2")[0], "delete_index")
    eq("非指令返回 None", plugin._parse("今天天气怎么样"), None)
    eq("唤醒词后无空格不匹配", plugin._parse("山姆menu"), None)


async def main():
    test_freight()
    test_service()
    test_proxy_fee()
    test_proxy_fee_service()
    await test_commands()
    await test_payment_failure()
    await test_proxy_fee_commands()
    test_config()

    failed = [item for item in RESULTS if not item[1]]
    print()
    print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
    if failed:
        for name, _, detail in failed:
            print(f"  FAIL {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except Exception:
        traceback.print_exc()
        code = 2
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
