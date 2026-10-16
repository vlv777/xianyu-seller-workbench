# -*- coding: utf-8 -*-
"""闲鱼助手 · 协议工具：签名 / ID 生成 / cookie / 消息解码"""
import base64
import hashlib
import json
import random
import time

import msgpack


def generate_mid():
    return f"{int(1000 * random.random())}{int(time.time() * 1000)} 0"


def generate_uuid():
    return f"-{int(time.time() * 1000)}1"


def generate_device_id(user_id):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = []
    for i in range(36):
        if i in (8, 13, 18, 23):
            out.append("-")
        elif i == 14:
            out.append("4")
        elif i == 19:
            out.append(chars[(int(16 * random.random()) & 0x3) | 0x8])
        else:
            out.append(chars[int(16 * random.random())])
    return "".join(out) + "-" + user_id


def generate_sign(t, token, data):
    msg = f"{token}&{t}&34839810&{data}"
    return hashlib.md5(msg.encode("utf-8")).hexdigest()


def trans_cookies(cookies_str):
    cookies = {}
    for item in str(cookies_str or "").split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def cookies_to_str(cookies):
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k)


def _normalize(value):
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _decode_bytes(raw):
    stripped = raw.lstrip()
    if stripped[:1] in (b"{", b"["):
        try:
            value = json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(value, dict):
                return _normalize(value)
        except Exception:
            pass
    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
    unpacker.feed(raw)
    first = None
    for value in unpacker:
        if first is None:
            first = value
        else:
            break
    if first is None:
        raise ValueError("空数据")
    if isinstance(first, bytes):
        first = first.decode("utf-8", errors="ignore")
    if isinstance(first, str):
        return json.loads(first)
    return _normalize(first)


def decode_message_data(data):
    """syncPushPackage 里的 data：JSON 或 base64(JSON/MessagePack)，统一解成 dict。"""
    if isinstance(data, dict):
        return data
    if isinstance(data, (bytes, bytearray)):
        return _decode_bytes(bytes(data))
    text = str(data or "")
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    raw = base64.b64decode(text + "=" * (-len(text) % 4))
    return _decode_bytes(raw)


def is_chat_message(data):
    try:
        return (
            isinstance(data, dict)
            and "1" in data
            and isinstance(data["1"], dict)
            and "10" in data["1"]
            and isinstance(data["1"]["10"], dict)
            and "reminderContent" in data["1"]["10"]
        )
    except Exception:
        return False
