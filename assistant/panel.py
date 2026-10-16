# -*- coding: utf-8 -*-
"""闲鱼助手 · 本地网页面板（127.0.0.1）"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import order_stats
import store

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "web" / "index.html"
APP = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_OPTIONS(self):
        self._send(204, "text/plain", b"")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", INDEX.read_bytes())
        elif u.path == "/status":
            cfg = APP.config
            self._json(200, {
                "ok": True,
                "shop": cfg.get("shop", ""),
                "display": cfg.get("display_name", ""),
                "port": cfg.get("port", 8767),
                "auto_reply": bool(cfg.get("auto_reply")),
                "client_status": APP.client.status,
                "login_status": APP.login.status,
                "conversations": len(store.get_conversations() or []),
            })
        elif u.path == "/api/order-stats":
            try:
                force = "refresh" in q
                self._json(200, {"ok": True, "has_data": True,
                                 **order_stats.fetch(force=force)})
            except Exception as e:
                self._json(200, {"ok": False, "has_data": False, "error": str(e)})
        elif u.path == "/api/state":
            self._json(200, APP.state())
        elif u.path == "/api/settings":
            self._json(200, APP.config)
        elif u.path == "/api/messages":
            cid = (q.get("cid") or [""])[0]
            self._json(200, {"messages": store.get_messages(cid)})
        elif u.path == "/api/logs":
            after = int((q.get("after") or ["0"])[0])
            self._json(200, {"logs": store.get_logs(after)})
        elif u.path == "/api/login/qr.png":
            if not APP.login.qr_url:
                self._send(404, "text/plain", b"no qr")
            else:
                try:
                    self._send(200, "image/png", APP.login.qr_png())
                except Exception as e:
                    self._json(500, {"error": str(e)})
        elif u.path == "/api/login/status":
            self._json(200, {"status": APP.login.status, "message": APP.login.message,
                             "account": APP.login.account})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            data = self._body()
        except Exception as e:
            self._json(400, {"error": f"请求格式错误: {e}"})
            return
        u = urlparse(self.path)
        if u.path == "/api/send":
            self._json(200, APP.send_manual(data.get("cid", ""), data.get("text", "")))
        elif u.path == "/api/mode":
            self._json(200, APP.set_mode(data.get("cid", ""), data.get("mode", "")))
        elif u.path == "/api/toggle":
            self._json(200, APP.set_auto_reply(data.get("value", False)))
        elif u.path == "/api/settings":
            self._json(200, APP.update_settings(data))
        elif u.path == "/api/login/start":
            self._json(200, APP.start_qr())
        else:
            self._json(404, {"error": "not found"})


def serve(app):
    global APP
    APP = app
    port = int(app.config.get("port", 8767))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.serve_forever()
