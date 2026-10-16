# -*- coding: utf-8 -*-
"""闲鱼助手 · 多店铺上下文：--shop 解析 / 店目录定位 / 店铺枚举"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHOPS_DIR = ROOT / "shops"


def parse_shop(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--shop", default="")
    args, _ = ap.parse_known_args(argv)
    return args.shop.strip()


def data_dir(shop):
    if not shop:
        raise SystemExit("未指定 --shop 店铺名")
    d = SHOPS_DIR / shop
    if not d.is_dir():
        raise SystemExit(f"店铺不存在：{d}（先用『店铺管理』新建店铺）")
    return d


def load_config(shop):
    return json.loads((data_dir(shop) / "config.json").read_text(encoding="utf-8"))


def all_shops():
    if not SHOPS_DIR.is_dir():
        return []
    return sorted(p.name for p in SHOPS_DIR.iterdir()
                  if p.is_dir() and (p / "config.json").exists())


def shop_env(shop):
    """常用路径/参数集合，供 heal / 登录工具使用。"""
    d = data_dir(shop)
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    return {
        "shop": shop,
        "data": d,
        "config": cfg,
        "port": int(cfg.get("port", 8767)),
        "debug_port": int(cfg.get("debug_port", 9333)),
        "profile": d / "chrome-profile",
        "session": d / "session.json",
        "db": d / "assistant.db",
        "log": d / "heal.log",
        "outbox": d / "outbox",
    }
