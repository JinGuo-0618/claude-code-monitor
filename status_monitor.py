import tkinter as tk
import json
import os
import sys
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

STATUS_FILE = Path.home() / ".claude" / "status.json"
LOG_FILE = Path.home() / ".claude" / "status_log.jsonl"


# ── Tiny hook server ────────────────────────────────────────────────

class HookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        status_map = {
            "/api/green":   ("idle",    ""),
            "/api/working": ("working", ""),
            "/api/waiting": ("waiting", "等待确认"),
            "/api/done":    ("idle",    ""),
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
        pass


def start_hook_server(port=17322):
    try:
        server = HTTPServer(("127.0.0.1", port), HookHandler)
        server.serve_forever()
    except OSError:
        pass  # port already in use


# ── Monitor UI ──────────────────────────────────────────────────────

class StatusMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Claude Code Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"200x68+{sw - 210}+10")

        self.colors = {
            "idle": "#4CAF50",
            "thinking": "#FF9800",
            "working": "#2196F3",
            "waiting": "#F44336",
            "error": "#F44336",
            "offline": "#757575",
        }
        self.labels = {
            "idle": "就绪",
            "thinking": "思考中...",
            "working": "执行中...",
            "waiting": "等待确认",
            "error": "出错",
            "offline": "未连接",
        }
        self.tool_icons = {
            "Read": "📖",
            "Write": "✏️",
            "Edit": "🔧",
            "Bash": "⚡",
            "Grep": "🔍",
            "Glob": "📁",
            "Agent": "🤖",
            "WebFetch": "🌐",
            "WebSearch": "🔎",
            "TaskCreate": "📋",
            "TaskUpdate": "✅",
            "Skill": "🛠️",
        }

        self._build_ui()
        self._bind_events()

        # Start hook server in background
        threading.Thread(target=start_hook_server, args=(17323,), daemon=True).start()

        self.current_status = "offline"
        self.current_tool = ""
        self.activity_log = []
        self.pulse_phase = 0

        self.poll_status()
        self.root.mainloop()

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        self.frame = tk.Frame(self.root, bg="#161616", bd=1,
                              highlightbackground="#333333",
                              highlightthickness=1)
        self.frame.pack(fill=tk.BOTH, expand=True)

        # Header bar
        header = tk.Frame(self.frame, bg="#202020", height=22)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        self.title_lbl = tk.Label(
            header, text="Claude Code Monitor", fg="#888888",
            bg="#202020", font=("Consolas", 7))
        self.title_lbl.pack(side=tk.LEFT, padx=6)

        self.time_lbl = tk.Label(
            header, text="", fg="#666666", bg="#202020",
            font=("Consolas", 7))
        self.time_lbl.pack(side=tk.RIGHT, padx=6)

        # Body
        body = tk.Frame(self.frame, bg="#161616")
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 6))

        # Status dot + label row
        dot_row = tk.Frame(body, bg="#161616")
        dot_row.pack(fill=tk.X)

        self.canvas = tk.Canvas(dot_row, width=10, height=10,
                                bg="#161616", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, padx=(0, 6))
        self.dot = self.canvas.create_oval(
            0, 1, 10, 11, fill=self.colors["offline"], outline="")

        self.status_lbl = tk.Label(
            dot_row, text=self.labels["offline"], fg="#CCCCCC",
            bg="#161616", font=("Microsoft YaHei", 10, "bold"))
        self.status_lbl.pack(side=tk.LEFT)

        # Tool detail row
        self.detail_lbl = tk.Label(
            body, text="", fg="#777777", bg="#161616",
            font=("Consolas", 8), anchor=tk.W)
        self.detail_lbl.pack(fill=tk.X, pady=(1, 0))

    # ── Window dragging ──────────────────────────────────────────────

    def _bind_events(self):
        for w in (self.frame, self.canvas, self.status_lbl,
                  self.detail_lbl, self.title_lbl, self.time_lbl):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        self.frame.bind("<Button-3>", self._context_menu)
        self.menu = tk.Menu(self.root, tearoff=0,
                            bg="#252525", fg="#CCCCCC",
                            activebackground="#3A3A3A", activeforeground="#FFFFFF",
                            font=("Microsoft YaHei", 9))
        self.menu.add_command(label="退出监控", command=self.root.quit)

    def _start_drag(self, event):
        self._dx = event.x_root
        self._dy = event.y_root

    def _on_drag(self, event):
        x = self.root.winfo_x() + (event.x_root - self._dx)
        y = self.root.winfo_y() + (event.y_root - self._dy)
        self.root.geometry(f"+{x}+{y}")
        self._dx = event.x_root
        self._dy = event.y_root

    def _context_menu(self, event):
        self.menu.post(event.x_root, event.y_root)

    # ── Status polling ───────────────────────────────────────────────

    def poll_status(self):
        status = "offline"
        detail = ""
        tool = ""

        try:
            if STATUS_FILE.exists():
                raw = STATUS_FILE.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    status = data.get("status", "offline")
                    detail = data.get("detail", "")
                    tool = data.get("tool", "")
        except Exception:
            status = "offline"

        # Update UI on change
        if status != self.current_status or tool != self.current_tool:
            self.current_status = status
            self.current_tool = tool
            color = self.colors.get(status, self.colors["offline"])
            self.canvas.itemconfig(self.dot, fill=color)
            self.status_lbl.config(
                text=self.labels.get(status, status), fg=color)

            if detail:
                icon = self.tool_icons.get(tool, "")
                self.detail_lbl.config(text=f"{icon} {detail}")
            else:
                self.detail_lbl.config(text="")

        # Pulsing dot for thinking/working
        if status in ("thinking", "working", "waiting"):
            self.pulse_phase = (self.pulse_phase + 1) % 20
            r = 5 - abs(self.pulse_phase - 10) * 0.3
            if r < 3:
                r = 3
            self.canvas.coords(self.dot, 5 - r, 6 - r, 5 + r, 6 + r)
        else:
            self.canvas.coords(self.dot, 0, 1, 10, 11)

        now = datetime.now().strftime("%H:%M")
        self.time_lbl.config(text=now)

        self.root.after(400, self.poll_status)


# ── Launch ───────────────────────────────────────────────────────────

def launch_detached():
    """Launch the monitor in a detached background process."""
    script = Path(__file__).resolve()
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen(
            [str(pythonw), str(script), "--foreground"],
            creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen(
            [sys.executable, str(script), "--foreground"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--foreground":
        StatusMonitor()
    else:
        launch_detached()
        print("Monitor launched (PID shown above). It will auto-connect.")
