# -*- coding: utf-8 -*-
"""闲鱼订单金额统计（直连卖家工作台接口，无需浏览器插件）

统计口径（与卖家工作台「订单管理」一致）：
  - 待发货：queryCode=NOT_SHIP 的订单，priceVO.totalPrice 合计
  - 已发货待到账：queryCode=SHIPPED 的订单，priceVO.totalPrice 合计

接口：mtop.taobao.idle.trade.merchant.sold.get（分页取明细）
坑：服务器会对响应启用 zstd 压缩（Python requests 不认），
    必须在请求头声明 Accept-Encoding: gzip 才会拿到可解析的响应。
"""
import json
import threading
import time

import xy_protocol as p

API = "mtop.taobao.idle.trade.merchant.sold.get"
VER = "1.0"
URL = f"https://h5api.m.goofish.com/h5/{API}/{VER}/"
ROWS = 50
CACHE_SECONDS = 120

_lock = threading.Lock()
_cache = {"ts": 0.0, "data": None}
_client = None
_client_file = None
_client_mtime = None


def _get_client():
    global _client, _client_file, _client_mtime
    cur = str(p.SESSION_FILE)
    try:
        mtime = p.SESSION_FILE.stat().st_mtime
    except Exception:
        mtime = 0
    if _client is None or _client_file != cur or mtime != _client_mtime:
        c = p.XianyuClient({}, None)
        if not c.load():
            raise RuntimeError("未登录（找不到有效登录态）")
        _client = c
        _client_file = cur
        _client_mtime = mtime
    return _client


def _token(client):
    for ck in client.session.cookies:
        if ck.name == "_m_h5_tk":
            return ck.value.split("_")[0]
    return ""


def _fetch_page(client, query_code, page):
    data_val = json.dumps({"pageNumber": page, "rowsPerPage": ROWS, "orderIds": "",
                           "queryCode": query_code, "orderSearchParam": "{}"},
                          separators=(",", ":"))
    j = {"ret": ["FAIL"]}
    for attempt in (1, 2):
        token = _token(client)
        t = str(int(time.time() * 1000))
        sign = p.generate_sign(t, token, data_val)
        params = {"jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign, "v": VER,
                  "type": "json", "accountSite": "xianyu", "dataType": "json",
                  "timeout": "20000", "api": API, "valueType": "string",
                  "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.home.0.0"}
        h = dict(p.MTOP_HEADERS)
        h["Accept-Encoding"] = "gzip"  # 关键：不声明则服务器回 zstd，解析不了
        r = client.session.post(URL, params=params, data={"data": data_val},
                                headers=h, timeout=20)
        j = r.json()
        ret = str(j.get("ret") or "")
        if ("令牌过期" in ret or "TOKEN_EXPIRED" in ret or "TOKEN_EXOIRED" in ret) and attempt == 1:
            continue  # 响应已带新的 _m_h5_tk，重取 token 再试一次
        return j
    return j


def _sum_status(client, query_code):
    total, count, page = 0.0, 0, 1
    while page <= 40:
        j = _fetch_page(client, query_code, page)
        if "SUCCESS" not in str(j.get("ret")):
            raise RuntimeError("接口返回: " + str(j.get("ret"))[:80])
        items = ((j.get("data") or {}).get("module") or {}).get("items") or []
        if not items:
            break
        for it in items:
            pv = it.get("priceVO") or {}
            total += float(pv.get("totalPrice") or 0)
            count += 1
        if len(items) < ROWS:
            break
        page += 1
    return count, round(total, 2)


def fetch(force=False):
    """返回 {pending_count, pending_amount, shipped_count, shipped_amount, fetched_at, cached}"""
    now = time.time()
    with _lock:
        if not force and _cache["data"] and now - _cache["ts"] < CACHE_SECONDS:
            d = dict(_cache["data"])
            d["cached"] = True
            return d
        client = _get_client()
        pc, pa = _sum_status(client, "NOT_SHIP")
        sc, sa = _sum_status(client, "SHIPPED")
        data = {"pending_count": pc, "pending_amount": pa,
                "shipped_count": sc, "shipped_amount": sa,
                "fetched_at": now, "cached": False}
        _cache["ts"], _cache["data"] = now, data
        return dict(data)
