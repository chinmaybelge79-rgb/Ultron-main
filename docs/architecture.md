# Ultron Architecture

> Day 1 deliverable — the target system architecture. Every later day builds
> directly on the component boundaries defined here.

```
                         ┌─────────────────────────────┐
                         │   launchd (Day 7)            │
                         │   KeepAlive + RunAtLoad       │
                         └───────────────┬───────────────┘
                                          │ supervises
                         ┌───────────────▼───────────────┐
                         │   ultron/daemon.py  (Day 1)    │
                         │   headless process, no TTY     │
                         │   single-instance lock          │
                         └───────────────┬───────────────┘
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
           ┌────────▼────────┐ ┌────────▼────────┐  ┌────────▼────────┐
           │ Voice Loop        │ │ System Probes    │  │ Autonomy Loop    │
           │ (existing, fixed  │ │ (Day 3)          │  │ (Day 5)          │
           │  wake window)     │ │ CPU/mem/apps/net  │  │ goals+probes→act  │
           └────────┬────────┘ └────────┬────────┘  └────────┬────────┘
                     │                    │                    │
                     └──────────┬─────────┴──────────┬─────────┘
                                │                     │
                       ┌────────▼─────────────────────▼────────┐
                       │  core/assistant.py → agents/orchestrator │
                       │  (Day 5: wired in, currently dormant)    │
                       └────────────────────┬────────────────────┘
                                             │
                       ┌─────────────────────▼─────────────────────┐
                       │  Action Layer (Day 4)                       │
                       │  Permission Gate → tools/registry → Audit   │
                       └─────────────────────┬─────────────────────┘
                                             │
                       ┌─────────────────────▼─────────────────────┐
                       │  Persona Engine (Day 2)                     │
                       │  wraps every outbound reply before speak()  │
                       └─────────────────────┬─────────────────────┘
                                             │
                                   voice/speaker.py → 🔊
```

Cross-cutting, touching every box above: **Kill Switch** (Day 4) and
`memory/store.py` (the shared state backbone for facts/preferences/goals/
tasks/reasoning traces).

## Daemon lifecycle

1. `launchd` invokes `ultron/daemon.py` at login (`RunAtLoad=true`).
2. Daemon acquires a single-instance lock (`/tmp/ultron.lock`, `fcntl.flock`)
   — refuses to start a second copy.
3. Daemon checks the kill-switch sentinel (`data/DISABLED`) — if present, logs
   and exits cleanly without starting any subsystem.
4. Daemon starts three concurrent loop threads (not processes, so they share
   one in-memory `MemoryStore`/`Config`): Voice Loop, System Probe Loop,
   Autonomy Loop.
5. All three loops route actions through the same Action Layer (Day 4) — there
   is exactly one path to tool execution, regardless of which loop triggered it.
6. On any unhandled exception in a loop, log it, keep the other loops running,
   and only let `launchd`'s `KeepAlive` restart the whole process if the
   *entire* daemon exits.

## Module map

| Day | Module | Status |
|-----|--------|--------|
| 1 | `ultron/daemon.py` | ✅ stubs + lock + kill-switch check |
| 2 | `ultron/persona/` | ongoing |
| 3 | `ultron/probes/` | ongoing |
| 4 | `ultron/action/` | ongoing |
| 5 | `ultron/autonomy/` | ongoing |
| 6 | `ultron/selfmod/` | ongoing |
| 7 | `packaging/`, `scripts/` | ongoing |
