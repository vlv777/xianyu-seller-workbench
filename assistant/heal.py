# -*- coding: utf-8 -*-
r"""闲鱼助手多店自动修复：遍历店铺，掉线走「浏览器取 x5sec / 回填 cookie → 重启助手」；在线则跳过。
用法：python heal.py --shop <店名>    单店
      python heal.py --all             全部店铺（串行 + 店间隔 20s 节流）
由计划任务 mlzs-auto-heal 每 30 分钟运行。日志：各店 shops\<店名>\heal.log
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import shopctx
import xy_protocol as p

def _find_chrome():
    for c in (os.environ.get("CHROME_PATH"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if c and Path(c).exists():
            return c
    return r"C:\Program Files\Google\Chrome\Application\chrome.exe"


CHROME = _find_chrome()


def find_python():
    for c in (ROOT / ".venv" / "Scripts" / "python.exe",
              ROOT.parent / ".venv" / "Scripts" / "python.exe"):
        if c.exists():
            return str(c)
    return sys.executable


PY = find_python()


def log(env, msg):
    with open(env["log"], "a", encoding="utf-8") as f:
        f.write(time.strftime("[%m-%d %H:%M:%S] ") + str(msg) + "\n")


def state(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def start_app(env):
    proc = subprocess.Popen([PY, str(ROOT / "main.py"), "--shop", env["shop"]],
                            cwd=str(ROOT), creationflags=0x08000000)
    try:
        (env["data"] / "run.pid").write_text(str(proc.pid), encoding="utf-8")
    except Exception:
        pass
    log(env, f"启动助手 PID={proc.pid}")


def kill_app(env):
    pat = "--shop\\s+" + re.escape(env["shop"]) + "(\\s|$)"
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -match 'main.py' -and "
           f"$_.CommandLine -match '{pat}' }} | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)


def restart_app(env):
    kill_app(env)
    time.sleep(2)
    start_app(env)


def kill_chrome(env):
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
           f"Where-Object {{ $_.CommandLine -like '*{env['profile']}*' }} | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)


def http_json(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def harvest(cookies):
    jar = {}
    for ck in cookies:
        dom = ck.get("domain") or ""
        if "goofish.com" in dom or "mmstat.com" in dom:
            jar[ck["name"]] = ck["value"]
    return jar


def probe_token(env, retry=False):
    """单发严格探测；返回 (ret 字符串, punish_url)。retry 只影响「令牌过期」类重试。"""
    try:
        c = p.XianyuClient({}, None)
        c.load()
        dv = json.dumps({"appKey": p.IM_APP_KEY, "deviceId": c.device_id}, separators=(",", ":"))
        r = c._mtop("mtop.taobao.idlemessage.pc.login.token", "1.0", dv, retry=retry)
        ret = r.get("ret") or []
        rets = ",".join(ret) if isinstance(ret, list) else str(ret)
        return rets, ((r.get("data") or {}).get("url") or "")
    except Exception as e:
        return f"PROBE_ERR:{e}", ""


def save_session_merge(env, jar):
    old = json.loads(env["session"].read_text(encoding="utf-8"))
    old["cookies"] = {**(old.get("cookies") or {}), **jar}
    old["saved_at"] = time.time()
    env["session"].write_text(json.dumps(old, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def clean_locks(env):
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        try:
            (env["profile"] / name).unlink()
        except Exception:
            pass


def launch_chrome(env):
    """拉起 Chrome（用户桌面，带调试口）。教训：
    ①计划任务上下文里直接 Popen 调试口不生效；
    ②受限令牌（heal 在任务里跑）schtasks /create 会被"拒绝访问"——
    因此优先复用"已存在任务"（部署时预建 mlzs-open-chrome-<店>），只 run 不 create。"""
    tn = "mlzs-open-chrome-" + env["shop"]
    cmd_file = env["data"] / "open_chrome.cmd"
    profile = str(env["profile"])
    dp = env["debug_port"]
    cmd_file.write_text(
        '@echo off\r\n'
        f'start "" "{CHROME}" --remote-debugging-port={dp} '
        f'--user-data-dir="{profile}" --no-first-run '
        f'--no-default-browser-check --new-window https://www.goofish.com/\r\n',
        encoding="gbk", errors="replace")
    q = subprocess.run(["schtasks", "/query", "/tn", tn], capture_output=True)
    if q.returncode != 0:
        r = subprocess.run(["schtasks", "/create", "/f", "/tn", tn, "/tr", str(cmd_file),
                            "/sc", "once", "/st", "00:00", "/it"], capture_output=True)
        if r.returncode != 0:
            err = (r.stderr or b"").decode("gbk", "ignore")[:140].strip()
            log(env, f"创建 Chrome 任务失败（{err}），回退直拉")
            subprocess.Popen([
                CHROME,
                f"--remote-debugging-port={dp}",
                f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check",
                "https://www.goofish.com/",
            ])
            return
    subprocess.run(["schtasks", "/run", "/tn", tn], capture_output=True)
    log(env, f"已通过任务 {tn} 拉起 Chrome（调试口 {dp}）")


async def capture_x5sec(env):
    port = env["debug_port"]
    have = False
    try:
        http_json(f"http://127.0.0.1:{port}/json/version")
        have = True
    except Exception:
        pass
    if not have:
        ok = False
        for attempt in range(2):
            kill_chrome(env)
            time.sleep(1)
            clean_locks(env)
            launch_chrome(env)
            for _ in range(40):
                try:
                    http_json(f"http://127.0.0.1:{port}/json/version")
                    ok = True
                    break
                except Exception:
                    time.sleep(1)
            if ok:
                break
            log(env, f"chrome 调试口没起来（第 {attempt + 1} 次）")
            time.sleep(3)
        if not ok:
            log(env, "chrome 调试口连续两次起不来，放弃本轮")
            return False
    page = None
    for _ in range(15):
        for t in http_json(f"http://127.0.0.1:{port}/json/list"):
            if t.get("type") == "page":
                page = t
                if "goofish" in (t.get("url") or ""):
                    break
        if page:
            break
        time.sleep(1)
    if not page:
        log(env, "找不到页面")
        return False
    import websockets
    try:
        ws = await asyncio.wait_for(
            websockets.connect(page["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024),
            timeout=15)
    except Exception as e:
        log(env, f"CDP 连接失败/超时：{e}")
        return False
    async with ws:
        box = [0]

        async def call(method, params=None, timeout=20):
            box[0] += 1
            mid = box[0]
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if m.get("id") == mid:
                    return m

        async def get_jar():
            res = await call("Network.getAllCookies")
            return harvest(res.get("result", {}).get("cookies", []))

        try:
            await call("Network.enable")
            await call("Page.enable")
            # 先加载 goofish 主页，让 cookie2/_tb_token_ 等会话 cookie 落到当前浏览器会话，
            # 否则抓出来的 cookie 会缺失这些登录 cookie，导致抓完仍报 Session 过期。
            await call("Page.navigate", {"url": "https://www.goofish.com/"})
            await asyncio.sleep(6)
        except Exception as e:
            log(env, f"CDP 初始化失败/超时：{e}")
            return False

        rets, url = probe_token(env)
        log(env, f"token 探测：{rets}")
        if "SUCCESS" in rets:
            log(env, "token 探测已通（无需解封）")
            return True

        if not url:
            # 会话 cookie 失效（TOKEN_EMPTY / TOKEN_EXPIRED / SESSION_EXPIRED 等）：
            # 从浏览器登录态抓全量 cookie 回填 session.json 后复测（旧代码在此误判「已通」）。
            try:
                jar = await get_jar()
            except Exception as e:
                log(env, f"抓取 cookie 失败/超时：{e}")
                return False
            if not jar.get("unb"):
                log(env, "浏览器里已无登录态（unb 缺失），需人工扫码或过滑块")
                return False
            save_session_merge(env, jar)
            log(env, f"已从浏览器回填 cookie（{len(jar)} 个），复测 token…")
            rets, url = probe_token(env, retry=True)
            log(env, f"复测：{rets}")
            if "SUCCESS" in rets:
                return True
            if not url:
                log(env, "复测仍失败，等下一轮自动继续（必要时人工扫码）")
                return False

        try:
            await call("Page.navigate", {"url": url})
        except Exception as e:
            log(env, f"打开验证页失败/超时：{e}")
            return False
        log(env, "已把验证页拉到浏览器窗口，等待滑块验证…")
        try:
            base_x5 = ((json.loads(env["session"].read_text(encoding="utf-8"))
                        .get("cookies") or {}).get("x5sec")) or ""
        except Exception:
            base_x5 = ""
        deadline = time.time() + 180
        while time.time() < deadline:
            await asyncio.sleep(3)
            try:
                jar = await get_jar()
            except Exception as e:
                log(env, f"轮询 cookie 失败/超时：{e}")
                return False
            # 只认「与 session.json 里不一样」的 x5sec（新的），避免把浏览器残留的旧值当成果
            if jar.get("x5sec") and jar.get("x5sec") != base_x5:
                await asyncio.sleep(4)
                try:
                    jar = await get_jar()
                except Exception:
                    pass
                save_session_merge(env, jar)
                log(env, "x5sec 已捕获，session.json 更新")
                rets, _ = probe_token(env, retry=True)
                log(env, f"复测：{rets}")
                return "SUCCESS" in rets
        log(env, "等待 x5sec 超时（可能需要人工滑块）")
        return False


async def amain(env):
    s = state(env["port"])
    if s and s.get("status") == "在线":
        log(env, "状态在线，跳过")
        return
    if s and s.get("status") == "未登录":
        log(env, "未登录（等待扫码），跳过")
        return
    if s is None:
        if not env["session"].exists():
            log(env, "面板未响应且无登录态，跳过")
            return
        log(env, "面板未响应，尝试拉起助手")
        start_app(env)
        time.sleep(8)
        s2 = state(env["port"])
        log(env, "助手已启动，状态=%s" % (s2.get("status") if s2 else "未响应"))
        return
    log(env, "检测到异常：状态=%s，开始自愈" % s.get("status"))
    ok = await capture_x5sec(env)
    if ok:
        kill_chrome(env)
        restart_app(env)
        time.sleep(10)
        s3 = state(env["port"])
        log(env, "自愈完成，状态=%s" % (s3.get("status") if s3 else "未响应"))
    else:
        log(env, "自愈失败：浏览器窗口保留，可人工滑滑块，等下一轮自动继续")


def run_one(shop):
    env = shopctx.shop_env(shop)
    p.set_session_file(env["session"])
    try:
        asyncio.run(amain(env))
    except Exception as e:
        log(env, f"heal 异常：{e}")


def main():
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "mlzs-auto-heal-lock")
    if ctypes.windll.kernel32.GetLastError() == 183:
        print("已有 heal 在运行，本次跳过")
        return
    argv = sys.argv[1:]
    if "--all" in argv:
        shops = shopctx.all_shops()
        for i, shop in enumerate(shops):
            run_one(shop)
            if i < len(shops) - 1:
                time.sleep(20)
    else:
        run_one(shopctx.parse_shop())


if __name__ == "__main__":
    main()
