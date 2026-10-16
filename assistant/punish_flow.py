# -*- coding: utf-8 -*-
"""把风控验证页(punish/x5sec)拉到浏览器窗口里，用户过滑块后回收 cookie 并复测 token"""
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import shopctx
import xy_protocol as p

PORT = 9333
SESSION = ROOT / "session.json"
SHOT = None  # main 里按店铺写到该店 outbox（避免共享 Temp 目录权限冲突）


def http_json(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


async def cdp_call(ws, box, method, params=None):
    box[0] += 1
    mid = box[0]
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == mid:
            return msg


def token_probe():
    c = p.XianyuClient({}, None)
    c.load()
    dv = json.dumps({"appKey": p.IM_APP_KEY, "deviceId": c.device_id}, separators=(",", ":"))
    res = c._mtop("mtop.taobao.idlemessage.pc.login.token", "1.0", dv, retry=False)
    ret = res.get("ret") or []
    url = ((res.get("data") or {}).get("url") or "")
    return ret, url


def harvest(cookies):
    jar = {}
    for c in cookies:
        dom = c.get("domain") or ""
        if "goofish.com" in dom or "mmstat.com" in dom:
            jar[c["name"]] = c["value"]
    return jar


def save_session(jar):
    old = json.loads(SESSION.read_text(encoding="utf-8"))
    old["cookies"] = jar
    old["saved_at"] = time.time()
    SESSION.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")


async def main():
    global PORT, SESSION, SHOT
    env = shopctx.shop_env(shopctx.parse_shop())
    PORT, SESSION = env["debug_port"], env["session"]
    SHOT = env["outbox"] / "punish_page.png"
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    p.set_session_file(env["session"])
    ret, url = token_probe()
    print("PROBE:", json.dumps(ret, ensure_ascii=True), flush=True)
    if not url:
        print("没有 punish 链接，直接重测 token 看结果", flush=True)
        c = p.XianyuClient({}, None)
        c.load()
        dv = json.dumps({"appKey": p.IM_APP_KEY, "deviceId": c.device_id}, separators=(",", ":"))
        r2 = c._mtop("mtop.taobao.idlemessage.pc.login.token", "1.0", dv)
        print("RETRY:", json.dumps(r2.get("ret"), ensure_ascii=True), flush=True)
        return
    print("PUNISH_URL_LEN:", len(url), flush=True)
    page = None
    for t in http_json(f"http://127.0.0.1:{PORT}/json/list"):
        if t.get("type") == "page":
            page = t
            if "goofish" in (t.get("url") or ""):
                break
    import websockets
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as ws:
        box = [0]
        await cdp_call(ws, box, "Network.enable")
        await cdp_call(ws, box, "Page.enable")
        await cdp_call(ws, box, "Page.navigate", {"url": url})
        print("已把验证页拉到浏览器窗口，请查看并完成滑块验证", flush=True)
        deadline = time.time() + 360
        last_keys = ""
        shot_done = False
        while time.time() < deadline:
            await asyncio.sleep(3)
            res = await cdp_call(ws, box, "Network.getAllCookies")
            jar = harvest(res.get("result", {}).get("cookies", []))
            keys = ",".join(sorted(jar.keys()))
            if "x5sec" in jar and jar.get("x5sec") != last_keys:
                last_keys = jar["x5sec"]
                await asyncio.sleep(4)
                res = await cdp_call(ws, box, "Network.getAllCookies")
                jar = harvest(res.get("result", {}).get("cookies", []))
                save_session(jar)
                print("x5sec 已捕获，session.json 已更新，复测 token…", flush=True)
                c = p.XianyuClient({}, None)
                c.load()
                dv = json.dumps({"appKey": p.IM_APP_KEY, "deviceId": c.device_id}, separators=(",", ":"))
                r2 = c._mtop("mtop.taobao.idlemessage.pc.login.token", "1.0", dv)
                print("TOKEN_CHECK:", json.dumps(r2.get("ret"), ensure_ascii=True), flush=True)
                print("DONE", flush=True)
                return
            if not shot_done and time.time() > deadline - 340:
                r = await cdp_call(ws, box, "Page.captureScreenshot", {"format": "png"})
                import base64
                try:
                    SHOT.write_bytes(base64.b64decode(r["result"]["data"]))
                except Exception as e:
                    print("截图保存失败（忽略）:", e, flush=True)
                shot_done = True
                print("已截验证页图:", shot_done, flush=True)
        print("TIMEOUT: 5 分钟内没等到 x5sec", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
