# -*- coding: utf-8 -*-
r"""闲鱼卖家工作台 · 首次配置向导（交互式）
用法：双击 setup\首次配置.bat，或 python setup\首次配置.py
做完的事：
  1. 建第一个店铺配置 assistant\shops\<店名>\config.json
  2. 写 assistant\软件配置.json（店名 / AI key）
  3. 复制知识库模板（若还没有）
  4. 初始化进销存：拉起 PocketBase → 建管理员账号 → 建登录用户 → 写 jxc\ai\ai-config.json
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSIST = ROOT / "assistant"
JXC = ROOT / "jxc"
PB_EXE = JXC / "pocketbase.exe"
PB_URL = "http://127.0.0.1:8090"


def ask(prompt, default=""):
    hint = f"（默认 {default}）" if default else ""
    v = input(f"{prompt}{hint}: ").strip()
    return v or default


def http_json(method, path, body=None, token=None, timeout=10):
    req = urllib.request.Request(PB_URL + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def ensure_pb():
    """确保 PocketBase 在跑。返回 True/False。"""
    st, _ = http_json("GET", "/api/health", timeout=3)
    if st == 200:
        print("  进销存服务已在运行")
        return True
    if not PB_EXE.exists():
        print("  [跳过] 缺少 jxc\\pocketbase.exe，请先运行 setup\\安装依赖.bat")
        return False
    print("  启动进销存服务（pocketbase）...")
    subprocess.Popen([str(PB_EXE), "serve", "--http=0.0.0.0:8090"],
                     cwd=str(JXC), creationflags=0x08000000)
    for _ in range(30):
        time.sleep(1)
        st, _ = http_json("GET", "/api/health", timeout=2)
        if st == 200:
            return True
    print("  [警告] 进销存服务起得慢，稍后可再试")
    return False


def setup_pb_account(email, password):
    """建超级管理员 + 建 users 登录账号。"""
    # 1) superuser（命令行方式，幂等）
    r = subprocess.run([str(PB_EXE), "superuser", "upsert", email, password],
                       cwd=str(JXC), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"  [警告] 管理员创建返回：{r.stderr.strip()[:120]}")
    # 2) 登录拿 token
    st, j = http_json("POST", "/api/collections/_superusers/auth-with-password",
                      {"identity": email, "password": password})
    if st != 200 or not j.get("token"):
        print("  [警告] 管理员登录失败，跳过用户创建（稍后可在网页后台手动建用户）")
        return False
    token = j["token"]
    # 3) 建 users 记录（已存在则跳过）
    st, j = http_json("POST", "/api/collections/users/records",
                      {"email": email, "password": password,
                       "passwordConfirm": password, "verified": True}, token=token)
    if st in (200, 201):
        print("  登录用户已创建")
    elif st == 400 and "already" in json.dumps(j).lower():
        print("  登录用户已存在，跳过")
    else:
        print(f"  [提示] 用户创建返回 {st}：{json.dumps(j, ensure_ascii=False)[:120]}")
    return True


def main():
    print("===== 闲鱼卖家工作台 · 首次配置 =====")
    print()

    # ── 1. 店铺 ──
    print("【1/3】闲鱼店铺")
    shop = ask("店铺标识（字母/数字，用于目录名）", "shop01")
    display = ask("店铺昵称（面板上显示）", shop)
    port = ask("面板端口", "8767")
    key = ask("DeepSeek API Key（回车可跳过，稍后在面板设置里填）", "")
    push = ask("PushPlus Token（转人工微信推送，回车跳过）", "")

    shop_dir = ASSIST / "shops" / shop
    shop_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "shop": shop, "display_name": display, "port": int(port),
        "debug_port": 9333, "auto_reply": True,
        "pushplus_token": push, "serverchan_key": "",
    }
    (shop_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写入 {shop_dir / 'config.json'}")

    soft_path = ASSIST / "软件配置.json"
    soft = {}
    if soft_path.exists():
        try:
            soft = json.loads(soft_path.read_text(encoding="utf-8"))
        except Exception:
            soft = {}
    soft.update({"店名": display, "llm_base_url": soft.get("llm_base_url") or "https://api.deepseek.com",
                 "llm_model": soft.get("llm_model") or "deepseek-chat"})
    if key:
        soft["llm_key"] = key
    soft.setdefault("知识库", "知识库.md")
    soft_path.write_text(json.dumps(soft, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写入 {soft_path}")

    kb = ASSIST / "知识库.md"
    if not kb.exists() and (ASSIST / "知识库.example.md").exists():
        kb.write_text((ASSIST / "知识库.example.md").read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  已生成知识库模板 {kb}（记得改成你自己的内容）")

    # ── 2. 进销存 ──
    print()
    print("【2/3】进销存（PocketBase）")
    email = ask("登录邮箱（网页/手机App用）", "you@example.com")
    password = ask("登录密码", "")
    if password and ensure_pb():
        setup_pb_account(email, password)

    ai_cfg = JXC / "ai" / "ai-config.json"
    ai = {"pb_url": PB_URL, "pb_identity": email, "pb_password": password,
          "llm_key": key or soft.get("llm_key", "")}
    ai_cfg.write_text(json.dumps(ai, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写入 {ai_cfg}")

    # ── 3. 完成 ──
    print()
    print("【3/3】完成 ✅")
    print("  启动：双击 workbench\\工作台.bat → 选 1 启动全部服务")
    print("  打开：浏览器访问 http://127.0.0.1:8090/workbench/")
    print("  闲鱼登录：在「闲鱼客服」tab 里点扫码登录，用闲鱼小号扫码")
    print()
    input("按回车退出...")


if __name__ == "__main__":
    main()
