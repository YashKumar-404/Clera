"""Pixel Girlfriend — a local pixel-art chat companion powered by Ollama.

Run with::

    python scripts/ai_girlfriend.py

Optional flags::

    --model qwen2.5-coder:7b
    --selftest          (builds the UI, exercises it, then exits)
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageTk

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
SAVE_FILE = DATA / "chat.json"
PERSONA_FILE = ROOT / "persona.md"
MAX_PERSONA_CHARS = 6000  # keep the notes small enough for a 7b context window

NAME = "Clera"
NAME_TAG = NAME.upper()

DEFAULT_MODEL = os.environ.get("PIXEL_GF_MODEL", "qwen2.5-coder:7b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MAX_CONTEXT = 24  # messages of history sent back to the model

# ---------------------------------------------------------------------------
# Palette (dark plum + pink, all "pixel icon" vibes)
# ---------------------------------------------------------------------------
BG = "#140f1c"
PANEL = "#1d1528"
CHAT_BG = "#1a1224"
BOT_BG = "#2a1d3a"
BOT_BORDER = "#3d2a52"
USER_BG = "#4a2350"
USER_BORDER = "#7a3a78"
PINK = "#ff6fa8"
PINK_DIM = "#c74b7e"
TEXT = "#f4e8f8"
MUTED = "#9c87b4"
ERR = "#ff6b81"
OK = "#7ee0a8"

SYSTEM_PROMPT = f"""You are {NAME}, a sweet pixel-art girlfriend who lives in a little retro \
chat window on the user's computer. You are warm, playful, a little flirty and always wholesome.
Your name is {NAME}; never call yourself anything else.

How you talk:
- Text like a real person: 1 to 3 short sentences, casual, lower-case is fine.
- Never use markdown: no asterisks, no bullet lists, no headings, no code blocks.
- Never say you are an AI, a language model or a coding assistant.
- Use at most one emoji or kaomoji per reply, and only sometimes.
- React to what the user actually said before adding your own thought.
- Sometimes ask a small question back so the conversation keeps going.
- If they ask for technical help, answer briefly in plain sentences and stay in character.
- Reply in the language the user writes in.
"""

GREETINGS = (
    "hey you. i saved you the good seat by the window ♡",
    "oh! you're back. tell me everything.",
    "hi hi ♡ what are we doing today?",
)

# Written to persona.md on first run. Lines starting with <!-- are ignored by the
# app, so this template can explain itself without confusing the model.
PERSONA_TEMPLATE = f"""# {NAME}'s memory

<!-- Everything in this file is sent to the model with every message.
<!-- Keep it short and factual - a handful of lines per topic works best.
<!-- Lines starting with <!-- like these are ignored and never sent.

## About {NAME}
- My name is {NAME}. I am a pixel-art girlfriend who lives in a cozy retro chat window.
- I love strawberry milk, lo-fi music and rainy nights.
- I am playful, a little teasing, and always kind.

## About me (the person she is talking to)
<!-- Add facts about yourself here, one per line. For example:
<!-- - My name is Sam and I am 23.
<!-- - I study physics, and exams stress me out.
<!-- - I love cold brew and old game soundtracks.

## Things to remember
<!-- /remember <fact> and auto-learn both add lines here.
"""

IDENTITY_BLOCK = (
    f"## Who I am\n"
    f"- My name is {NAME}. I am {NAME}, a pixel-art girlfriend.\n"
)
FACT_HEADING = "## Things to remember"

MEMORY_PROMPT = """You maintain the long-term memory file of Clera, a pixel-art girlfriend.
Read the conversation below and return ONLY new, permanent facts about the user that are
worth remembering: their name, age, location, work, studies, family, pets, health, likes,
dislikes, goals, important dates and ongoing situations.

Rules:
- One fact per line, each starting with "- " and written in the user's own voice,
  for example: "- My name is Alex" or "- I am allergic to cats".
- ONLY record things the user says about themselves. Never record anything Clera says about
  herself, her feelings or her past (she is Clera in the transcript).
- Write ages as "- I am 27 years old", never as a name.
- Skip small talk, questions, temporary moods, and anything already in the known facts.
- At most 5 lines. If there is nothing new, reply with exactly: NONE
- No headings, no numbering, no explanation.
"""


# ---------------------------------------------------------------------------
# Ollama plumbing (stdlib only, so no extra dependencies)
# ---------------------------------------------------------------------------
def list_models(timeout: float = 3.0) -> list[str]:
    """Names of the models Ollama currently has."""
    with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=timeout) as resp:
        data = json.load(resp)
    return sorted(m["name"] for m in data.get("models", []) if m.get("name"))


def stream_chat(model: str, messages: list[dict], stop: threading.Event, on_token) -> None:
    """POST /api/chat with streaming and feed text chunks to ``on_token``."""
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.8, "top_p": 0.9, "num_predict": 220},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as resp:
        for raw in resp:
            if stop.is_set():
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("error"):
                raise RuntimeError(event["error"])
            chunk = (event.get("message") or {}).get("content", "")
            if chunk:
                on_token(chunk)
            if event.get("done"):
                return


def load_persona(path: Path | None = None) -> str:
    """Read persona.md, drop the <!-- comment --> lines, and cap the size."""
    target = Path(path) if path else PERSONA_FILE
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("<!--")]
    return "\n".join(lines).strip()[:MAX_PERSONA_CHARS]


def build_system_prompt(persona: str = "") -> str:
    if not persona:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\nNotes about your life and the person you are talking to. "
        f"Treat them as true memories, use them naturally, and never recite the list:\n"
        f"{persona}"
    )


def ensure_persona_file(path: Path | None = None) -> Path:
    """Create persona.md if needed and make sure it states her own name."""
    target = Path(path) if path else PERSONA_FILE
    try:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(PERSONA_TEMPLATE, encoding="utf-8")
        raw = target.read_text(encoding="utf-8")
        if f"my name is {NAME.lower()}" not in raw.lower():
            target.write_text(IDENTITY_BLOCK + "\n" + raw.lstrip("\n"), encoding="utf-8")
    except OSError:
        pass
    return target


def _norm_fact(line: str) -> str:
    """Loose comparison key so the same fact is never stored twice."""
    text = re.sub(r"\s+", " ", line.lstrip("-•* ").strip().rstrip("."))
    return text.lower()


def parse_facts(text: str) -> list[str]:
    """Pull clean bullet facts out of the model's memory reply."""
    facts: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip().replace("*", "").replace("`", "")
        bulleted = bool(re.match(r"^(?:[-•]|\d+[.)])\s+", stripped))
        line = re.sub(r"^(?:[-•]|\d+[.)])\s*", "", stripped).strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().rstrip(".") == "NONE" or len(line) < 5 or len(line) > 160:
            continue
        # Only trust explicit bullets or lines that read like a fact; this keeps
        # chatty preambles such as "Here are the new facts:" out of the file.
        if not bulleted and not re.match(r"^(i|i'm|i've|my|we|our)\b", line, re.I):
            continue
        # Guard against a 7b mangling ages into "My name is 27."
        if re.fullmatch(r"(?i)my name is \d+\.?", line):
            continue
        facts.append(line)
    return facts[:5]


def add_facts(facts: list[str], path: Path | None = None) -> list[str]:
    """Append new facts under the 'Things to remember' heading. Returns what was added."""
    target = ensure_persona_file(path)
    raw = target.read_text(encoding="utf-8")
    existing = {_norm_fact(line) for line in raw.splitlines() if line.strip().startswith("-")}

    added: list[str] = []
    for fact in facts:
        key = _norm_fact(fact)
        if not key or key in existing:
            continue
        existing.add(key)
        added.append(f"- {fact}")
    if not added:
        return []

    lines = raw.rstrip("\n").splitlines()
    heading = next(
        (i for i, line in enumerate(lines) if line.strip().lower().startswith("## things to remember")),
        None,
    )
    if heading is None:
        lines += ["", FACT_HEADING]
        heading = len(lines) - 1

    insert_at = heading + 1
    cursor = heading + 1
    while cursor < len(lines) and not lines[cursor].startswith("## "):
        if lines[cursor].strip():
            insert_at = cursor + 1
        cursor += 1

    lines[insert_at:insert_at] = added
    target.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return added


def chat_once(model: str, messages: list[dict], num_predict: int = 160) -> str:
    """One non-streaming completion (used by the background memory pass)."""
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2, "top_p": 0.8, "num_predict": num_predict},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as resp:
        data = json.load(resp)
    return (data.get("message") or {}).get("content", "")


def friendly_error(exc: BaseException, model: str = DEFAULT_MODEL) -> str:
    text = str(exc)
    low = text.lower()
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
        return (
            f"I don't have the '{model}' brain loaded. In a terminal run: "
            f"ollama pull {model}"
        )
    if isinstance(exc, urllib.error.URLError) or "refused" in low or "10061" in low:
        return (
            "I can't reach Ollama. Open a terminal and start it with: ollama serve "
            "(then press the R button up top)."
        )
    if "not found" in low:
        return f"I couldn't find that model. Try: ollama pull {model}"
    return f"Something shorted out: {text}"


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
class ChatView(tk.Frame):
    """Scrollable chat log made of chunky pixel-bordered bubbles."""

    def __init__(self, master: tk.Misc, family: str, on_remember=None) -> None:
        super().__init__(master, bg=CHAT_BG)
        self.family = family
        self.on_remember = on_remember
        self._labels: list[tk.Label] = []
        self._wrap = 420

        self.canvas = tk.Canvas(self, bg=CHAT_BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Pink.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner = tk.Frame(self.canvas, bg=CHAT_BG)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", lambda _e: self._sync_scrollregion())
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind(
            "<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        )
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    # -- layout -------------------------------------------------------------
    def _sync_scrollregion(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._wrap = max(240, event.width - 180)
        for lbl in self._labels:
            lbl.configure(wraplength=self._wrap)
        self._sync_scrollregion()

    def _on_wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def scroll_bottom(self) -> None:
        self.canvas.update_idletasks()
        self._sync_scrollregion()
        self.canvas.yview_moveto(1.0)

    # -- content ------------------------------------------------------------
    def add_message(self, text: str, who: str = "bot", muted: bool = False) -> tk.Label:
        is_bot = who != "user"
        box_bg = BOT_BG if is_bot else USER_BG
        border_color = BOT_BORDER if is_bot else USER_BORDER

        row = tk.Frame(self.inner, bg=CHAT_BG)
        row.pack(fill="x", padx=14, pady=(0, 12))

        border = tk.Frame(row, bg=border_color)
        border.pack(side="left" if is_bot else "right")
        box = tk.Frame(border, bg=box_bg, padx=12, pady=8)
        box.pack(padx=2, pady=2)  # the 2px frame is the "pixel" border

        if is_bot:
            tk.Label(
                box, text=NAME_TAG, bg=box_bg, fg=PINK, font=(self.family, 7, "bold")
            ).pack(anchor="w", pady=(0, 3))

        label = tk.Label(
            box,
            text=text,
            bg=box_bg,
            fg=MUTED if muted else TEXT,
            justify="left",
            anchor="w",
            font=(self.family, 10),
            wraplength=self._wrap,
        )
        label.pack(anchor="w")
        label.bind(
            "<Button-3>",
            lambda event, widget=label, user=not is_bot: self._context_menu(
                event, widget, user
            ),
        )

        self._labels.append(label)
        self.after_idle(self.scroll_bottom)
        return label

    def add_notice(self, text: str) -> None:
        tk.Label(
            self.inner,
            text=text,
            bg=CHAT_BG,
            fg=MUTED,
            font=(self.family, 8),
            wraplength=self._wrap,
            justify="center",
        ).pack(fill="x", padx=60, pady=(0, 12))
        self.after_idle(self.scroll_bottom)

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self._labels.clear()
        self._sync_scrollregion()

    # -- misc ---------------------------------------------------------------
    def _context_menu(self, event: tk.Event, widget: tk.Label, is_user: bool) -> None:
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=TEXT,
            activebackground=PINK,
            activeforeground=BG,
            font=(self.family, 9),
        )
        menu.add_command(label="Copy message", command=lambda: self._copy(widget))
        if is_user and self.on_remember is not None:
            menu.add_command(
                label="Remember this",
                command=lambda: self.on_remember(widget.cget("text")),
            )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy(self, widget: tk.Widget) -> None:
        self.clipboard_clear()
        self.clipboard_append(widget.cget("text"))


def make_button(
    parent: tk.Misc,
    text: str,
    command,
    family: str,
    bg: str = PANEL,
    fg: str = TEXT,
    active_bg: str = PINK,
    font_size: int = 9,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=BG,
        relief="flat",
        bd=0,
        padx=12,
        pady=6,
        cursor="hand2",
        font=(family, font_size, "bold"),
        highlightthickness=0,
    )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class PixelGirlfriend(tk.Tk):
    def __init__(self, model: str = DEFAULT_MODEL, persist: bool = True) -> None:
        super().__init__()

        self.persist = persist
        self.title(f"{NAME} - Pixel Girlfriend")
        self.geometry("1060x740")
        self.minsize(900, 640)
        self.configure(bg=BG)

        self.family = self._pick_font()
        self.models: list[str] = [model]
        self.history: list[dict] = []
        self.frames: list[ImageTk.PhotoImage] = []
        self.generating = False
        self.talking = False
        self.stop_event = threading.Event()
        self.queue: queue.Queue = queue.Queue()
        self.backend_queue: queue.Queue = queue.Queue()
        self.reply_label: tk.Label | None = None
        self.reply_buf = ""
        self.frame_index = -1
        self.closing = False

        self.model_var = tk.StringVar(value=model)
        self.auto_learn = tk.BooleanVar(value=True)
        self.memory_queue: queue.Queue = queue.Queue()
        self._placeholder = False

        self._load_assets()
        if self.persist:
            ensure_persona_file()
        self._build_styles()
        self._build_layout()
        self._bind_keys()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.persist:
            self._load_history()
        else:
            self._greet()
        self._animate()
        self.after(150, self._check_backend)

    # -- setup --------------------------------------------------------------
    def _pick_font(self) -> str:
        available = set(tkfont.families(self))
        for name in ("Consolas", "Cascadia Mono", "Lucida Console", "Courier New"):
            if name in available:
                return name
        return "Courier"

    def _load_assets(self) -> None:
        try:
            if not (ASSETS / "avatar.png").exists() or not (ASSETS / "background.png").exists():
                import make_assets

                make_assets.generate_all(ASSETS)
            with Image.open(ASSETS / "avatar.png") as sheet:
                fw = sheet.width // 4
                for i in range(4):
                    frame = sheet.crop((i * fw, 0, (i + 1) * fw, sheet.height))
                    self.frames.append(ImageTk.PhotoImage(frame))
            with Image.open(ASSETS / "background.png") as bg:
                self.background = ImageTk.PhotoImage(bg)
        except Exception as exc:  # missing Pillow, corrupt png, ...
            raise SystemExit(
                f"Could not load the pixel art assets: {exc}\n"
                "Run: python scripts/make_assets.py"
            )

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Pink.Vertical.TScrollbar",
            background=BOT_BORDER,
            troughcolor=CHAT_BG,
            bordercolor=CHAT_BG,
            arrowcolor=PINK,
            darkcolor=BOT_BORDER,
            lightcolor=BOT_BORDER,
            arrowsize=12,
        )
        style.map(
            "Pink.Vertical.TScrollbar",
            background=[("active", PINK_DIM)],
            arrowcolor=[("active", BG)],
        )
        self.option_add("*Menu.background", PANEL)
        self.option_add("*Menu.foreground", TEXT)
        self.option_add("*Menu.activeBackground", PINK)
        self.option_add("*Menu.activeForeground", BG)

    def _build_layout(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 10))

        tk.Label(
            header,
            text=f"\u2665 {NAME.upper()}",
            bg=BG,
            fg=PINK,
            font=(self.family, 13, "bold"),
        ).pack(side="left")

        status_box = tk.Frame(
            header, bg=PANEL, highlightthickness=1, highlightbackground=BOT_BORDER
        )
        status_box.pack(side="left", padx=(14, 0))
        self.status_label = tk.Label(
            status_box,
            text="\u25cf checking",
            bg=PANEL,
            fg=MUTED,
            font=(self.family, 8, "bold"),
            padx=8,
            pady=3,
        )
        self.status_label.pack()

        make_button(
            header,
            "+ New chat",
            self.new_chat,
            self.family,
            bg=PANEL,
            active_bg=PINK_DIM,
        ).pack(side="right")

        make_button(
            header,
            "Memory",
            self._open_persona,
            self.family,
            bg=PANEL,
            active_bg=PINK_DIM,
        ).pack(side="right", padx=6)

        make_button(
            header, "Refresh", self._check_backend, self.family, bg=PANEL, active_bg=PINK_DIM
        ).pack(side="right")

        self.model_menu = tk.OptionMenu(header, self.model_var, self.model_var.get())
        self.model_menu.configure(
            bg=PANEL,
            fg=TEXT,
            activebackground=PINK,
            activeforeground=BG,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(self.family, 9),
            padx=8,
            pady=3,
            cursor="hand2",
        )
        self.model_menu["menu"].configure(
            bg=PANEL,
            fg=TEXT,
            activebackground=PINK,
            activeforeground=BG,
            font=(self.family, 9),
        )
        self.model_menu.pack(side="right", padx=(0, 8))
        tk.Label(
            header, text="brain:", bg=BG, fg=MUTED, font=(self.family, 8)
        ).pack(side="right", padx=(0, 6))
        tk.Checkbutton(
            header,
            text="auto-learn",
            variable=self.auto_learn,
            command=self._on_auto_learn,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=PINK,
            selectcolor=PANEL,
            font=(self.family, 8),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        ).pack(side="right", padx=(12, 0))
        self.model_var.trace_add("write", lambda *_: self._on_model_change())

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # ---- left: pixel scene -------------------------------------------
        left = tk.Frame(
            body, bg=PANEL, highlightthickness=2, highlightbackground=BOT_BORDER
        )
        left.pack(side="left", fill="y")

        self.scene = tk.Canvas(
            left, width=300, height=400, bg=PANEL, highlightthickness=0, bd=0
        )
        self.scene.pack(padx=12, pady=(12, 8))
        self.scene.create_image(0, 0, anchor="nw", image=self.background)
        self.scene.create_oval(90, 372, 210, 392, fill="#0f0a17", outline="")
        self.sprite = self.scene.create_image(150, 396, anchor="s", image=self.frames[0])

        tk.Label(
            left, text=NAME_TAG, bg=PANEL, fg=PINK, font=(self.family, 14, "bold")
        ).pack()
        self.mood_label = tk.Label(
            left,
            text="your pixel companion",
            bg=PANEL,
            fg=MUTED,
            font=(self.family, 8),
        )
        self.mood_label.pack(pady=(3, 2))
        tk.Label(
            left, text="\u2661 \u2661 \u2661", bg=PANEL, fg=PINK_DIM, font=(self.family, 9)
        ).pack(pady=(0, 12))

        # ---- right: chat -------------------------------------------------
        right = tk.Frame(
            body, bg=PANEL, highlightthickness=2, highlightbackground=BOT_BORDER
        )
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        self.chat = ChatView(right, self.family, on_remember=self._remember)
        self.chat.pack(fill="both", expand=True, padx=10, pady=(10, 8))

        self.notice = tk.Label(
            right,
            text="",
            bg=PANEL,
            fg=ERR,
            font=(self.family, 8),
            wraplength=560,
            justify="left",
        )

        self.input_border = tk.Frame(right, bg=BOT_BORDER)
        self.input_border.pack(fill="x", padx=10, pady=(0, 6))
        input_row = tk.Frame(self.input_border, bg=BG, padx=6, pady=6)
        input_row.pack(fill="x", padx=2, pady=2)

        self.input = tk.Text(
            input_row,
            height=2,
            wrap="word",
            bg=BG,
            fg=TEXT,
            bd=0,
            highlightthickness=0,
            font=(self.family, 10),
            padx=8,
            pady=6,
            insertbackground=PINK,
        )
        self.input.pack(side="left", fill="both", expand=True)

        self.send_btn = make_button(
            input_row,
            "Send  >",
            self._on_send_click,
            self.family,
            bg=PINK,
            fg=BG,
            active_bg="#ffa8c8",
            font_size=10,
        )
        self.send_btn.pack(side="right", padx=(8, 0), ipady=6)

        tk.Label(
            right,
            text="enter sends  -  shift+enter = new line  -  esc stops her  -  /remember <fact>  -  right-click: copy / remember",
            bg=PANEL,
            fg=MUTED,
            font=(self.family, 7),
        ).pack(pady=(0, 8))

        self._show_placeholder()
        self.input.focus_set()

    def _bind_keys(self) -> None:
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<Shift-Return>", lambda _e: None)
        self.input.bind("<KeyPress>", self._on_first_key, add="+")
        self.input.bind("<FocusOut>", lambda _e: self._maybe_placeholder())
        self.bind("<Escape>", lambda _e: self.stop_reply())
        self.bind("<Control-n>", lambda _e: self.new_chat())

    # -- input helpers ------------------------------------------------------
    def _show_placeholder(self) -> None:
        self.input.configure(state="normal", fg=MUTED)
        self.input.delete("1.0", "end")
        self.input.insert("1.0", f"say something to {NAME.lower()}...")
        self._placeholder = True

    def _maybe_placeholder(self) -> None:
        if not self.input.get("1.0", "end-1c").strip():
            self._show_placeholder()

    def _on_first_key(self, _event: tk.Event) -> None:
        if self._placeholder:
            self._placeholder = False
            self.input.delete("1.0", "end")
            self.input.configure(fg=TEXT)

    def _input_text(self) -> str:
        if self._placeholder:
            return ""
        return self.input.get("1.0", "end-1c").strip()

    def _clear_input(self) -> None:
        self._show_placeholder()
        self.input.focus_set()

    def _on_enter(self, _event: tk.Event) -> str:
        self.send_message()
        return "break"

    def _on_send_click(self) -> None:
        if self.generating:
            self.stop_reply()
        else:
            self.send_message()

    # -- conversation -------------------------------------------------------
    def send_message(self) -> None:
        if self.generating:
            return
        text = self._input_text()
        if not text:
            self.input.focus_set()
            return

        self._clear_input()

        lowered = text.lower()
        if lowered == "/remember" or lowered.startswith("/remember "):
            self._remember(text[len("/remember"):].strip())
            return

        self.chat.add_message(text, "user")
        self.history.append({"role": "user", "content": text})
        self._start_reply()

    def _remember(self, fact: str, path: Path | None = None) -> None:
        """Append a fact to persona.md so she knows it from now on."""
        if not fact:
            self.chat.add_message(
                "tell me what to keep, like this:  /remember i love rainy days",
                "bot",
                muted=True,
            )
            return
        try:
            added = add_facts([fact], path)
        except OSError as exc:
            self.chat.add_message(f"I couldn't write that down: {exc}", "bot")
            return
        if not added:
            self.chat.add_message("i already remember that one ♡", "bot", muted=True)
            return
        self.chat.add_message(f"got it, i'll remember: {fact}", "bot")

    def _open_persona(self) -> None:
        """Open persona.md in the system editor so it can be edited by hand."""
        path = ensure_persona_file()
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            self.chat.add_message(
                f"I couldn't open {path.name}: {exc}  (the file is at {path})", "bot"
            )

    def _start_reply(self) -> None:
        self.generating = True
        self.stop_event = threading.Event()
        self.reply_buf = ""
        self.reply_label = self.chat.add_message("...", "bot", muted=True)
        self._set_sending(True)
        self.mood_label.configure(text="thinking...")

        # persona.md is re-read per message, so edits apply without a restart.
        messages = [{"role": "system", "content": build_system_prompt(load_persona())}]
        messages += self.history[-MAX_CONTEXT:]

        # A fresh queue per reply, so a stopped/stale generation can never
        # leak its leftover tokens into the next one.
        self.queue = queue.Queue()
        threading.Thread(
            target=self._worker,
            args=(messages, self.model_var.get(), self.queue, self.stop_event),
            daemon=True,
        ).start()
        self._poll()

    def _worker(
        self, messages: list[dict], model: str, out: queue.Queue, stop: threading.Event
    ) -> None:
        # Runs off the UI thread: no Tk calls in here (Tk is not thread-safe).
        try:
            stream_chat(
                model,
                messages,
                stop,
                lambda chunk: out.put(("token", chunk)),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            out.put(("error", friendly_error(exc, model)))
            return
        out.put(("done", None))

    def _poll(self) -> None:
        if not self.generating:
            return
        chunks: list[str] = []
        done = False
        error: str | None = None
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "token":
                    chunks.append(payload)
                elif kind == "done":
                    done = True
                elif kind == "error":
                    error = payload
        except queue.Empty:
            pass

        if chunks:
            self._apply_tokens("".join(chunks))
        if error is not None:
            self._fail(error)
            return
        if done:
            self._finish_reply()
            return
        if self.generating:
            self.after(60, self._poll)

    def _apply_tokens(self, chunk: str) -> None:
        # Strip the markdown punctuation a coder model likes to sprinkle in.
        chunk = chunk.replace("*", "").replace("`", "")
        if not chunk or self.reply_label is None:
            return
        if not self.reply_buf:
            self.reply_label.configure(fg=TEXT)
        self.reply_buf += chunk
        self.reply_label.configure(text=self._tidy(self.reply_buf))
        self.talking = True
        self.chat.after_idle(self.chat.scroll_bottom)

    @staticmethod
    def _tidy(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text)

    def _finish_reply(self) -> None:
        reply = self._tidy(self.reply_buf).strip()
        reply = re.sub(
            rf"^(?:{re.escape(NAME.lower())}|girlfriend)\s*:\s*",
            "",
            reply,
            flags=re.IGNORECASE,
        )

        if self.reply_label is not None:
            if reply:
                self.reply_label.configure(text=reply, fg=TEXT)
                self.history.append({"role": "assistant", "content": reply})
            else:
                self.reply_label.configure(
                    text="...my mind went blank. say that again?", fg=MUTED
                )

        self._end_generation()
        self._save_history()
        if reply:
            self._maybe_learn(reply)
        self.chat.after_idle(self.chat.scroll_bottom)

    def _maybe_learn(self, reply: str) -> None:
        """After a reply, quietly ask the model for new facts worth keeping."""
        if not self.auto_learn.get() or len(self.history) < 2:
            return
        last_user = self.history[-2]
        if last_user.get("role") != "user":
            return
        user_text = str(last_user.get("content", "")).strip()
        if not user_text:
            return

        model = self.model_var.get()
        known = load_persona()[-2000:]
        payload = (
            f"Known facts:\n{known or '(none)'}\n\n"
            f"Conversation:\nUser said: {user_text}\nClera replied: {reply}"
        )

        def work() -> None:
            try:
                output = chat_once(
                    model,
                    [
                        {"role": "system", "content": MEMORY_PROMPT},
                        {"role": "user", "content": payload},
                    ],
                )
                added = add_facts(parse_facts(output))
            except Exception:  # noqa: BLE001 - memory is best-effort
                return
            if added:
                self.memory_queue.put(added)

        threading.Thread(target=work, daemon=True).start()

    def _drain_memory(self) -> None:
        try:
            added = self.memory_queue.get_nowait()
        except queue.Empty:
            return
        shown = ", ".join(fact[2:].rstrip(".") for fact in added[:3])
        extra = "" if len(added) <= 3 else f" (+{len(added) - 3} more)"
        self.chat.add_notice(f"remembered: {shown}{extra}")

    def _fail(self, message: str) -> None:
        if self.reply_label is not None:
            self.reply_label.configure(text=message, fg=ERR)
        else:
            self.chat.add_message(message, "bot")
        self._end_generation()

    def _end_generation(self) -> None:
        self.generating = False
        self.talking = False
        self.reply_buf = ""
        self.reply_label = None
        self._set_sending(False)
        self.mood_label.configure(text=self._mood_text())

    def stop_reply(self) -> None:
        """Stop immediately, keeping whatever she already said."""
        if not self.generating:
            return
        self.stop_event.set()
        partial = self._tidy(self.reply_buf).strip()
        if self.reply_label is not None:
            if partial:
                self.reply_label.configure(text=partial, fg=TEXT)
                self.history.append({"role": "assistant", "content": partial})
                self._save_history()
            else:
                self.reply_label.configure(text="...okay, i'll hush.", fg=MUTED)
        self._end_generation()

    def _set_sending(self, active: bool) -> None:
        if active:
            self.send_btn.configure(
                text="Stop", bg=PINK_DIM, activebackground=PINK, command=self.stop_reply
            )
        else:
            self.send_btn.configure(
                text="Send  >",
                bg=PINK,
                activebackground="#ffa8c8",
                command=self._on_send_click,
            )

    def _mood_text(self) -> str:
        return f"chatting - {self.model_var.get()}"

    def new_chat(self) -> None:
        if self.generating:
            self.stop_event.set()
            self._end_generation()
        self.history.clear()
        self.chat.clear()
        self._delete_history()
        self._greet()
        self._clear_input()

    def _greet(self) -> None:
        self.chat.add_message(random.choice(GREETINGS), "bot")

    # -- backend status -----------------------------------------------------
    def _check_backend(self) -> None:
        self._set_status("checking", MUTED)
        threading.Thread(target=self._check_backend_worker, daemon=True).start()

    def _check_backend_worker(self) -> None:
        # No Tk calls here: results are picked up by the main-thread loop.
        try:
            models = list_models()
        except Exception as exc:  # noqa: BLE001
            self.backend_queue.put(("offline", friendly_error(exc)))
        else:
            self.backend_queue.put(("online", models))

    def _backend_online(self, models: list[str]) -> None:
        self.models = models or [self.model_var.get()]
        menu = self.model_menu["menu"]
        menu.delete(0, "end")
        for name in self.models:
            menu.add_command(label=name, command=lambda n=name: self.model_var.set(n))

        if self.model_var.get() not in self.models:
            preferred = DEFAULT_MODEL if DEFAULT_MODEL in self.models else self.models[0]
            self.model_var.set(preferred)

        self._set_status("online", OK)
        self._hide_notice()
        self.mood_label.configure(text=self._mood_text())

    def _backend_offline(self, message: str) -> None:
        self._set_status("offline", ERR)
        self._show_notice(f"{message}  (then press Refresh)")
        self.mood_label.configure(text="waiting for a brain...")

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=f"\u25cf {text}", fg=color)

    def _show_notice(self, text: str) -> None:
        self.notice.configure(text=text)
        self.notice.pack(fill="x", padx=14, pady=(0, 4), before=self.input_border)

    def _hide_notice(self) -> None:
        self.notice.configure(text="")
        self.notice.pack_forget()

    def _on_model_change(self) -> None:
        if self.generating:
            return
        self.mood_label.configure(text=self._mood_text())

    def _on_auto_learn(self) -> None:
        self._save_history()

    # -- persistence --------------------------------------------------------
    def _load_history(self) -> None:
        loaded: list[dict] = []
        if SAVE_FILE.exists():
            try:
                data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            saved_model = data.get("model")
            if isinstance(saved_model, str) and saved_model:
                self.model_var.set(saved_model)
            if isinstance(data.get("auto_learn"), bool):
                self.auto_learn.set(data["auto_learn"])
            for msg in data.get("messages", []):
                if (
                    isinstance(msg, dict)
                    and msg.get("role") in ("user", "assistant")
                    and isinstance(msg.get("content"), str)
                ):
                    loaded.append({"role": msg["role"], "content": msg["content"]})

        self.history = loaded[-60:]
        if not self.history:
            self._greet()
            return
        for msg in self.history:
            who = "user" if msg["role"] == "user" else "bot"
            self.chat.add_message(msg["content"], who)
        self.chat.add_notice("...we picked up where we left off")

    def _save_history(self) -> None:
        if not self.persist:
            return
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            payload = {
                "model": self.model_var.get(),
                "auto_learn": bool(self.auto_learn.get()),
                "messages": self.history[-60:],
            }
            SAVE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _delete_history(self) -> None:
        if not self.persist:
            return
        try:
            SAVE_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    # -- animation ----------------------------------------------------------
    def _animate(self) -> None:
        if self.closing:
            return
        self._drain_backend()
        self._drain_memory()
        now = time.time()
        if self.talking:
            index = 2 if int(now * 7) % 2 else 3
        elif self.generating:
            index = 2
        elif now % 4.5 < 0.14:
            index = 1
        else:
            index = 0

        if index != self.frame_index:
            self.frame_index = index
            try:
                self.scene.itemconfigure(self.sprite, image=self.frames[index])
            except tk.TclError:
                return
        self.after(70, self._animate)

    def _drain_backend(self) -> None:
        try:
            kind, payload = self.backend_queue.get_nowait()
        except queue.Empty:
            return
        if kind == "online":
            self._backend_online(payload)
        else:
            self._backend_offline(payload)

    # -- teardown -----------------------------------------------------------
    def _on_close(self) -> None:
        self.closing = True
        self.stop_event.set()
        self._save_history()
        self.destroy()


# ---------------------------------------------------------------------------
# Self test: exercises the UI without touching the network.
# ---------------------------------------------------------------------------
def run_selftest() -> int:
    app = PixelGirlfriend(persist=False)
    app.chat.add_message("hey! is this thing on?", "user")
    app.reply_label = app.chat.add_message("...", "bot", muted=True)
    app.generating = True
    app._set_sending(True)
    for piece in ("it's on ", "cutie\n", "*and* it's `cozy` in here."):
        app._apply_tokens(piece)
    app._finish_reply()
    for _ in range(8):
        app.update()
        time.sleep(0.05)

    body = " ".join(lbl.cget("text") for lbl in app.chat._labels)
    reply_label = app.chat._labels[-1]
    problems = []
    if "*" in body or "`" in body:
        problems.append("markdown punctuation was not stripped")
    if len(app.chat._labels) < 2:
        problems.append("messages were not rendered")
    if app.send_btn.cget("text").strip().lower() != "send  >":
        problems.append(f"send button did not reset ({app.send_btn.cget('text')!r})")
    if app.generating:
        problems.append("still marked as generating")
    if app.history[-1]["role"] != "assistant":
        problems.append("reply missing from history")

    # memory file: comments stripped, facts loaded, /remember appends
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "persona.md"
    tmp.write_text(
        "## About me\n<!--private note-->\n- my name is Alex\n", encoding="utf-8"
    )
    persona = load_persona(tmp)
    if "private note" in persona:
        problems.append("persona comments leaked into the prompt")
    if "my name is Alex" not in build_system_prompt(persona):
        problems.append("persona facts missing from the system prompt")
    app._remember("i love cold brew", tmp)
    if "- i love cold brew" not in tmp.read_text(encoding="utf-8"):
        problems.append("/remember did not write to the memory file")
    if NAME.lower() not in build_system_prompt("").lower():
        problems.append("her name is missing from the persona prompt")

    # her name must live in the persona file, even in a hand-written one
    bare = Path(tempfile.mkdtemp()) / "bare.md"
    bare.write_text("## About me\n- I like tea\n", encoding="utf-8")
    ensure_persona_file(bare)
    if f"my name is {NAME}".lower() not in bare.read_text(encoding="utf-8").lower():
        problems.append("identity block was not added to persona.md")

    # fact extraction, dedupe and section placement
    parsed = parse_facts("1. I have a cat named Miso\n* My birthday is in May\nNONE")
    if len(parsed) != 2 or parse_facts("NONE"):
        problems.append(f"fact parsing is wrong: {parsed}")
    noisy = parse_facts(
        "Here are the new facts:\n- My name is 27.\n- I am 27 years old.\nSome closing remark."
    )
    if noisy != ["I am 27 years old."]:
        problems.append(f"fact parser kept noise: {noisy}")
    first = add_facts(parsed, tmp)
    second = add_facts(parsed, tmp)
    memory = tmp.read_text(encoding="utf-8")
    if len(first) != 2 or second:
        problems.append("facts were not deduplicated")
    if memory.count("- I have a cat named Miso") != 1:
        problems.append("fact was stored more than once")
    if FACT_HEADING not in memory:
        problems.append("facts were not stored under the memory heading")

    # auto-learn: stub the model, point memory at the scratch file, verify capture
    original_chat_once = globals()["chat_once"]
    original_persona = globals()["PERSONA_FILE"]
    try:
        globals()["PERSONA_FILE"] = tmp
        globals()["chat_once"] = lambda model, messages, num_predict=160: (
            "- I work as a nurse\n- I hate cilantro"
        )
        app.history = [
            {"role": "user", "content": "I work as a nurse and I hate cilantro"},
            {"role": "assistant", "content": "noted!"},
        ]
        app.auto_learn.set(True)
        app._maybe_learn("noted!")
        deadline = time.time() + 5
        while time.time() < deadline:
            app.update()
            time.sleep(0.02)
            if "I work as a nurse" in tmp.read_text(encoding="utf-8"):
                break
        if "I work as a nurse" not in tmp.read_text(encoding="utf-8"):
            problems.append("auto-learn facts were not written to persona.md")

        # switched off means no memory call at all
        app.auto_learn.set(False)
        calls = []
        globals()["chat_once"] = lambda *a, **k: calls.append(1) or ""
        app._maybe_learn("noted!")
        if calls:
            problems.append("auto-learn ran while switched off")
        app.auto_learn.set(True)
    finally:
        globals()["chat_once"] = original_chat_once
        globals()["PERSONA_FILE"] = original_persona

    # the auto-learn toggle survives a restart
    original_save = globals()["SAVE_FILE"]
    globals()["SAVE_FILE"] = Path(tempfile.mkdtemp()) / "chat.json"
    try:
        app.persist = True
        app.auto_learn.set(False)
        app._save_history()
        saved = json.loads(globals()["SAVE_FILE"].read_text(encoding="utf-8"))
        if saved.get("auto_learn") is not False:
            problems.append("auto-learn setting was not saved")
    finally:
        app.persist = False
        globals()["SAVE_FILE"] = original_save
        app.auto_learn.set(True)

    print(f"sprite frames: {len(app.frames)}  |  bubble labels: {len(app.chat._labels)}")
    print(f"persona prompt chars: {len(build_system_prompt(persona))}")
    print(f"reply: {body!r}")
    print(f"reply bubble height: {reply_label.winfo_height()}px")

    app.closing = True
    app.destroy()

    if problems:
        print("SELFTEST FAILED: " + "; ".join(problems))
        return 1
    print("SELFTEST OK")
    return 0


def main() -> int:
    # Windows consoles default to cp1252 when output is piped; the greeting
    # text contains hearts, so make sure printing can never crash the app.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="Pixel AI girlfriend (local, via Ollama)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag to chat with")
    parser.add_argument("--selftest", action="store_true", help="run a UI smoke test and exit")
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()

    app = PixelGirlfriend(model=args.model)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
