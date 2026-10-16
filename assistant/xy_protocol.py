# -*- coding: utf-8 -*-
"""闲鱼助手 · 协议客户端：扫码登录 / MTOP / WebSocket 收发"""
import asyncio
import base64
import contextlib
import json
import time
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
import websockets

import store
from xy_utils import (cookies_to_str, decode_message_data, generate_device_id,
                      generate_mid, generate_sign, generate_uuid, is_chat_message)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
UA_DING = UA + " DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/147.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5"
WS_URL = "wss://wss-goofish.dingtalk.com/"
IM_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
SESSION_FILE = Path(__file__).resolve().parent / "session.json"


def set_session_file(path):
    global SESSION_FILE
    SESSION_FILE = Path(path)

MTOP_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7,ja;q=0.6",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.goofish.com",
    "Referer": "https://www.goofish.com/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "priority": "u=1, i",
}

PASSPORT_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7,ja;q=0.6",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}


def _initial_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    try:
        s.get("https://log.mmstat.com/eg.js", timeout=10)
    except Exception:
        pass
    cna = s.cookies.get("cna", domain=".mmstat.com")
    if cna:
        s.cookies.set("cna", cna, domain=".goofish.com", path="/")
    for api in ("mtop.taobao.idlehome.home.webpc.feed",
                "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get"):
        try:
            s.post(
                f"https://h5api.m.goofish.com/h5/{api}/1.0/",
                params={"jsv": "2.7.2", "appKey": "34839810",
                        "t": str(int(time.time() * 1000)), "sign": "", "v": "1.0",
                        "type": "originaljson", "dataType": "json", "timeout": "20000",
                        "api": api, "sessionOption": "AutoLoginOnly",
                        "spm_cnt": "a21ybx.home.0.0"},
                data="data=%7B%7D", headers=MTOP_HEADERS, timeout=10,
            )
        except Exception:
            pass
    return s


class AuthError(Exception):
    """登录态失效 / 风控验证（需要重登或过滑块），用于拉长重试间隔。"""


class QrLogin:
    """纯 HTTP 扫码登录，供网页面板轮询驱动。"""

    def __init__(self, session_file=None):
        self.session_file = Path(session_file or SESSION_FILE)
        self.s = None
        self.qr_url = ""
        self.status = "idle"
        self.message = "未开始"
        self.account = None
        self._qr_t = None
        self._qr_ck = None
        self._csrf = ""
        self._cookie2 = ""
        self._cna = ""

    def _query_base(self):
        return {
            "appName": "xianyu", "fromSite": "77", "appEntrance": "web",
            "_csrf_token": self._csrf, "umidToken": "", "hsiz": self._cookie2,
            "bizParams": f"taobaoBizLoginFrom=web&renderRefer={quote('https://www.goofish.com/')}",
            "mainPage": "false", "isMobile": "false", "lang": "zh_CN",
            "returnUrl": "", "umidTag": "SERVER", "navlanguage": "en",
            "navUserAgent": UA, "navPlatform": "Win32", "isIframe": "true",
            "documentReferer": "https://www.goofish.com/", "defaultView": "sms",
            "deviceId": self._cna,
        }

    def start(self):
        self.status = "starting"
        self.message = "正在生成二维码…"
        self.s = _initial_session()
        self._cna = (self.s.cookies.get("cna", domain=".goofish.com")
                     or self.s.cookies.get("cna", domain=".mmstat.com") or "")
        self._cookie2 = self.s.cookies.get("cookie2", domain=".goofish.com") or ""
        self.s.get(
            "https://passport.goofish.com/mini_login.htm",
            params={"lang": "zh_cn", "appName": "xianyu", "appEntrance": "web",
                    "styleType": "vertical", "bizParams": "", "notLoadSsoView": "false",
                    "notKeepLogin": "false", "isMobile": "false", "qrCodeFirst": "false",
                    "stie": "77", "rnd": "0.6842814084442211"},
            headers={**PASSPORT_HEADERS, "Referer": "https://www.goofish.com/",
                     "sec-fetch-site": "same-site", "sec-fetch-dest": "iframe",
                     "sec-fetch-mode": "navigate"},
            timeout=15,
        )
        self._csrf = self.s.cookies.get("XSRF-TOKEN", domain="passport.goofish.com") or ""
        resp = self.s.get(
            "https://passport.goofish.com/newlogin/qrcode/generate.do",
            params=self._query_base(),
            headers={**PASSPORT_HEADERS, "Referer": "https://passport.goofish.com/mini_login.htm"},
            timeout=10,
        ).json()
        data = (resp.get("content") or {}).get("data") or {}
        url, t, ck = data.get("codeContent"), data.get("t"), data.get("ck")
        if not (url and t and ck):
            raise RuntimeError(f"二维码生成失败: {resp}")
        self.qr_url, self._qr_t, self._qr_ck = url, t, ck
        self.status = "NEW"
        self.message = "等待扫码"
        return url

    def poll(self):
        if not self._qr_t:
            return self.status
        try:
            body = {**self._query_base(), "t": str(self._qr_t), "ck": self._qr_ck}
            resp = self.s.post(
                "https://passport.goofish.com/newlogin/qrcode/query.do?appName=xianyu&fromSite=77",
                data=body,
                headers={**PASSPORT_HEADERS,
                         "Content-Type": "application/x-www-form-urlencoded",
                         "Origin": "https://passport.goofish.com",
                         "Referer": "https://passport.goofish.com/mini_login.htm"},
                timeout=10,
            )
            qdata = (resp.json().get("content") or {}).get("data") or {}
            status = qdata.get("qrCodeStatus", "")
        except Exception as e:
            self.status = "error"
            self.message = f"轮询异常: {e}"
            return self.status
        mapping = {"NEW": "等待扫码", "SCANNED": "已扫码，请在手机上确认",
                   "EXPIRED": "二维码已过期，请重新生成"}
        if status in mapping:
            self.status = status
            self.message = mapping[status]
        if status == "EXPIRED":
            self._qr_t = None
            return self.status
        if status == "CONFIRMED":
            try:
                login_token = qdata.get("token") or qdata.get("lgToken")
                if login_token:
                    self.s.post(
                        "https://passport.goofish.com/login_token/login.do",
                        params={"token": login_token, "subFlow": "DIALOG_CHECK_LOGIN_RPC",
                                "nextCode": "0018", "bizScene": "qrcode", "confirm": "true"},
                        data={"deviceId": self._cna},
                        headers={**PASSPORT_HEADERS,
                                 "Content-Type": "application/x-www-form-urlencoded",
                                 "Origin": "https://passport.goofish.com",
                                 "Referer": "https://passport.goofish.com/mini_login.htm"},
                        timeout=10,
                    )
                self._finish()
            except Exception as e:
                self.status = "error"
                self.message = f"登录收尾失败: {e}"
        return self.status

    def _finish(self):
        self.s.post(
            "https://h5api.m.goofish.com/h5/mtop.idle.web.user.page.nav/1.0/",
            params={"jsv": "2.7.2", "appKey": "34839810",
                    "t": str(int(time.time() * 1000)), "sign": "", "v": "1.0",
                    "type": "originaljson", "dataType": "json", "timeout": "20000",
                    "api": "mtop.idle.web.user.page.nav",
                    "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.home.0.0"},
            data="data=%7B%7D", headers=MTOP_HEADERS, timeout=10,
        )
        unb = self.s.cookies.get("unb", domain=".goofish.com") or ""
        tracknick = self.s.cookies.get("tracknick", domain=".goofish.com") or ""
        if not unb:
            raise RuntimeError("未拿到 unb cookie，扫码登录失败")
        cookies = {}
        for c in self.s.cookies:
            if c.domain and (".goofish.com" in c.domain or ".mmstat.com" in c.domain):
                cookies[c.name] = c.value
        data = {"cookies": cookies, "unb": unb, "tracknick": tracknick,
                "device_id": generate_device_id(unb), "saved_at": time.time()}
        self.session_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.account = {"unb": unb, "tracknick": tracknick}
        self.status = "CONFIRMED"
        self.message = f"登录成功：{tracknick or unb}"
        store.log("info", f"扫码登录成功 unb={unb} nick={tracknick}")
        self._qr_t = None

    def qr_png(self):
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(self.qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class XianyuClient:
    def __init__(self, config, on_message, session_file=None):
        self.config = config
        self.on_message = on_message
        self.session_file = Path(session_file or SESSION_FILE)
        self.loop = None
        self.ws = None
        self.session = None
        self.cookies = {}
        self.myid = ""
        self.nick = ""
        self.device_id = ""
        self.status = "未登录"
        self._stop = False
        self._recent = OrderedDict()
        self._pending_sends = {}
        self._late_sends = OrderedDict()
        self._self_sent_recent = OrderedDict()
        self.on_send_rejected = None
        self.on_auth_failed = None
        self._auth_notified = False
        self._connected_at = 0

    def load(self):
        if not self.session_file.exists():
            self.status = "未登录"
            return False
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except Exception as e:
            store.log("error", f"会话文件损坏: {e}")
            self.status = "未登录"
            return False
        self.cookies = data.get("cookies") or {}
        self.myid = str(data.get("unb") or "")
        self.nick = str(data.get("tracknick") or "")
        self.device_id = data.get("device_id") or generate_device_id(self.myid)
        if not (self.cookies and self.myid):
            self.status = "未登录"
            return False
        self.session = requests.Session()
        self.session.cookies.update(self.cookies)
        self.status = "离线"
        return True

    def _h5_token(self):
        best, best_ts = "", -1
        for c in self.session.cookies:
            if c.name == "_m_h5_tk":
                try:
                    ts = int(str(c.value).rsplit("_", 1)[1])
                except Exception:
                    ts = 0
                if ts > best_ts:
                    best_ts, best = ts, str(c.value)
        return best.split("_")[0] if best else ""

    def _dedupe_h5(self):
        keep, keep_ts = None, -1
        for c in self.session.cookies:
            if c.name == "_m_h5_tk":
                try:
                    ts = int(str(c.value).rsplit("_", 1)[1])
                except Exception:
                    ts = 0
                if ts > keep_ts:
                    keep_ts, keep = ts, c
        if not keep:
            return
        for c in list(self.session.cookies):
            if c.name == "_m_h5_tk" and not (c.domain == keep.domain and c.path == keep.path):
                with contextlib.suppress(Exception):
                    self.session.cookies.clear(c.domain, c.path, c.name)

    # ── MTOP ────────────────────────────────────────────────
    def _mtop(self, api, version, data_val, extra_params=None, retry=True):
        token = self._h5_token()
        t = str(int(time.time() * 1000))
        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t,
            "sign": generate_sign(t, token, data_val), "v": version,
            "type": "originaljson", "accountSite": "xianyu", "dataType": "json",
            "timeout": "20000", "api": api, "sessionOption": "AutoLoginOnly",
            "spm_cnt": "a21ybx.im.0.0",
        }
        if extra_params:
            params.update(extra_params)
        r = self.session.post(
            f"https://h5api.m.goofish.com/h5/{api}/{version}/",
            params=params, data={"data": data_val}, headers=MTOP_HEADERS, timeout=20,
        )
        res = r.json()
        self._dedupe_h5()
        ret = str(res.get("ret") or "")
        if retry and ("令牌过期" in ret or "TOKEN_EXPIRED" in ret or "TOKEN_EXOIRED" in ret):
            time.sleep(1.2)
            return self._mtop(api, version, data_val, extra_params, retry=False)
        return res

    def fetch_token(self):
        data_val = json.dumps({"appKey": IM_APP_KEY, "deviceId": self.device_id},
                              separators=(",", ":"))
        res = self._mtop("mtop.taobao.idlemessage.pc.login.token", "1.0", data_val)
        return str(((res.get("data") or {}).get("accessToken")) or "")

    def refresh_session(self):
        """保活：刷新 cookie / 登录态。返回 True 表示仍有效。"""
        res = self._mtop("mtop.taobao.idlemessage.pc.loginuser.get", "1.0", "{}")
        ret = str(res.get("ret") or "")
        if "SUCCESS" in ret or (res.get("data") is not None):
            self.cookies = self.session.cookies.get_dict()
            data = {"cookies": self.cookies, "unb": self.myid, "tracknick": self.nick,
                    "device_id": self.device_id, "saved_at": time.time()}
            self.session_file.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
            return True
        return False

    # ── WebSocket ───────────────────────────────────────────
    async def run_forever(self):
        self.loop = asyncio.get_running_loop()
        backoff = 5
        while not self._stop:
            try:
                await self._connect_once()
                backoff = 5
            except asyncio.CancelledError:
                raise
            except AuthError as e:
                self.status = "登录失效"
                delay = 1800
                with contextlib.suppress(Exception):
                    delay = int(self.config.get("auth_retry_seconds") or 1800)
                store.log("warn", f"登录失效：{e}；{delay // 60} 分钟后再试（避免频繁请求加重风控）")
                if not self._auth_notified:
                    self._auth_notified = True
                    cb = self.on_auth_failed
                    if cb:
                        try:
                            cb(str(e))
                        except Exception:
                            pass
                await asyncio.sleep(delay)
                backoff = 5
            except Exception as e:
                self.status = "离线"
                store.log("warn", f"消息通道断开：{e}，{backoff}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _connect_once(self):
        self.status = "连接中"
        token = await asyncio.to_thread(self.fetch_token)
        if not token:
            self.status = "登录失效"
            raise AuthError("token 获取失败（可能需要重新扫码登录/过滑块）")
        headers = {
            "Cookie": cookies_to_str(self.cookies),
            "Host": "wss-goofish.dingtalk.com",
            "Connection": "Upgrade",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "User-Agent": UA,
            "Origin": "https://www.goofish.com",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with websockets.connect(
            WS_URL, additional_headers=headers, max_size=16 * 1024 * 1024,
            ping_interval=None, close_timeout=5,
        ) as ws:
            self.ws = ws
            self._connected_at = time.time()
            await self._reg(token)
            await asyncio.sleep(1)
            await self._ack_diff()
            hb = asyncio.create_task(self._heartbeat())
            refresh = asyncio.create_task(self._refresh_loop())
            self.status = "在线"
            self._auth_notified = False
            store.log("info", f"闲鱼消息通道已连接（{self.nick or self.myid}）")
            try:
                async for raw in ws:
                    await self._on_raw(raw)
            finally:
                hb.cancel()
                refresh.cancel()
                self.ws = None

    async def _reg(self, token):
        msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": IM_APP_KEY,
                "token": token,
                "ua": UA_DING,
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid(),
            },
        }
        await self.ws.send(json.dumps(msg))

    async def _ack_diff(self):
        now = int(time.time() * 1000)
        msg = {
            "lwp": "/r/SyncStatus/ackDiff",
            "headers": {"mid": generate_mid()},
            "body": [{"pipeline": "sync", "tooLong2Tag": "PNM,1", "channel": "sync",
                      "topic": "sync", "highPts": 0, "pts": now * 1000, "seq": 0,
                      "timestamp": now}],
        }
        await self.ws.send(json.dumps(msg))

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(15)
            try:
                await self.ws.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
            except Exception:
                return

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(1800)
            try:
                ok = await asyncio.to_thread(self.refresh_session)
                if ok:
                    store.log("info", "登录态保活成功")
                else:
                    store.log("warn", "登录态保活失败，可能需重新扫码")
                    self.status = "登录失效"
            except Exception as e:
                store.log("warn", f"保活异常: {e}")

    async def _on_raw(self, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            store.log("warn", f"[WS] 无法解析帧: {str(raw)[:120]}")
            return
        headers = msg.get("headers") or {}
        body = msg.get("body")
        lwp = msg.get("lwp") or ""
        mid = headers.get("mid")
        is_reject = isinstance(body, dict) and bool(body.get("reason"))
        resolved_mid = None
        if mid:
            fut = self._pending_sends.get(mid)
            if fut is not None and not fut.done():
                fut.set_result(msg)
                resolved_mid = mid
        if resolved_mid is None and is_reject:
            for pm in list(self._pending_sends.keys()):
                fut = self._pending_sends.get(pm)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                    resolved_mid = pm
                    break
        if resolved_mid is not None:
            self._late_sends.pop(resolved_mid, None)
        elif is_reject:
            if self._late_sends:
                last_mid, info = next(reversed(self._late_sends.items()))
                self._late_sends.pop(last_mid, None)
                store.log("warn", f"[WS] 迟到拦截回执，匹配到最近一条发送：{info['text'][:40]}")
                cb = self.on_send_rejected
                if cb:
                    try:
                        result = cb(info["cid"], info["text"], str(body.get("reason") or ""))
                        if asyncio.iscoroutine(result):
                            asyncio.create_task(result)
                    except Exception:
                        pass
        if lwp and lwp != "/!":
            store.log("debug", f"[WS] lwp={lwp} body={str(body)[:160] if body is not None else '-'}")
        elif body is not None and not lwp:
            store.log("debug", f"[WS] 无lwp帧 body={str(body)[:160]}")
        ack = {"code": 200, "headers": {"mid": headers.get("mid") or generate_mid(),
                                        "sid": headers.get("sid", "")}}
        for k in ("app-key", "ua", "dt"):
            if k in headers:
                ack["headers"][k] = headers[k]
        with contextlib.suppress(Exception):
            await self.ws.send(json.dumps(ack))
        if lwp == "/s/vulcan":
            with contextlib.suppress(Exception):
                await self._ack_diff()
        for item in (body or {}).get("syncPushPackage", {}).get("data") or []:
            try:
                data = decode_message_data(item.get("data"))
            except Exception as e:
                store.log("error", f"[WS] 消息解码失败: {e}")
                continue
            if is_chat_message(data):
                m10 = data["1"]["10"]
                store.log("debug", f"[WS] 聊天包 sender={m10.get('senderUserId')} text={str(m10.get('reminderContent'))[:50]}")
            elif not (isinstance(data, dict) and ("chatType" in data or "bizId" in data or "1" in data)):
                keys = list(data.keys())[:6] if isinstance(data, dict) else type(data).__name__
                store.log("debug", f"[WS] 其他包: {keys}")
            await self._process(data)

    async def _process(self, data):
        if not is_chat_message(data):
            return
        m1 = data["1"]
        m10 = m1["10"]
        sender = str(m10.get("senderUserId") or "")
        if not sender:
            return
        is_self = sender == self.myid
        biz = str(m10.get("bizTag") or "")
        if "taskName" in biz or "SECURITY" in biz or "taskId" in biz:
            store.log("debug", "[WS] 跳过系统消息")
            return
        text = str(m10.get("reminderContent") or "").strip()
        image_url = ""
        try:
            ext = m1.get("6") or {}
            content = ext.get("3") or {}
            if str(content.get("4") or "") == "2":
                payload = json.loads(str(content.get("5") or "{}"))
                if int(payload.get("contentType") or 0) == 2:
                    pics = ((payload.get("image") or {}).get("pics") or [])
                    if pics:
                        image_url = str(pics[0].get("url") or "")
        except Exception:
            image_url = ""
        if text == "[图片]" and not image_url:
            try:
                dd = Path(__file__).resolve().parent / "outbox" / "img_dump"
                dd.mkdir(parents=True, exist_ok=True)
                (dd / f"img_{int(time.time() * 1000)}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                store.log("debug", "[WS] 图片帧解析失败，原始帧已 dump 到 outbox/img_dump")
            except Exception:
                pass
        if not text:
            store.log("debug", "[WS] 跳过空文本消息")
            return
        ts_ms = int(m1.get("5") or 0)
        if ts_ms and ts_ms < int((self._connected_at - 180) * 1000):
            store.log("debug", f"[WS] 跳过历史消息（{int((self._connected_at - ts_ms / 1000))}s 前）")
            return
        cid = str(m1.get("2") or "").split("@")[0]
        if not cid:
            return
        nick = str(m10.get("senderNick") or m10.get("reminderTitle") or "").strip()
        key = f"{cid}|{ts_ms}|{sender}|{text[:80]}"
        if key in self._recent:
            return
        self._recent[key] = True
        while len(self._recent) > 500:
            self._recent.popitem(last=False)
        if is_self:
            self._handle_self_message(cid, text, ts_ms)
            return
        await self.on_message({"cid": cid, "buyer_id": sender, "nick": nick,
                               "text": text, "image_url": image_url,
                               "ts": ts_ms / 1000 if ts_ms else time.time()})

    def _remember_self_send(self, cid, text):
        """记录本进程刚发出的消息，用于过滤服务端回声，避免重复归档。"""
        self._self_sent_recent[(cid, str(text))] = time.time()
        while len(self._self_sent_recent) > 200:
            self._self_sent_recent.popitem(last=False)

    def _handle_self_message(self, cid, text, ts_ms):
        """本账号在手机/网页端发出的消息：归档为 out/human，不触发自动回复。"""
        now = time.time()
        sent_at = self._self_sent_recent.get((cid, str(text)))
        if sent_at and now - sent_at < 180:
            return
        ts = ts_ms / 1000 if ts_ms else now
        try:
            if store.add_message(cid, "out", "human", text, ts):
                store.upsert_conversation(cid, last_text=text, last_ts=ts)
                store.log("info", f"[WS] 记录手机侧消息：{text[:40]}")
        except Exception as e:
            store.log("error", f"[WS] 手机侧消息归档失败：{e}")

    async def send_text(self, cid, toid, text):
        if not self.ws:
            raise RuntimeError("消息通道未连接")
        mid = generate_mid()
        payload = {"contentType": 1, "text": {"text": text}}
        b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {"mid": mid},
            "body": [
                {"uuid": generate_uuid(), "cid": f"{cid}@goofish", "conversationType": 1,
                 "content": {"contentType": 101, "custom": {"type": 1, "data": b64}},
                 "redPointPolicy": 0, "extension": {"extJson": "{}"},
                 "ctx": {"appVersion": "1.0", "platform": "web"},
                 "mtags": {}, "msgReadStatusSetting": 1},
                {"actualReceivers": [f"{toid}@goofish", f"{self.myid}@goofish"]},
            ],
        }
        fut = None
        if self.loop and self.loop.is_running():
            fut = self.loop.create_future()
            self._pending_sends[mid] = fut
        now = time.time()
        for key in [k for k, v in self._late_sends.items() if now - v["ts"] > 180]:
            self._late_sends.pop(key, None)
        self._late_sends[mid] = {"cid": cid, "toid": toid, "text": text, "ts": now}
        self._remember_self_send(cid, text)
        await self.ws.send(json.dumps(msg))
        if fut is None:
            return True, "已发送（未跟踪回执）"
        try:
            resp = await asyncio.wait_for(fut, timeout=8)
        except asyncio.TimeoutError:
            return True, "无回执（保留 3 分钟核对，迟到拦截会自动纠正）"
        finally:
            self._pending_sends.pop(mid, None)
        rbody = (resp or {}).get("body") or {}
        code = str(rbody.get("code", "0") or "0")
        reason = str(rbody.get("reason") or rbody.get("message") or "")
        store.log("debug", f"[WS] 发送回执: code={code} body={str(rbody)[:150]}")
        if reason or code not in ("0", "200"):
            return False, reason or f"code={code}"
        return True, ""
