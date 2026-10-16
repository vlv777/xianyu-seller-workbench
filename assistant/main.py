# -*- coding: utf-8 -*-
"""闲鱼卖家工作台 · 闲鱼助手主程序
买家消息 → 本地知识库大脑（kb.py）→ 自动回复 / 转人工(微信推送) → 网页面板接管
"""
import asyncio
import contextlib
import json
import random
import sys
import threading
import time
from pathlib import Path

import brain
import notify
import panel
import shopctx
import store
import vision
import xy_protocol
from xy_protocol import QrLogin, XianyuClient

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT  # main() 启动时按 --shop 指向 shops/<店名>


def _config_file():
    return DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "port": 8767,
    "auto_reply": True,
    "holding_text": "这个我确认下",
    "handoff_keywords": ["退款", "退货", "投诉", "举报", "纠纷", "假货", "骗子", "赔",
                         "便宜", "少点", "少一点", "能少", "优惠", "降价", "砍价",
                         "议价", "抹零", "小刀", "再低", "低点", "最低"],
    "reply_delay_min": 2.0,
    "reply_delay_max": 6.0,
    "max_replies_per_10min": 8,
    "pushplus_token": "",
    "serverchan_key": "",
    "auth_retry_seconds": 1800,
    # 出稿前的替换表（悄悄替换敏感词/统一话术），示例：
    #   "text_replacements": [["OpenWrt", "OP"], ["uboot", "ubt"], ...]
    "text_replacements": [],
}


def load_config():
    f = _config_file()
    if f.exists():
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        merged = {**DEFAULT_CONFIG, **cfg}
    else:
        merged = dict(DEFAULT_CONFIG)
        f.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def save_config(cfg):
    _config_file().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class App:
    def __init__(self):
        self.config = load_config()
        self._soft_cfg_path = ROOT / "软件配置.json"
        self.config.update(self._soft_show())
        store.init()
        self.client = self._make_client()
        self.loop = None
        self.login = QrLogin()
        self._client_task = None
        self._qr_thread = None
        self._qr_started_at = 0.0
        self._reply_times = {}
        self._lock = threading.Lock()

    def _soft_load(self):
        try:
            return json.loads(self._soft_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _soft_show(self):
        s = self._soft_load()
        return {"deepseek_api_key": s.get("llm_key") or s.get("deepseek_key") or "",
                "kb_path": s.get("知识库") or "",
                "vision_base_url": s.get("vision_base_url") or "",
                "vision_key": s.get("vision_key") or "",
                "vision_model": s.get("vision_model") or ""}

    def _make_client(self):
        client = XianyuClient(self.config, self.on_buyer_message)
        client.on_send_rejected = self._on_late_reject
        client.on_auth_failed = self._on_auth_failed
        return client

    def _on_auth_failed(self, message):
        notify.push(
            self.config,
            "闲鱼助手离线：登录失效",
            f"{message}\n\n请打开面板重新登录/过验证："
            f"http://127.0.0.1:{self.config['port']}/",
        )

    # ── 启动 ────────────────────────────────────────────────
    def run(self):
        try:
            brain.warmup(self.config)
            store.log("info", "知识库大脑加载完成")
        except Exception as e:
            store.log("error", f"知识库加载失败：{e}")
        threading.Thread(target=panel.serve, args=(self,), daemon=True).start()
        store.log("info", f"网页面板：http://127.0.0.1:{self.config['port']}/")
        asyncio.run(self._main())

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        if self.client.load():
            self._client_task = asyncio.create_task(self.client.run_forever())
        else:
            store.log("warn", "尚未登录，请打开网页面板扫码登录小号")
        while True:
            await asyncio.sleep(3600)

    # ── 自动回复 ────────────────────────────────────────────
    def _rate_ok(self, cid):
        now = time.time()
        with self._lock:
            times = [t for t in self._reply_times.get(cid, []) if now - t < 600]
            self._reply_times[cid] = times
            return len(times) < int(self.config.get("max_replies_per_10min", 8))

    def _rate_mark(self, cid):
        with self._lock:
            self._reply_times.setdefault(cid, []).append(time.time())

    def _safe_text(self, text):
        """发送前替换已验证会触发闲鱼审核的句式。"""
        for pair in self.config.get("text_replacements") or []:
            try:
                src, dst = pair
            except Exception:
                continue
            if src and src in text:
                text = text.replace(src, dst)
                store.log("debug", f"已替换敏感句式：{src} -> {dst}")
        return text

    async def on_buyer_message(self, msg):
        cid, nick, text = msg["cid"], msg["nick"] or msg["buyer_id"], msg["text"]
        if not store.add_message(cid, "in", "buyer", text, msg["ts"]):
            return
        store.upsert_conversation(cid, msg["buyer_id"], msg["nick"], text, msg["ts"])
        store.log("info", f"收到 {nick}：{text[:60]}")
        image_url = msg.get("image_url") or ""
        if image_url:
            if not self.config.get("auto_reply"):
                return
            conv = store.get_conversation(cid)
            if not conv or conv["mode"] != "auto":
                return
            await self._on_image(cid, msg, image_url)
            return
        if not self.config.get("auto_reply"):
            return
        conv = store.get_conversation(cid)
        if not conv or conv["mode"] != "auto":
            return
        keyword = next((k for k in self.config.get("handoff_keywords", []) if k and k in text), "")
        if keyword:
            await self._handoff(cid, msg, "", f"命中关键词「{keyword}」")
            return
        if not self._rate_ok(cid):
            store.log("warn", f"{nick} 触发限频，本轮不回复")
            return
        delay = random.uniform(float(self.config.get("reply_delay_min", 2)),
                               float(self.config.get("reply_delay_max", 6)))
        await asyncio.sleep(delay)
        if not self.config.get("auto_reply"):
            return
        conv = store.get_conversation(cid)
        if not conv or conv["mode"] != "auto":
            return
        draft, need_human, note = await asyncio.to_thread(brain.answer, self.config, text)
        self._rate_mark(cid)
        if need_human:
            await self._handoff(cid, msg, draft, note)
        elif draft:
            await self._send(cid, msg["buyer_id"], self._safe_text(draft),
                             sender="ai", nick=nick)
        else:
            await self._handoff(cid, msg, "", "大脑无草稿")

    async def _on_image(self, cid, msg, image_url):
        """买家发来图片：识别后优先自动回复，不确定则转人工。"""
        nick = msg["nick"] or msg["buyer_id"]
        desc = ""
        if vision.enabled(self.config):
            store.log("info", f"图片识别中（{nick}）…")
            desc = await asyncio.to_thread(vision.describe_url, self.config, image_url) or ""
        if not desc:
            suggested = "买家发来一张图片（未识别），请在闲鱼里查看原图。"
            await self._handoff(cid, msg, suggested, "买家发来图片（未识别）")
            return
        store.add_message(cid, "in", "sys", f"[图片识别] {desc}")
        store.log("info", f"图片识别完成（{nick}）：{desc[:60]}")
        if not self._rate_ok(cid):
            store.log("warn", f"{nick} 触发限频，图片本轮不回复")
            return
        delay = random.uniform(float(self.config.get("reply_delay_min", 2)),
                               float(self.config.get("reply_delay_max", 6)))
        await asyncio.sleep(delay)
        conv = store.get_conversation(cid)
        if not conv or conv["mode"] != "auto":
            return
        question = f"买家发来一张图片，图片内容是：{desc}"
        draft, need_human, note = await asyncio.to_thread(brain.answer, self.config, question)
        self._rate_mark(cid)
        if need_human or not draft:
            suggested = f"买家发来图片，识别内容：{desc}"
            await self._handoff(cid, msg, draft or suggested, f"图片消息转人工（{note}）")
        else:
            await self._send(cid, msg["buyer_id"], self._safe_text(draft),
                             sender="ai", nick=nick)

    async def _handoff(self, cid, msg, suggested, reason):
        nick = msg["nick"] or msg["buyer_id"]
        holding = self._safe_text(str(self.config.get("holding_text") or "这个我确认下"))
        sent = await self._send(cid, msg["buyer_id"], holding, sender="ai", nick=nick,
                                silent=True)
        if sent:
            store.set_conversation(cid, mode="handoff", needs_human=True, suggested=suggested or "")
        else:
            store.set_conversation(cid, mode="handoff", needs_human=True, suggested=suggested or "")
        store.log("warn", f"转人工 {nick}（{reason}）| 买家：{msg['text'][:50]}")
        notify.push(
            self.config,
            f"闲鱼需人工：{nick}",
            f"买家说：{msg['text']}\n\nAI 草稿参考：\n{suggested or '（无，请直接回复）'}\n\n"
            f"面板：http://127.0.0.1:{self.config['port']}/",
        )

    async def _on_late_reject(self, cid, text, reason):
        """迟到拦截回执：取消误记的送达，标记未送达并转人工。"""
        conv = store.get_conversation(cid)
        nick = (conv or {}).get("buyer_nick") or cid
        store.log("error", f"发送被闲鱼拦截（延迟回执）：{reason}（内容：{text[:40]}）")
        store.add_message(cid, "sys", "sys", f"这条回复被闲鱼拦截、未送达买家：{text}")
        store.set_conversation(cid, mode="handoff", needs_human=True, suggested=text)
        notify.push(
            self.config,
            f"闲鱼回复被拦截：{nick}",
            f"内容：{text}\n原因：{reason}\n\n请手动改词后发送。\n"
            f"面板：http://127.0.0.1:{self.config['port']}/",
        )

    async def _send(self, cid, toid, text, sender, nick="", silent=False):
        try:
            ok, detail = await self.client.send_text(cid, toid, text)
        except Exception as e:
            store.log("error", f"发送失败：{e}")
            return False
        if not ok:
            store.log("error", f"发送被闲鱼拦截：{detail}（内容：{text[:40]}）")
            store.add_message(cid, "sys", "sys", f"这条回复被闲鱼拦截、未送达买家：{text}")
            store.set_conversation(cid, mode="handoff", needs_human=True, suggested=text)
            notify.push(
                self.config,
                f"闲鱼回复被拦截：{nick or cid}",
                f"内容：{text}\n原因：{detail}\n\n请手动改词后发送。\n"
                f"面板：http://127.0.0.1:{self.config['port']}/",
            )
            return False
        store.add_message(cid, "out", sender, text)
        store.upsert_conversation(cid, last_text=text)
        if not silent:
            store.log("info", f"已回复 {nick or toid}：{text[:60]}")
        return True

    # ── 面板调用 ────────────────────────────────────────────
    def state(self):
        c = self.client
        return {
            "status": c.status,
            "nick": c.nick,
            "unb": c.myid,
            "auto_reply": bool(self.config.get("auto_reply")),
            "login_status": self.login.status,
            "login_message": self.login.message,
            "conversations": store.get_conversations(),
        }

    def send_manual(self, cid, text):
        text = (text or "").strip()
        if not text:
            return {"error": "内容为空"}
        conv = store.get_conversation(cid)
        if not conv or not conv.get("buyer_id"):
            return {"error": "会话不存在"}
        if not self.loop or not self.client.ws:
            return {"error": "消息通道未连接，请先扫码登录"}
        fut = asyncio.run_coroutine_threadsafe(
            self.client.send_text(cid, conv["buyer_id"], text), self.loop)
        try:
            ok, detail = fut.result(timeout=20)
        except Exception as e:
            return {"error": f"发送失败：{e}"}
        if not ok:
            store.log("error", f"人工发送被闲鱼拦截：{detail}")
            return {"error": f"被闲鱼拦截：{detail}"}
        store.add_message(cid, "out", "human", text)
        store.upsert_conversation(cid, last_text=text)
        store.set_conversation(cid, mode="manual", needs_human=False)
        store.log("info", f"人工回复 {conv.get('buyer_nick') or cid}：{text[:60]}")
        return {"ok": True}

    def set_mode(self, cid, mode):
        if mode not in ("auto", "manual", "handoff"):
            return {"error": "mode 不合法"}
        store.set_conversation(cid, mode=mode,
                               needs_human=(mode == "handoff"),
                               suggested="" if mode != "handoff" else None)
        return {"ok": True}

    def set_auto_reply(self, value):
        self.config["auto_reply"] = bool(value)
        save_config(self.config)
        store.log("info", f"自动回复总开关：{'开' if value else '关'}")
        return {"ok": True}

    def update_settings(self, data):
        for key in ("holding_text", "reply_delay_min", "reply_delay_max",
                    "max_replies_per_10min", "pushplus_token", "serverchan_key"):
            if key in data:
                self.config[key] = data[key]
        if "handoff_keywords" in data:
            kws = data["handoff_keywords"]
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.replace("，", ",").split(",") if k.strip()]
            self.config["handoff_keywords"] = kws
        soft = {}
        if "deepseek_api_key" in data:
            soft["llm_key"] = str(data.get("deepseek_api_key") or "").strip()
            self.config["deepseek_api_key"] = soft["llm_key"]
        if "kb_path" in data:
            soft["知识库"] = str(data.get("kb_path") or "").strip()
            self.config["kb_path"] = soft["知识库"]
        for vk in ("vision_base_url", "vision_key", "vision_model"):
            if vk in data:
                soft[vk] = str(data.get(vk) or "").strip()
                self.config[vk] = soft[vk]
        if soft:
            s = self._soft_load()
            s.update(soft)
            try:
                self._soft_cfg_path.write_text(
                    json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                store.log("error", f"软件配置写入失败：{e}")
        save_config({k: v for k, v in self.config.items()
                     if k not in ("deepseek_api_key", "kb_path",
                                  "vision_base_url", "vision_key", "vision_model")})
        store.log("info", "设置已保存")
        return {"ok": True}

    # ── 扫码登录 ────────────────────────────────────────────
    def start_qr(self):
        with self._lock:
            if (self._qr_thread and self._qr_thread.is_alive()
                    and self.login.status in ("starting", "NEW", "SCANNED")
                    and time.time() - self._qr_started_at < 100):
                return {"qr": True, "message": "二维码已生成"}
            login = QrLogin()
            try:
                login.start()
            except Exception as e:
                store.log("error", f"生成二维码失败：{e}")
                return {"error": str(e)}
            self.login = login
            self._qr_started_at = time.time()
            self._qr_thread = threading.Thread(target=self._qr_worker, args=(login,), daemon=True)
            self._qr_thread.start()
            return {"qr": True}

    def _qr_worker(self, login):
        while login is self.login and login.status in ("starting", "NEW", "SCANNED"):
            time.sleep(2.5)
            login.poll()
        if login is self.login and login.status == "CONFIRMED":
            self._reconnect()

    def _reconnect(self):
        async def restart():
            if self._client_task:
                self._client_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._client_task
            self.client = self._make_client()
            if self.client.load():
                self._client_task = asyncio.create_task(self.client.run_forever())
        if self.loop:
            asyncio.run_coroutine_threadsafe(restart(), self.loop)


def _single_instance_guard():
    global _lock_handle
    import msvcrt
    try:
        _lock_handle = open(DATA_DIR / "mlzs.lock", "a+")
        msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("已有实例在运行，本进程退出。")
        sys.exit(0)


_lock_handle = None


def main():
    global DATA_DIR
    shop = shopctx.parse_shop()
    DATA_DIR = shopctx.data_dir(shop)
    xy_protocol.set_session_file(DATA_DIR / "session.json")
    store.set_db_file(DATA_DIR / "assistant.db")
    _single_instance_guard()
    app = App()
    store.log("info", f"店铺 {shop} 启动（数据目录 {DATA_DIR}）")
    try:
        app.run()
    except KeyboardInterrupt:
        store.log("info", "程序退出")


if __name__ == "__main__":
    main()
