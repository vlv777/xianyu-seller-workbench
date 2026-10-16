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
    # 取"最新"的 _m_h5_tk（按值后缀时间戳），不能拿 jar 里第一个匹配——
    # 旧令牌会导致 FAIL_SYS_TOKEN_ILLEGAL
    try:
        return client._h5_token()
    except Exception:
        return ""


def _clear_tokens(client):
    """清掉所有 _m_h5_tk/_m_h5_tk_enc（含 domain 为空的僵尸副本）。

    坑：会话里残留的旧 _m_h5_tk_enc 会参与服务端令牌配对校验，
    导致新领的令牌一律被判 ILLEGAL——必须先清干净再重新握手。
    """
    try:
        for ck in list(client.session.cookies):
            if ck.name.startswith("_m_h5_tk"):
                try:
                    client.session.cookies.clear(ck.domain, ck.path, ck.name)
                except Exception:
                    pass
    except Exception:
        pass


def _fetch_page(client, query_code, page, rows=ROWS):
    data_val = json.dumps({"pageNumber": page, "rowsPerPage": rows, "orderIds": "",
                           "queryCode": query_code, "orderSearchParam": "{}"},
                          separators=(",", ":"))
    j = {"ret": ["FAIL"]}
    for attempt in range(5):
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
        token_bad = ("TOKEN_EMPTY" in ret or "TOKEN_ILLEGAL" in ret
                     or "令牌为空" in ret or "非法令牌" in ret or "令牌过期" in ret
                     or "TOKEN_EXPIRED" in ret or "TOKEN_EXOIRED" in ret)
        if not token_bad:
            return j
        if attempt >= 4:
            break
        # 非法/过期：清掉整套旧令牌（含僵尸 _enc），下一发空手领新令再发
        if ("TOKEN_ILLEGAL" in ret or "非法令牌" in ret
                or "令牌过期" in ret or "TOKEN_EXPIRED" in ret or "TOKEN_EXOIRED" in ret):
            _clear_tokens(client)
        time.sleep(0.8)
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


ORDER_CODES = ("ALL", "NOT_PAY", "NOT_SHIP", "SHIPPED", "REFUND", "TRADE_CLOSED", "TRADE_SUCCESS")


def fetch_orders(page=1, size=20, status="ALL"):
    """订单列表（供进销存「拉闲鱼订单」用）。字段与旧 Node 实现保持一致。

    返回 {total, nextPage, orders:[{orderId,status,createTime,payTime,title,spec,
    price,totalPrice,postFee,buyNum,buyerNick,inRefund}]}
    """
    page = max(1, int(page or 1))
    size = min(100, max(1, int(size or 20)))
    code = status if status in ORDER_CODES else "ALL"
    client = _get_client()
    j = _fetch_page(client, code, page, rows=size)
    if "SUCCESS" not in str(j.get("ret")):
        raise RuntimeError("接口返回: " + str(j.get("ret"))[:120])
    mod = ((j.get("data") or {}).get("module")) or {}
    items = mod.get("items") or []
    orders = []
    for it in items:
        cd = it.get("commonData") or {}
        iv = it.get("itemVO") or {}
        pv = it.get("priceVO") or {}
        bv = it.get("buyerInfoVO") or {}
        spec = " ".join(
            ("%s%s" % (l.get("key") or "", l.get("value") or "")).strip()
            for l in (iv.get("itemInfoLines") or [])
        ).strip()
        orders.append({
            "orderId": str(cd.get("orderId") or ""),
            "status": str(cd.get("orderStatus") or ""),
            "createTime": str(cd.get("createTime") or ""),
            "payTime": str(cd.get("paySuccessTime") or ""),
            "title": str(iv.get("title") or ""),
            "spec": spec,
            "price": float(pv.get("auctionPrice") or 0),
            "totalPrice": float(pv.get("totalPrice") or 0),
            "postFee": float(pv.get("postFee") or 0),
            "buyNum": int(pv.get("buyNum") or 1),
            "buyerNick": str(bv.get("userNick") or ""),
            "inRefund": bool(cd.get("inRefund")),
        })
    return {"total": int(mod.get("totalCount") or 0),
            "nextPage": mod.get("nextPage") is True,
            "orders": orders}
