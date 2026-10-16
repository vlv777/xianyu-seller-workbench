# -*- coding: utf-8 -*-
"""闲鱼助手 · 微信推送（PushPlus / Server酱）"""
import threading

import requests

import store


def _pushplus(token, title, content):
    r = requests.post(
        "https://www.pushplus.plus/send",
        json={"token": token, "title": title, "content": content, "template": "txt"},
        timeout=15,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("code") != 200:
        raise RuntimeError(f"pushplus 返回: {body}")
    return "pushplus ok"


def _serverchan(key, title, content):
    r = requests.post(
        f"https://sctapi.ftqq.com/{key}.send",
        data={"title": title, "desp": content},
        timeout=15,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("code") not in (0, "0"):
        raise RuntimeError(f"serverchan 返回: {body}")
    return "serverchan ok"


def push(config, title, content):
    token = (config.get("pushplus_token") or "").strip()
    key = (config.get("serverchan_key") or "").strip()
    if not token and not key:
        store.log("warn", f"未配置微信推送，消息未送达：{title}")
        return

    def run():
        for name, fn, arg in (("PushPlus", _pushplus, token), ("Server酱", _serverchan, key)):
            if not arg:
                continue
            try:
                result = fn(arg, title, content)
                store.log("info", f"微信推送成功({name}): {result}")
            except Exception as e:
                store.log("error", f"微信推送失败({name}): {e}")

    threading.Thread(target=run, daemon=True).start()
