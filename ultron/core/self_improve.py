"""Self-Improvement Engine.

Tracks agent/tool success rates, captures reasoning trace outcomes, and
adjusts internal prompt/strategy hints based on observed performance so
Ultron gradually improves over time. Persists statistics to the memory
store and exposes actionable suggestions.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

from ultron.memory.store import MemoryStore
from ultron.utils import truncate


@dataclass
class AgentStats:
    """Running statistics for one agent or tool."""

    name: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_latency: float = 0.0

    @property
    def success_rate(self) -> float:
        """Fraction of successful attempts (0.0 when no attempts)."""
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def avg_latency(self) -> float:
        """Average latency in seconds (0.0 when no attempts)."""
        return self.total_latency / self.attempts if self.attempts else 0.0

    def snapshot(self) -> dict[str, Any]:
        """Return a stable serializable representation."""
        data = asdict(self)
        data["success_rate"] = round(self.success_rate, 3)
        data["avg_latency"] = round(self.avg_latency, 3)
        return data


class SelfImprovementEngine:
    """Tracks performance and derives improvement suggestions."""

    def __init__(
        self,
        memory: MemoryStore | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._memory = memory
        self._log = logger or logging.getLogger("ultron.self_improve")
        self._agents: dict[str, AgentStats] = {}
        self._tools: dict[str, AgentStats] = {}
        self._strategy_hits: dict[str, int] = {}
        self._strategy_misses: dict[str, int] = {}
        self._started = time.time()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_agent_result(
        self, agent: str, success: bool, latency: float = 0.0
    ) -> None:
        """Record the outcome of an agent execution."""
        stats = self._stats(self._agents, agent)
        stats.attempts += 1
        stats.successes += int(success)
        stats.failures += int(not success)
        stats.total_latency += latency
        self._log.debug("Agent '%s' result: success=%s", agent, success)

    def record_tool_result(
        self, tool: str, success: bool, latency: float = 0.0
    ) -> None:
        """Record the outcome of a tool execution."""
        stats = self._stats(self._tools, tool)
        stats.attempts += 1
        stats.successes += int(success)
        stats.failures += int(not success)
        stats.total_latency += latency

    def record_strategy(self, strategy: str, success: bool) -> None:
        """Record whether a prompt/planning strategy led to success."""
        bucket = self._strategy_hits if success else self._strategy_misses
        bucket[strategy] = bucket.get(strategy, 0) + 1

    def get_agent_stats(self, agent: str) -> AgentStats:
        """Return stats for an agent, creating them if absent."""
        return self._stats(self._agents, agent)

    def get_tool_stats(self, tool: str) -> AgentStats:
        """Return stats for a tool, creating them if absent."""
        return self._stats(self._tools, tool)

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def weakest_agents(self, limit: int = 3, min_attempts: int = 1) -> list[AgentStats]:
        """Return the agents with the lowest success rates."""
        candidates = [
            stats for stats in self._agents.values() if stats.attempts >= min_attempts
        ]
        return sorted(candidates, key=lambda stats: stats.success_rate)[:limit]

    def fastest_agents(self, limit: int = 3) -> list[AgentStats]:
        """Return the fastest (lowest average latency) agents."""
        candidates = [stats for stats in self._agents.values() if stats.attempts > 0]
        return sorted(candidates, key=lambda stats: stats.avg_latency)[:limit]

    def summarize(self) -> str:
        """Return a text summary of tracked performance."""
        lines: list[str] = []
        if self._agents:
            lines.append("Agents:")
            for _, stats in sorted(self._agents.items()):
                lines.append(
                    f"  {stats.name}: {stats.attempts} runs, "
                    f"{stats.success_rate * 100:.0f}% success"
                )
        if self._tools:
            lines.append("Tools:")
            for _, stats in sorted(self._tools.items()):
                lines.append(
                    f"  {stats.name}: {stats.attempts} runs, "
                    f"{stats.success_rate * 100:.0f}% success"
                )
        if not self._agents and not self._tools:
            lines.append("No performance data recorded yet.")
        return truncate("\n".join(lines), 4000)

    def suggestions(self) -> list[str]:
        """Derive actionable improvement suggestions from tracked data."""
        ideas: list[str] = []
        for stats in self.weakest_agents(limit=3, min_attempts=2):
            if stats.success_rate < 0.5:
                ideas.append(
                    f"Agent '{stats.name}' fails often "
                    f"({stats.failures}/{stats.attempts}); "
                    "consider simplifying its tool usage or adding retries."
                )
        for strategy, misses in self._strategy_misses.items():
            hits = self._strategy_hits.get(strategy, 0)
            if misses > hits and misses >= 3:
                ideas.append(
                    f"Strategy '{strategy}' typically fails "
                    f"({hits} ok / {misses} bad); "
                    "consider adjusting it."
                )
        if not ideas:
            ideas.append("No improvement opportunities detected yet.")
        return ideas

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self) -> None:
        """Persist performance statistics to the memory store."""
        if self._memory is None:
            return
        try:
            payload = json.dumps(
                {
                    "agents": [stats.snapshot() for stats in self._agents.values()],
                    "tools": [stats.snapshot() for stats in self._tools.values()],
                    "strategies": {
                        "hits": self._strategy_hits,
                        "misses": self._strategy_misses,
                    },
                }
            )
            self._memory.store_reasoning_trace(
                task_description="self_improvement_snapshot",
                trace_json=payload,
                outcome="info",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._log.warning("Could not persist self-improvement stats: %s", exc)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _stats(table: dict[str, AgentStats], name: str) -> AgentStats:
        stats = table.get(name)
        if stats is None:
            stats = AgentStats(name=name)
            table[name] = stats
        return stats
