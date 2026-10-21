# Clera ♥

A cozy, pixel-art chat companion that runs **100% on your own PC**. She is powered by a
local [Ollama](https://ollama.com) model, so nothing you type ever leaves your computer.

- Animated pixel-art sprite (idle, blinking, talking) drawn procedurally — no external art needed.
- Chunky pixel chat bubbles, streaming replies, typing state.
- Works with any model you have in Ollama. Defaults to `qwen2.5-coder:7b`.
- **She can be taught**: `persona.md` holds her name and everything she knows, auto-learn saves new
  facts after each reply, and `/remember` / right-click save anything by hand.
- Remembers your last conversation between launches (`data/chat.json`).
- Graceful "Ollama is offline" message instead of a crash.

## Requirements

1. **Windows** with Python 3.9+ (tkinter included). The app itself is cross-platform.
2. **Ollama** installed and the model pulled at least once:

   ```bat
   ollama pull qwen2.5-coder:7b
   ```

   Ollama usually runs in the background after install. If she says she can't reach it,
   open a terminal and run `ollama serve`.

## Run it

Double-click **`start_girlfriend.bat`**. The first run creates a `.venv`, installs Pillow,
draws the pixel art, and launches the window.

Or do it manually:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts\ai_girlfriend.py
```

If you ever delete `assets\`, the app redraws it automatically — you can also run
`python scripts\make_assets.py` to rebuild it by hand.

## Teaching Clera about you

The model itself is stateless: on every message the app sends it her personality prompt **plus**
the contents of `persona.md`. That file is her only long-term memory — including her own name,
which the app writes there and restores if it ever goes missing. Conversations stay in
`data/chat.json` so the persona file remains short and readable. There are three ways to fill it:

### Automatic — she learns after every reply (on by default)

When a reply finishes, a quick background pass asks the model for new permanent facts in the
exchange and appends them under `## Things to remember`. It never blocks the reply, and you see a
subtle `remembered: …` line in the chat when something new was saved. A "My name is Clera" line
means facts are already known and are never stored twice.

Turn it off with the **auto-learn** checkbox in the header (the setting is saved between launches).
The pass costs one extra short request per exchange.

### 1. Type `/remember <fact>` in the chat

```
/remember my name is Alex and I turn 28 in March
/remember I'm allergic to cats
/remember I work night shifts, so I'm up late
```

She writes the line into `persona.md` and confirms in chat. The very next message already
uses it — no restart needed. `/remember` never reaches the model itself, so it costs no
tokens and can't be "forgotten".

You can also right-click any of your own messages and pick **Remember this** — handy when you
said something worth keeping but didn't think to use the command.

### 2. Edit `persona.md` by hand

Click **Memory** in the header to open `persona.md` in your editor (it's also just a file in
the project folder). Put anything you want her to know there, one fact per line:

```markdown
## About me
- My name is Alex and I am 27.
- I study physics, and exams stress me out.
- I love cold brew and old game soundtracks.
- I'm trying to get to bed before 1am.

## About Clera
- She loves strawberry milk, lo-fi music and rainy nights.
```

The file is re-read on every message, so you can edit it while she's running and the change
takes effect immediately. Lines starting with `<!--` are ignored, so you can leave notes to
yourself in the template.

### 3. Just talk to her

Recent messages (up to 24) are sent along with each request as conversation context, so she
follows the thread. That context lives in `data/chat.json` between launches, but it is a
rolling window — for anything you want her to keep permanently, use `/remember`.

**Tips**

- Keep `persona.md` short: it's sent with every message. A few dozen lines is plenty
  (the app caps it at 6000 characters).
- Duplicates are skipped automatically, so `/remember` the same thing twice is harmless.
- If auto-learn saves something wrong, delete the line in `persona.md` (or switch auto-learn off).
- Write facts, not commands: "My sister's name is Mia" works better than "Remember my sister".
- Both `persona.md` and `data/` are git-ignored, so personal notes never end up in a commit.

## Using the UI

| Action | How |
| --- | --- |
| Send a message | `Enter` or the **Send** button |
| New line | `Shift + Enter` |
| Stop her mid-sentence | `Esc`, or the **Stop** button |
| Teach her a fact | `/remember <fact>` |
| Remember one of your messages | right-click it → **Remember this** |
| Toggle automatic learning | **auto-learn** checkbox in the header |
| Edit her memory | **Memory** button (opens `persona.md`) |
| Start a fresh chat | **+ New chat** (`Ctrl + N`) |
| Change the brain | the **brain:** dropdown in the header |
| Re-check the connection | **Refresh** |
| Copy a message | right-click the bubble → **Copy message** |
| Scroll back | mouse wheel over the chat |

The header shows live connection state:

- `● online` — Ollama answered and the dropdown lists your installed models.
- `● offline` — Ollama isn't running; the red bar under the chat tells you what to do.

## Configuration

Set environment variables before launching (optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `PIXEL_GF_MODEL` | `qwen2.5-coder:7b` | Model tag to chat with |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama is listening |

You can also pass a model for a single run:

```bat
python scripts\ai_girlfriend.py --model hf.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M
```

## How it works

`scripts/ai_girlfriend.py` talks to Ollama's local HTTP API (`POST /api/chat`) with
`stream: true`, using only the Python standard library plus Pillow for the sprite.
Tokens arrive on a worker thread and are rendered into a bubble on the UI thread, so the
window never freezes while she thinks. `build_system_prompt()` welds her personality to
`persona.md` on every message. With auto-learn on, a second non-streaming request runs after
each reply; its output is parsed for bullet facts, deduplicated, and appended to the file.

`scripts/make_assets.py` draws Clera and her room on a small pixel grid and upscales it with
nearest-neighbour sampling: `assets/avatar.png` is a 4-frame sprite sheet
(idle, blink, talk, talk) and `assets/background.png` is the room behind her.

## Troubleshooting

- **"I can't reach Ollama"** — start it with `ollama serve`, then press **Refresh**.
- **"I don't have the ... brain loaded"** — `ollama pull <model>` (or pick another model in the dropdown).
- **She ignores something you told her** — put it in `persona.md` as one short factual line and
  keep the file small; stuffing pages of text into a 7b model makes it lose the thread.
- **Auto-learn saved something odd** — a 7b occasionally phrases facts clumsily. Fix or delete the
  line in `persona.md`; the parser already drops chatter and "My name is 27"-style mistakes.
- **Replies are slow** — the first message after starting Ollama loads the model into memory;
  later replies are much faster. `qwen2.5-coder:7b` needs roughly 6–8 GB of RAM/VRAM.
- **She sounds like a programmer** — she's running on a coding model. Try a chat model such as
  `ollama pull qwen2.5:7b` and select it in the dropdown; it stays in character more naturally.
- **Text looks small/blurry** — Windows display scaling can blur Tk fonts. At 100% scaling it's crisp.
