"""Priority ranking for the Autonomy Loop.

A legible, tunable scoring table beats an \"the LLM decides everything\" black
box for something that is supposed to be auditable. The Autonomy Loop uses
these scores to decide whether a candidate is worth interrupting for.
"""

from __future__ import annotations

BASE_URGENCY = {
    "resource_pressure": 6,  # CPU pinned, might be worth flagging
    "idle": 2,  # low-stakes, good moment for a proactive suggestion
    "app_launched": 1,  # usually noise unless paired with a standing goal
    "network_changed": 3,  # worth a security-relevant check (new/unknown network)
    "pending_goal": 5,  # user explicitly asked for this at some point
    "pending_task": 7,  # user explicitly queued a concrete action
}

# Candidates below this urgency are not worth interrupting anyone for.
ACTION_THRESHOLD = 3

# Probe events below this urgency are surfaced as observations, not actions.
OBSERVE_THRESHOLD = 5


def score(event_kind: str, agent_success_rate: float | None) -> int:
    """Rank an event kind on a 0–10 scale, optionally tuned by track record.

    An agent with a poor track record on this kind of task gets deprioritized,
    not blocked — this is where ``self_improve.py`` stats actually change
    behavior rather than just being logged.
    """
    base = BASE_URGENCY.get(event_kind, 1)
    if agent_success_rate is not None:
        base = round(base * (0.5 + 0.5 * agent_success_rate))
    return min(base, 10)
