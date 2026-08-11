"""Autonomy Loop: proactive decision-making built on probe events and goals.

The loop is a decider, never a bypass — every action it takes still routes
through the Day 4 PermissionGate.
"""

from ultron.autonomy.loop import AutonomyLoop, Candidate
from ultron.autonomy.priority import ACTION_THRESHOLD, BASE_URGENCY, score

__all__ = [
    "ACTION_THRESHOLD",
    "BASE_URGENCY",
    "AutonomyLoop",
    "Candidate",
    "score",
]
