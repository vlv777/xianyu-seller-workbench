# -*- coding: utf-8 -*-
"""AI 大脑：本地知识库检索 + LLM 生成客服草稿（对接同目录 kb.py）"""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_lock = threading.Lock()
_state = {"kb": None, "chunks": None, "bm25": None, "loaded_m": 0}


def _load(_config=None):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import kb
    return kb


def _ensure_fresh(kb_mod):
    with _lock:
        if not kb_mod.KB_SRC.exists():
            raise FileNotFoundError(
                f"找不到知识库文件：{kb_mod.KB_SRC}（可从 知识库.example.md 复制一份开始写）")
        kb_mod.refresh_cfg()
        kb_m = kb_mod.KB_SRC.stat().st_mtime if kb_mod.KB_SRC.exists() else 0
        if kb_mod.KB_EXTRA.exists():
            kb_m = max(kb_m, kb_mod.KB_EXTRA.stat().st_mtime)
        ch_m = kb_mod.CHUNKS_FILE.stat().st_mtime if kb_mod.CHUNKS_FILE.exists() else 0
        if kb_m > ch_m:
            kb_mod.build_and_save()
            ch_m = kb_mod.CHUNKS_FILE.stat().st_mtime
        if ch_m > _state["loaded_m"]:
            _state["chunks"], _state["bm25"] = kb_mod.load_index()
            _state["loaded_m"] = ch_m


def warmup(config=None):
    kb_mod = _state["kb"] or _load(config)
    _state["kb"] = kb_mod
    _ensure_fresh(kb_mod)


def answer(config, question):
    """返回 (draft, need_human, note)。draft 仅在不需人工时非空。"""
    question = (question or "").strip()
    if not question:
        return "", True, "空消息"
    try:
        kb_mod = _state["kb"] or _load(config)
        _state["kb"] = kb_mod
        _ensure_fresh(kb_mod)
        reply, hits, _ = kb_mod.ask(question, _state["chunks"], _state["bm25"])
    except Exception as e:
        return "", True, f"大脑异常: {e}"
    if not reply:
        return "", True, "知识库无命中"
    draft = reply.split("【依据】", 1)[0].replace("【草稿】", "").strip()
    if "【需人工】" in draft:
        draft = draft.replace("【需人工】", "").strip()
        return draft, True, "AI 标记需人工"
    return draft, False, "ok"
