"""本地 JSON 持久化。

插件重启后商品、购物车、订单状态不丢失。写入采用「临时文件 + 原子替换」，
避免写一半导致数据损坏。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .config import StorageConfig


class JsonFileStore:
    """带锁的 JSON 文件读写。"""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def read(self, default: Any = None) -> Any:
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except FileNotFoundError:
                return default
            except (json.JSONDecodeError, OSError):
                return default

    def write(self, data: Any) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.tmp.{os.getpid()}")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)


class Repository:
    """商品 / 购物车 / 订单的仓库。"""

    def __init__(self, data_dir: str | os.PathLike, storage: StorageConfig) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.products_file = Path(storage.products_path) if storage.products_path else self.data_dir / "products.json"
        self.orders_file = Path(storage.orders_path) if storage.orders_path else self.data_dir / "orders.json"
        self.carts_file = Path(storage.carts_path) if storage.carts_path else self.data_dir / "carts.json"

        self._products_store = JsonFileStore(self.products_file)
        self._orders_store = JsonFileStore(self.orders_file)
        self._carts_store = JsonFileStore(self.carts_file)

        products = self._products_store.read(None)
        if not isinstance(products, dict) or "categories" not in products:
            products = {"categories": {}}
        self._products = products

        carts = self._carts_store.read(None)
        self._carts = carts if isinstance(carts, dict) else {}

        orders = self._orders_store.read(None)
        self._orders = orders if isinstance(orders, dict) else {}

    # ---------- 商品 ----------
    @property
    def products(self) -> dict:
        return self._products

    def save_products(self) -> None:
        self._products_store.write(self._products)

    # ---------- 购物车 ----------
    @property
    def carts(self) -> dict:
        return self._carts

    def save_carts(self) -> None:
        self._carts_store.write(self._carts)

    # ---------- 订单 ----------
    @property
    def orders(self) -> dict:
        return self._orders

    def save_orders(self) -> None:
        self._orders_store.write(self._orders)
