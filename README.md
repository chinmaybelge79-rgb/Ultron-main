<h1 color = black, align = centre >ULTRON</h1>

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/43910764-b690-4d6c-9aa9-bf5dc271ac7a" />

A production-ready, hands-free desktop AI operating system for macOS that behaves like JARVIS.

Speak **"Hey Ultron"** → it replies **"Yes sir?"** → it records your command,
processes it (locally via Ollama, or via OpenRouter + tools), speaks the answer,
and returns to listening.

## Features

- **Continuous microphone listening** with a configurable wake phrase
- **Local speech recognition** via Faster-Whisper (works fully offline)
- **Local-first LLM** via Ollama with automatic fallback to OpenRouter (cloud)
- **Silence detection** for precise command capture
- **OpenRouter LLM** (any model) with retry logic and structured errors
- **ElevenLabs voice** with automatic fallback to the macOS `say` voice
- **25+ tools**: open/quit apps, open websites, Google search, screenshots,
  clipboard copy/paste, terminal commands, file read/write/search, git,
  code search/edit, project scanning, process/disk/uptime, notifications
- **SQLite memory with embeddings**: conversation summaries, preferences, facts,
  semantic vector search, goals, tasks, and reasoning traces
- **Reasoning engine**: Understand → Think → Research → Plan → Execute →
  Verify → Reflect → Improve → Remember
- **Multi-agent framework**: planner, coder, researcher, terminal, browser,
  vision, and memory agents routed by an executive orchestrator
- **Self-improvement**: tracks agent/tool success rates and derives suggestions
- **Offline detection** with heuristic tool routing when the network is down
- **Graceful shutdown** on Ctrl-C / SIGTERM
- SOLID architecture, dependency injection, type hints, docstrings, no global state

## Requirements

- macOS (tested on arm64)
- Python 3.14 (3.10+ compatible)
- Microphone permission for your terminal app
  (System Settings → Privacy & Security → Microphone)
- Optional: [Ollama](https://ollama.com) for fully local LLM inference
  (`ollama pull llama3.1:8b`)

## Quick start

```bash
cd Ultron
./setup.sh                 # creates .venv, installs deps, installs the `ultron` command
cp .env.example .env       # (setup.sh does this if .env is missing)
# edit .env and add your OPENROUTER_API_KEY and ELEVENLABS_API_KEY

.venv/bin/ultron           # or: .venv/bin/python main.py, or: make run
```

`setup.sh` is idempotent — run it any time to refresh the environment.
Manual setup is equivalent:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

Expected startup output:

```
Ultron starting...
Loading Whisper...
Loading microphone...
Listening...
```

Say **"Hey Ultron"**, wait for **"Yes sir?"**, then give a command such as:
*"Open Safari"*, *"Search Google for apple stock"*, *"Take a screenshot"*,
*"What's on my clipboard?"*, or *"Remember that my dog is named Rex"*.

Say **"Goodbye"** to shut down.

## Development

```bash
.venv/bin/python -m pytest -q     # 270 tests covering all modules
.venv/bin/python -m ruff check .  # linter (E, F, I, UP rules)
make test                         # same as pytest -q
make lint                         # same as ruff check
```

If you move the project folder, **recreate the venv** — console scripts
(`.venv/bin/ultron`, `.venv/bin/pip`) embed the absolute install path and
will not work from the old location:

```bash
rm -rf .venv && ./setup.sh
```

## Architecture

```
Ultron/
├── main.py            # Legacy entry point (delegates to ultron.app)
├── pyproject.toml     # Packaging: `ultron` console script, ruff config
├── setup.sh           # One-shot idempotent environment setup
├── Makefile           # setup / test / lint / run targets
├── assets/            # Runtime asset cache
├── logs/              # ultron.log + screenshots
├── data/
│   ├── models/        # Downloaded models cache
│   └── projects/      # Project indexes
├── ultron/            # Main package
│   ├── __main__.py    # python -m ultron
│   ├── app.py         # Composition root, main loop, signal handling
│   ├── config.py      # Immutable Config loaded from .env
│   ├── logger.py      # Console + rotating file logging
│   ├── monitoring.py  # Thread-safe telemetry (counters, latencies, gauges)
│   ├── utils.py       # Exceptions, retry decorator, offline detection
│   ├── core/          # LLM providers, reasoning engine, event bus,
│   │                  # self-improvement
│   ├── memory/        # SQLite store, embeddings, vector search, types
│   ├── agents/        # Agent protocol, registry, orchestrator, and the
│   │                  # planner/coder/researcher/terminal/browser/vision/
│   │                  # memory agents
│   ├── tools/         # Tool framework + macOS, filesystem, shell, clipboard,
│   │                  # web, git, code, project, and system tools
│   ├── voice/         # Listener, recognizer, speaker
│   └── ui/            # Rich terminal UI + output formatters
└── tests/             # pytest suite (config, core, memory, agents, voice...)
```

## Configuration

All settings live in `.env` (see `.env.example`). Notable variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Enables the cloud LLM brain |
| `ELEVENLABS_API_KEY` | — | Enables the cloud voice (else `say`) |
| `ULTRON_WAKE_PHRASE` | `hey ultron` | Wake phrase |
| `ULTRON_WAKE_ACK` | `Yes sir?` | Acknowledgement replies (comma-separated) |
| `ULTRON_WHISPER_MODEL` | `base` | Faster-Whisper model size |
| `ULTRON_OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Cloud LLM model |
| `ULTRON_OLLAMA_URL` | `http://localhost:11434` | Local LLM endpoint |
| `ULTRON_OLLAMA_MODEL` | `llama3.1:8b` | Local LLM model (general tasks) |
| `ULTRON_OLLAMA_CODE_MODEL` | `qwen2.5-coder:7b` | Local LLM model (coding) |
| `ULTRON_SILENCE_THRESHOLD` | `0.006` | RMS level treated as silence |
| `ULTRON_SILENCE_DURATION` | `0.9` | Trailing silence that ends a command (s) |
| `ULTRON_COMMAND_TIMEOUT` | `12` | Max command length (s) |
| `ULTRON_TOOLS_TIMEOUT` | `30` | Shell tool timeout (s) |

## Tools

| Tool | Example argument |
| --- | --- |
| `open_application` | `Safari` |
| `quit_application` | `Safari` |
| `open_website` | `https://news.ycombinator.com` |
| `search_google` | `best espresso machines` |
| `take_screenshot` | *(none)* |
| `copy_clipboard` / `paste_clipboard` | `Hello world` / *(none)* |
| `run_command` | `ls -la` |
| `read_file` / `write_file` | `notes.txt` / `notes.txt :: Buy milk` |
| `list_directory` / `search_files` | `~/projects` / `~/proj :: *.py` |
| `git_status` / `git_diff` / `git_log` / `git_commit` / `git_branch` | `(path)` / `(path)` / ... |
| `code_search` / `code_edit` | `def x :: dir` / `file :: old :: new` |
| `project_scan` / `project_deps` / `todo_scan` | `~/projects/app` |
| `process_list` / `disk_usage` / `uptime` | `python` / `/` / *(none)* |
| `system_info` / `notify` | *(none)* / `Build done` |
| `remember` / `recall` | `user's dog is named Rex` / `what do I like?` |

Destructive shell commands (`rm -rf /`, `mkfs`, `shutdown`, ...) are blocked. Risky-but-sometimes-legitimate commands (`rm -rf` on a path, `sudo`, `git reset --hard`, `git push --force`, `kill -9`, `curl … | bash`) require explicit confirmation and are refused when no confirmation callback is wired.

## Observability

Ultron exposes a lightweight, thread-safe telemetry collector (`ultron/monitoring.py`). Every command, LLM call, tool, transcription, and speech synthesis is instrumented:

- **Counters** — commands online/offline, tool totals, errors
- **Latency histograms** — `llm.chat`, `tools.latency`, `speech.transcribe`, `speech.wake_latency`, `tts.latency` (bounded ring buffer, p50/p95/p99)
- **Gauges** — resource values (`set_gauge(...)`, e.g. RSS)

A session summary is logged at shutdown. Extend with `metrics.observe(...)` / `metrics.increment(...)` anywhere via the injected `Metrics` object (defaults to the process-wide collector).

## Agents

| Agent | Purpose |
| --- | --- |
| `orchestrator` | Executive coordinator; routes tasks to the best agent |
| `planner` | Breaks goals into ordered execution plans |
| `coder` | Code search, edit, and generation |
| `terminal` | Safe shell execution |
| `researcher` | Web, docs, and memory search |
| `browser` | URL fetching and HTML-to-text extraction |
| `vision` | Screenshot analysis and OCR |
| `memory_agent` | Fact storage, recall, and preference management |

## Logs & memory

- Logs: `logs/ultron.log` (rotating, 1 MB × 3) plus console output
- Screenshots: `logs/screenshots/`
- Memory: `ultron_memory.db` (SQLite, WAL mode) with `facts`, `preferences`,
  `conversations`, `embeddings`, `goals`, `tasks`, and `reasoning_traces`

## Troubleshooting

- **`ultron: command not found` / broken `pip`** — the venv was moved. See the
  "recreate the venv" note under Development.
- **"No module named faster_whisper"** — run `./setup.sh` to reinstall requirements.
- **Microphone fails** — grant mic permission to your terminal, then restart Ultron.
- **Whisper model download stalls** — delete `~/.cache/huggingface/hub` and retry.
- **Degraded mode warnings** — add the API keys to `.env`, or install Ollama
  and pull a local model to run fully offline.
- **Graceful shutdown** — Ctrl-C / SIGTERM at any point (even during startup)
  stops Ultron cleanly with exit code 0.
