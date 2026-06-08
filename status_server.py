"""Tiny HTTP server that receives Claude Code hook events and writes status.json."""
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

STATUS_FILE = Path.home() / ".claude" / "status.json"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        status_map = {
            "/api/green":   ("idle",      ""),
            "/api/working": ("working",   ""),
            "/api/waiting": ("waiting",   "等待确认"),
            "/api/done":    ("idle",      ""),
        }
        state, extra = status_map.get(self.path, ("offline", ""))
        payload = {"status": state, "detail": extra, "tool": ""}

        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            body = json.loads(self.rfile.read(content_len))
            if body.get("tool_name"):
                payload["tool"] = body["tool_name"]
            if body.get("tool_input"):
                detail = str(body["tool_input"])
                if len(detail) > 60:
                    detail = detail[:57] + "..."
                payload["detail"] = detail

        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress logs


def serve(port=17322):
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    # Keep alive
    while True:
        time.sleep(60)
