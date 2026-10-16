# -*- coding: utf-8 -*-
"""本地知识库引擎：把 Markdown 知识库切成片段，用 BM25 检索，调 LLM 生成客服草稿。

用法：
  python kb.py --build           # 从知识库 md 重建切片索引
  python kb.py --ask "问题"      # 单次提问出草稿
  python kb.py --retrieve --ask "问题"   # 只看检索命中（调试）
  python kb.py                   # 交互模式

配置（与本文件同目录的 软件配置.json）：
  llm_base_url   OpenAI 兼容接口地址（默认 https://api.deepseek.com）
  llm_model      模型名（默认 deepseek-chat）
  llm_key        API Key（也可用环境变量 DEEPSEEK_API_KEY）
  知识库         知识库 md 文件路径（默认同目录 知识库.md）
  custom_rules   追加到客服人设的自定义规则（店规），字符串或字符串数组
"""
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import jieba
import requests
from rank_bm25 import BM25Okapi

jieba.setLogLevel(logging.WARNING)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SOFT_CFG = ROOT / "软件配置.json"


def _load_soft_cfg():
    try:
        return json.loads(SOFT_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_kb_src():
    p = str(_load_soft_cfg().get("知识库") or "").strip()
    if p:
        pp = Path(p)
        return pp if pp.is_absolute() else (ROOT / pp)
    return ROOT / "知识库.md"


KB_SRC = _resolve_kb_src()
KB_EXTRA = ROOT / "补充知识.md"
CHUNKS_FILE = ROOT / "kb-chunks.json"
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
TOP_K = 8

_soft = _load_soft_cfg()
SHOP_NAME = str(_soft.get("店名") or "本店")

GENERIC_RULES = """硬规则：
1. 只依据【资料】回答，资料里没有的信息绝不编造；不知道就写"这个我确认下"。
   时间、时效、天数、运费、费用、参数等具体数字，资料没有就绝不允许给（包括"大概""一般""通常"的说法）。
2. 议价、退款、纠纷、索赔、特殊承诺（包邮/包到货时间等）一律不自行表态，结尾加「【需人工】」。
3. 口吻：像店主本人聊天，直接、简短、不客套，不堆笑脸表情，不啰嗦，1~5 句话。
4. 知识库里的内部信息（成本、加价逻辑、进货渠道）不写给买家，只写对买家有用的结论。
5. 遇到拿不准的问题不要硬答：请买家把问题说得再具体一点，或问一句「还有其他问题吗？」；
   仍判断不了的，按第 1 条写「这个我确认下」。"""


def _custom_rules_text():
    rules = _load_soft_cfg().get("custom_rules") or ""
    if isinstance(rules, list):
        rules = "\n".join(str(x) for x in rules)
    rules = str(rules).strip()
    return ("\n\n本店额外规则（店主自定，优先遵守）：\n" + rules) if rules else ""


SYSTEM_PROMPT = f"""你是闲鱼店铺「{SHOP_NAME}」的客服助理。草稿会由店主本人发给买家，
所以必须以第一人称（"我/我们店"）来写，禁止出现"找老板""跟老板聊"这类第三方说法。

{GENERIC_RULES}{_custom_rules_text()}

输出格式（严格遵守）：
【草稿】
（一段可直接参考的回复）
【依据】
- 小节名，一行一个"""


def tokenize(s):
    return [w for w in jieba.cut_for_search(s) if w.strip()]


def parse_md(text):
    lines = text.splitlines()
    chunks = []
    path_stack = []
    buf = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"path": " > ".join(t for _, t in path_stack), "text": body})
        buf.clear()

    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2)
            path_stack = [p for p in path_stack if p[0] < level]
            path_stack.append((level, title))
        else:
            buf.append(line)
    flush()
    return chunks


def build_chunks():
    if not KB_SRC.exists():
        raise FileNotFoundError(f"找不到知识库文件：{KB_SRC}（可从 知识库.example.md 复制一份开始写）")
    chunks = parse_md(KB_SRC.read_text(encoding="utf-8"))
    if KB_EXTRA.exists():
        chunks += parse_md(KB_EXTRA.read_text(encoding="utf-8"))

    out = []
    for c in chunks:
        if len(c["text"]) <= 1500:
            out.append(c)
            continue
        parts, cur = [], []
        for seg in c["text"].split("\n\n"):
            cur.append(seg)
            if sum(len(x) for x in cur) > 1000:
                parts.append("\n\n".join(cur))
                cur = []
        if cur:
            parts.append("\n\n".join(cur))
        for i, p in enumerate(parts, 1):
            out.append({"path": f'{c["path"]} ({i}/{len(parts)})', "text": p.strip()})
    return out


def build_and_save():
    chunks = build_chunks()
    CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    return chunks


def append_extra(question, answer):
    """把人工确认的问答写进补充知识库。返回 'added' / 'updated'。"""
    q = " ".join(question.split())
    a = answer.strip()
    if not q or not a:
        raise ValueError("问题和答复都不能为空")
    title = q[:40]
    from datetime import date
    entry = f"### {title}\n\n- 问题：{q}\n- 答复：{a}\n- 记录：{date.today().isoformat()}\n"
    if KB_EXTRA.exists():
        text = KB_EXTRA.read_text(encoding="utf-8")
    else:
        text = "# 补充知识（客服助手收集）\n"
    pat = re.compile(rf"(?ms)^### {re.escape(title)}\n.*?(?=^### |\Z)")
    if pat.search(text):
        text = pat.sub(entry.rstrip() + "\n", text)
        action = "updated"
    else:
        text = text.rstrip() + "\n\n" + entry
        action = "added"
    KB_EXTRA.write_text(text, encoding="utf-8")
    return action


def load_index():
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    corpus = [tokenize(c["path"] + " " + c["path"] + " " + c["text"]) for c in chunks]
    return chunks, BM25Okapi(corpus)


def _llm_cfg():
    s = _load_soft_cfg()
    base = str(s.get("llm_base_url") or "https://api.deepseek.com").strip().rstrip("/")
    model = str(s.get("llm_model") or MODEL).strip()
    key = str(s.get("llm_key") or "").strip()
    return base, model, key


def get_api_key():
    _, _, k = _llm_cfg()
    if k:
        return k
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    raise RuntimeError("未配置 AI 接口 Key：请在助手面板「设置」中填写，"
                       "或写入 软件配置.json 的 llm_key（也可用环境变量 DEEPSEEK_API_KEY）")


def llm(messages, temperature=0.3, max_tokens=2500):
    base, model, _ = _llm_cfg()
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {get_api_key()}"},
        json={"model": model, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _core_paths():
    try:
        title = KB_SRC.stem
        for line in KB_SRC.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break
    except Exception:
        title = KB_SRC.stem
    return tuple(f"{title} > {x}" for x in ("店铺基本信息", "售后政策", "注意事项", "回复话术模板"))


def retrieve(question, chunks, bm25):
    scores = bm25.get_scores(tokenize(question))
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    hits = [i for i in ranked[:TOP_K] if scores[i] > 0]
    core = _core_paths()
    for i, c in enumerate(chunks):
        if i in hits:
            continue
        if any(c["path"] == p or c["path"].startswith(p + " > ") for p in core):
            hits.append(i)
    return hits, scores


def ask(question, chunks, bm25):
    """检索 + 生成草稿。返回 (reply, hits, scores)；无命中时 reply 为 None。"""
    hits, scores = retrieve(question, chunks, bm25)
    if not hits:
        return None, hits, scores
    ctx = "\n\n".join(
        f"【资料 {n+1}｜{chunks[i]['path']}】\n{chunks[i]['text']}"
        for n, i in enumerate(hits)
    )
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"买家问：{question}\n\n【资料】\n{ctx}"},
    ]
    return llm(msgs), hits, scores


def run_one(question, chunks, bm25, retrieve_only=False):
    if retrieve_only:
        hits, scores = retrieve(question, chunks, bm25)
        reply = None
    else:
        reply, hits, scores = ask(question, chunks, bm25)
    print("\n--- 命中资料 ---")
    if not hits:
        print("(无命中)")
    for i in hits:
        mark = f"{scores[i]:6.2f}" if scores[i] > 0 else "  常驻 "
        print(f"[{mark}] {chunks[i]['path']}")
    if retrieve_only or reply is None:
        return
    print("\n--- 回复草稿 ---")
    print(reply)


def refresh_cfg():
    """软配置热更新（面板改设置后调用）。"""
    global _soft, SHOP_NAME, SYSTEM_PROMPT
    _soft = _load_soft_cfg()
    SHOP_NAME = str(_soft.get("店名") or "本店")
    SYSTEM_PROMPT = f"""你是闲鱼店铺「{SHOP_NAME}」的客服助理。草稿会由店主本人发给买家，
所以必须以第一人称（"我/我们店"）来写，禁止出现"找老板""跟老板聊"这类第三方说法。

{GENERIC_RULES}{_custom_rules_text()}

输出格式（严格遵守）：
【草稿】
（一段可直接参考的回复）
【依据】
- 小节名，一行一个"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="重建切片索引")
    ap.add_argument("--ask", metavar="Q", help="单次提问")
    ap.add_argument("--retrieve", action="store_true", help="只显示检索命中")
    args = ap.parse_args()

    if args.build:
        chunks = build_and_save()
        print(f"OK: {len(chunks)} chunks -> {CHUNKS_FILE}")
        return

    chunks, bm25 = load_index()
    if args.ask:
        run_one(args.ask, chunks, bm25, retrieve_only=args.retrieve)
        return
    if args.retrieve:
        print("--retrieve 只配合 --ask 使用")
        return
    print(f"{SHOP_NAME} 客服草稿助手 | 输入买家问题回车出草稿，q 退出")
    while True:
        q = input("\n买家> ").strip()
        if not q:
            continue
        if q.lower() in ("q", "quit", "exit"):
            break
        run_one(q, chunks, bm25)


if __name__ == "__main__":
    main()
