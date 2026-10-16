# -*- coding: utf-8 -*-
r"""店铺管理（命令行侧）
用法：
  python shop_admin.py new <店名>    新建店铺（自动分配面板/调试端口，生成配置）
  python shop_admin.py list          列出店铺与运行状态
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import shopctx


def cmd_new(name):
    name = (name or "").strip()
    if not name:
        print("用法：python shop_admin.py new <店名（字母/数字/下划线）>")
        return 1
    if not re.match(r"^[A-Za-z0-9_\-]+$", name):
        print("店名只允许字母/数字/下划线/减号（中文别名写在配置 display_name 里）")
        return 1
    d = shopctx.SHOPS_DIR / name
    if (ROOT / "单店版.txt").exists():
        print("此为单店铺测试版：仅支持预置的单店，不支持新建店铺。")
        return 1
    if d.exists():
        print(f"店铺已存在：{d}")
        return 1
    used_ports, used_debug = set(), set()
    for s in shopctx.all_shops():
        try:
            cfg = json.loads((shopctx.SHOPS_DIR / s / "config.json").read_text(encoding="utf-8"))
            used_ports.add(int(cfg.get("port", 8767)))
            used_debug.add(int(cfg.get("debug_port", 9333)))
        except Exception:
            pass
    port = 8767
    while port in used_ports:
        port += 1
    debug = 9333
    while debug in used_debug:
        debug += 1
    d.mkdir(parents=True)
    import main as m
    cfg = dict(m.DEFAULT_CONFIG)
    cfg.update({"shop": name, "display_name": name, "port": port, "debug_port": debug})
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    print(f"店铺 {name} 已创建")
    print(f"  目录：{d}")
    print(f"  面板端口：{port}   调试端口：{debug}")
    print("  下一步：用『店铺管理』启动此店，再打开面板扫码登录对应闲鱼小号")
    return 0


def cmd_list():
    shops = shopctx.all_shops()
    if not shops:
        print("还没有店铺（shops/ 为空）")
        return 0
    print(f"共 {len(shops)} 个店铺：")
    for s in shops:
        try:
            env = shopctx.shop_env(s)
        except SystemExit:
            continue
        st, nick = "未启动", ""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{env['port']}/api/state", timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
                st = data.get("status") or "?"
                nick = data.get("nick") or ""
        except Exception:
            pass
        name = str(env["config"].get("display_name") or s)
        print(f"  {s:<10} {name:<14} 端口 {env['port']}  {st}  {nick}")
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "new":
        return cmd_new(argv[1] if len(argv) > 1 else "")
    if argv and argv[0] == "list":
        return cmd_list()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
