# -*- coding: utf-8 -*-
"""发布前敏感信息扫描：确定这个仓库能安全公开。
用法：python setup/scan_secrets.py（在仓库任意位置运行）
退出码：0=干净，1=有发现
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# 必删文件（真实数据/密钥/签名文件，出现在仓库里就是事故）
FORBIDDEN = [
    r"assistant/shops/.+/session.json",
    r"assistant/shops/.+\.db$",
    r"assistant/软件配置\.json$",
    r"assistant/知识库\.md$",
    r"assistant/补充知识\.md$",
    r"jxc/ai/ai-config\.json$",
    r"jxc/pb_data/",
    r"jxc/\.?pocketbase\.exe$",
    r"jxc/android/keystore\.jks$",
    r"jxc/android/out/",
    r".+\.log$",
    r".+/chrome-profile/",
]

# 文本内容模式（出现在任何文件里都算发现；示例文件里带 "改成你" 的会被忽略）
PATTERNS = [
    (r"A[KZ]IA[A-Z0-9]{16}", "AWS key"),
    (r"sk-[A-Za-z0-9_\-]{20,}", "OpenAI/DeepSeek 风格 key"),
    (r"SCT\d{6,}[A-Za-z0-9]*", "Server酱 key"),
    (r"\bkuanglao\b", "个人标识 kuanglao"),
    (r"矿佬", "个人标识 矿佬"),
    (r"F:\\work", "本机路径 F:\\work"),
    (r"192\.168\.7\.", "家庭内网段"),
    (r"password\s*[:=]\s*[\"'][^\"'{}\s]{6,}[\"']", "硬编码密码"),
]

TEXT_EXT = {".py", ".js", ".mjs", ".ps1", ".cmd", ".bat", ".json", ".md",
            ".html", ".css", ".java", ".xml", ".yml", ".yaml", ".sh", ".txt"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "out"}

findings = []

for p in ROOT.rglob("*"):
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    rel = p.relative_to(ROOT).as_posix()
    for pat in FORBIDDEN:
        if re.search(pat, rel, re.IGNORECASE):
            findings.append((rel, 0, "禁止存在的文件/目录: " + pat))
            break
    if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
        continue
    if rel == "setup/scan_secrets.py":
        continue  # 扫描器自身的模式串不算
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for pat, name in PATTERNS:
        for m in re.finditer(pat, text):
            line_no = text[:m.start()].count("\n") + 1
            snippet = text.splitlines()[line_no - 1].strip()[:100]
            if "改成你" in snippet or "example" in snippet.lower():
                continue
            findings.append((rel, line_no, f"{name}: {snippet}"))

if not findings:
    print("扫描通过：没有发现敏感信息")
    sys.exit(0)

print(f"发现 {len(findings)} 处问题：")
for rel, line, msg in findings:
    print(f"  {rel}:{line}  {msg}")
sys.exit(1)
