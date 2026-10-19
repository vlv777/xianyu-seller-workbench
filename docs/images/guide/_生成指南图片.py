# -*- coding: utf-8 -*-
"""生成「闲鱼卖家工作台·安装指南」图文卡（7 张 1080x1440，暖色系）
素材：_素材\workbench.png / _素材\panel.png（真实截图）
用法：python _生成指南图片.py
"""
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
SHOT_WB = BASE / "_素材" / "workbench.png"
SHOT_PN = BASE / "_素材" / "panel.png"
TOTAL = 7

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1440px; overflow:hidden; background:#FBF7F0; color:#2B241C;
  font-family:"Microsoft YaHei","PingFang SC",sans-serif; display:flex; flex-direction:column; }
.head { padding:56px 68px 0; display:flex; align-items:center; justify-content:space-between; }
.kicker { font-size:27px; letter-spacing:4px; color:#C25A1F; font-weight:800; }
.pageno { font-size:25px; color:#C7B8A2; letter-spacing:2px; font-weight:700; }
.hero { flex:1; display:flex; flex-direction:column; justify-content:center; padding:0 68px 56px; }
.big { font-size:88px; line-height:1.2; font-weight:800; letter-spacing:1px; }
.big .hl { color:#F26722; }
.mid { margin-top:30px; font-size:37px; color:#8A7B68; line-height:1.62; }
.rows { margin-top:42px; display:flex; flex-direction:column; gap:28px; }
.row { display:flex; gap:18px; font-size:36px; line-height:1.52; align-items:flex-start; }
.dot { flex:0 0 auto; margin-top:15px; width:16px; height:16px; border-radius:50%; background:#F26722; }
.tags { margin-top:44px; display:flex; flex-wrap:wrap; gap:16px; }
.tag { background:#FDEEE1; color:#A8501F; font-size:27px; font-weight:700;
  padding:13px 28px; border-radius:999px; border:2px solid #F6D9C0; }
.codebox { margin-top:34px; background:#fff; border:2px solid #EFE2CE; border-radius:18px;
  padding:30px 34px; font-size:30px; line-height:1.85; color:#3C352A;
  font-family:Consolas,"Microsoft YaHei",monospace; }
.codebox .ok { color:#177A43; font-weight:700; }
.codebox .k { color:#C25A1F; font-weight:800; }
.codebox .dim { color:#A79A86; }
.shot { margin-top:30px; display:flex; justify-content:center; }
.shot img { max-width:940px; width:100%; height:auto; border-radius:14px; border:8px solid #fff;
  box-shadow:0 16px 44px rgba(160,110,50,.18); }
.shotcap { margin-top:14px; text-align:center; font-size:28px; color:#8A7B68; }
.foot { padding:24px 68px 40px; display:flex; align-items:center; justify-content:space-between;
  font-size:25px; color:#C7B8A2; letter-spacing:2px; }
.foot .brand { color:#C25A1F; font-weight:800; }
""".strip()

TMPL = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>@@CSS@@</style></head><body>
<div class="head"><div class="kicker">@@KICKER@@</div><div class="pageno">@@PAGENO@@</div></div>
<div class="hero">
@@HERO@@
</div>
<div class="foot"><span class="brand">闲鱼卖家工作台</span><span>免安装版 · 安装指南</span></div>
</body></html>"""


def big(t):
    return f'<div class="big">{t}</div>'


def mid(*lines):
    return '<div class="mid">' + "<br>".join(lines) + "</div>"


def rows(*items):
    body = "".join(f'<div class="row"><div class="dot"></div><div>{t}</div></div>' for t in items)
    return f'<div class="rows">{body}</div>'


def tags(*items):
    return '<div class="tags">' + "".join(f'<span class="tag">{t}</span>' for t in items) + "</div>"


def shot(img, cap, extra=""):
    src = f"file:///{Path(img).as_posix()}"
    body = f'<div class="shot"><img src="{src}"></div>'
    if cap:
        body += f'<div class="shotcap">{cap}</div>'
    return body + extra


COVER_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1440px; overflow:hidden;
  background:linear-gradient(165deg,#FFF9F0 0%,#FBEFDB 58%,#FCE3C6 100%);
  color:#2B241C; font-family:"Microsoft YaHei","PingFang SC",sans-serif;
  display:flex; flex-direction:column; position:relative; }
.ring1 { position:absolute; width:760px; height:760px; border-radius:50%;
  border:3px solid rgba(242,103,34,.16); right:-240px; top:-200px; }
.ring2 { position:absolute; width:420px; height:420px; border-radius:50%;
  border:3px solid rgba(31,95,208,.12); left:-150px; bottom:-120px; }
.head { padding:66px 78px 0; }
.badge { display:inline-block; background:#F26722; color:#fff; font-size:30px; font-weight:800;
  padding:15px 34px; border-radius:999px; letter-spacing:3px; box-shadow:0 10px 26px rgba(242,103,34,.30); }
.hero { flex:1; display:flex; flex-direction:column; justify-content:center; padding:0 78px 20px; }
.big { font-size:104px; line-height:1.18; font-weight:800; letter-spacing:2px; }
.big .hl { color:#F26722; }
.sub { margin-top:36px; font-size:38px; line-height:1.62; color:#7A6B58; }
.chips { margin-top:50px; display:flex; flex-wrap:wrap; gap:16px; }
.chip { background:#FFFFFF; color:#8A5A2B; font-size:28px; font-weight:700;
  padding:14px 30px; border-radius:999px; border:2px solid #F3DFC8; box-shadow:0 8px 20px rgba(160,110,50,.10); }
.line { margin-top:54px; height:5px; width:200px; background:#F26722; border-radius:3px; }
.foot { padding:0 78px 58px; display:flex; justify-content:space-between; font-size:28px;
  color:#B09A80; letter-spacing:2px; }
.foot .brand { color:#F26722; font-weight:800; }
"""

COVER = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>@@CSS@@</style></head><body>
<div class="ring1"></div><div class="ring2"></div>
<div class="head"><span class="badge">免安装版 · 3 分钟装好</span></div>
<div class="hero">
  <div class="big">下载解压<br>就能<span class="hl">直接用</span></div>
  <div class="sub">不用装 Python / Node / 数据库<br>数据全在自己电脑，开源免费</div>
  <div class="chips"><span class="chip">Windows 10/11</span><span class="chip">解压即用</span><span class="chip">本地运行</span></div>
  <div class="line"></div>
</div>
<div class="foot"><span class="brand">闲鱼卖家工作台</span><span>免安装版 · 安装指南</span></div>
</body></html>"""

PAGES = [
    ("01-封面", None, COVER),
    ("02-下载解压", "第 1 步 · 下载解压", None),
    ("03-首次配置", "第 2 步 · 首次配置", None),
    ("04-启动服务", "第 3 步 · 启动服务", None),
    ("05-打开工作台", "第 4 步 · 打开工作台", None),
    ("06-扫码登录", "第 5 步 · 扫码登录", None),
    ("07-不懂就问AI", "常见问题 · 不懂就问 AI", None),
]

HERO = {
    "02-下载解压": (
        big("去 Releases<br>下载<span class='hl'>免安装包</span>")
        + '<div class="codebox">github.com/vlv777/xianyu-seller-workbench'
          '<br>→ Releases → <span class="k">xianyu-seller-workbench-portable.zip</span></div>'
        + rows("解压到普通目录（建议 D:\\Tools\\，别放网盘同步目录）",
               "解压后得到「xianyu-seller-workbench」文件夹",
               "包内已带 Python / Node / 数据库，什么都不用装")
        + tags("约 100 MB", "Windows 10/11 64 位")
    ),
    "03-首次配置": (
        big("双击<br><span class='hl'>首次配置.bat</span>")
        + rows("按提示填几步（约半分钟）：店名、进销存账号密码",
               "DeepSeek Key 可以留空，之后在面板里再填")
        + '<div class="codebox"><span class="dim">&gt; 首次配置.bat</span><br>'
          '【1/3】闲鱼店铺 …… <span class="ok">已写入 config.json</span><br>'
          '【2/3】进销存 …… <span class="ok">登录用户已创建</span><br>'
          '【3/3】完成 <span class="ok">✅</span></div>'
        + tags("只跑一次", "失败了重跑即可")
    ),
    "04-启动服务": (
        big("双击工作台.bat<br>选 <span class='hl'>1 启动</span>")
        + '<div class="codebox"><span class="dim">===== 卖家工作台 =====</span><br>'
          '1) 启动全部服务 ……<br>'
          '<span class="ok">[OK] 进销存      http://127.0.0.1:8090</span><br>'
          '<span class="ok">[OK] AI开单     http://127.0.0.1:8091</span><br>'
          '<span class="ok">[OK] 闲鱼-主店  http://127.0.0.1:8767</span></div>'
        + rows("四个灯全绿 = 全部就绪", "以后每天用就这一步（2/3/4 可随时停/重启/看状态）")
    ),
    "05-打开工作台": (
        big("浏览器打开<br><span class='hl'>工作台主页</span>")
        + mid("http://127.0.0.1:8090/workbench/")
        + shot(SHOT_WB, "顶部是服务灯和订单金额；两个页签：进销存 / 闲鱼客服")
    ),
    "06-扫码登录": (
        big("「闲鱼客服」页签里<br>点 <span class='hl'>扫码登录</span>")
        + shot(SHOT_PN, "用「闲鱼小号」扫码最稳；登录一次后自动保持")
    ),
    "07-不懂就问AI": (
        big("看不懂？<br>直接<span class='hl'>问 AI</span>")
        + rows("把「卡在哪一步 + 报错原文」发给你常用的 AI（DeepSeek / 豆包 / 元宝 / ChatGPT），让它带你排查",
               "项目里还有《AI 一键部署提示词》：整段粘贴给任意 AI，它能直接帮你装",
               "备份 = 把整个文件夹拷走；换电脑拷过去接着用")
        + tags("常见问题都写在 README", "报错别慌，先问 AI")
    ),
}


def build(name, kicker, cover):
    if cover:
        return cover.replace("@@CSS@@", COVER_CSS)
    n = PAGES.index([p for p in PAGES if p[0] == name][0]) + 1
    return (TMPL.replace("@@CSS@@", CSS)
            .replace("@@KICKER@@", kicker)
            .replace("@@PAGENO@@", f"{n:02d} / {TOTAL:02d}")
            .replace("@@HERO@@", HERO[name]))


def find_chrome():
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if Path(p).exists():
            return p
    return None


def main():
    chrome = find_chrome()
    print("chrome:", chrome)
    build_dir = BASE / "_html"
    build_dir.mkdir(exist_ok=True)
    profile = build_dir / "_chrome_profile"
    for name, kicker, cover in PAGES:
        html = build(name, kicker, cover)
        hp = build_dir / f"{name}.html"
        hp.write_text(html, encoding="utf-8")
        png = BASE / f"{name}.png"
        for flag in ("--headless=new", "--headless"):
            subprocess.run(
                [chrome, flag, "--disable-gpu", "--hide-scrollbars",
                 f"--user-data-dir={profile}", "--force-device-scale-factor=1",
                 "--window-size=1080,1440", f"--screenshot={png}",
                 f"file:///{hp.as_posix()}"],
                capture_output=True, timeout=60,
            )
            if png.exists() and png.stat().st_size > 5000:
                break
        print(name, "->", png.stat().st_size if png.exists() else "FAIL")


if __name__ == "__main__":
    main()
