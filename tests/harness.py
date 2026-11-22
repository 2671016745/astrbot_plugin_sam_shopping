"""测试环境搭建：模拟 AstrBot 的 data.plugins.<name>.main 导入方式。"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = TESTS_DIR.parent
STUBS_DIR = TESTS_DIR / "stubs"
PKG_NAME = "astrbot_plugin_sam_shopping"
FULL_PKG = f"data.plugins.{PKG_NAME}"


def prepare(tmp_root: Path) -> Path:
    """把插件目录复制成 data/plugins/<name>，返回 data 目录。"""
    data_dir = tmp_root / "data"
    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugins_dir / "__init__.py").write_text("", encoding="utf-8")

    target = plugins_dir / PKG_NAME
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in PLUGIN_DIR.iterdir():
        if item.name in {"tests", "__pycache__", ".git"}:
            continue
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, dest)
    return data_dir


def load_plugin(tmp_root: Path):
    data_dir = prepare(tmp_root)
    for path in (str(STUBS_DIR), str(tmp_root)):
        if path not in sys.path:
            sys.path.insert(0, path)
    importlib.invalidate_caches()
    return importlib.import_module(f"{FULL_PKG}.main")
