"""Browser Agent for fetching web pages, reading docs, and web research."""

from __future__ import annotations

import logging
import re

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.tools.base import ToolCall

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_MAX_PAGE_CHARS = 8000

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover - graceful fallback
    _HTTPX_AVAILABLE = False

# Lightweight HTML-to-text: strip scripts/styles/tags, decode entities.
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_OTHER_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(#\d+|amp|lt|gt|quot|apos|nbsp);", re.IGNORECASE)


def html_to_text(html: str) -> str:
    """Convert raw HTML into plain readable text."""
    text = _TAG_RE.sub(" ", html)
    text = _OTHER_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)

    def _replace_entity(match: re.Match[str]) -> str:
        body = match.group(1)
        if body.startswith("#"):
            try:
                return chr(int(body[1:]))
            except ValueError:
                return ""
        return {
            "amp": "&",
            "lt": "<",
            "gt": ">",
            "quot": '"',
            "apos": "'",
            "nbsp": " ",
        }.get(body.lower(), "")

    return _ENTITY_RE.sub(_replace_entity, text).strip()


class BrowserAgent(Agent):
    """Browser Agent: fetches URLs, extracts readable text, and runs searches."""

    name = "browser"
    description = "Fetches web pages, reads documentation, and searches the web."
    capabilities = [
        "browse",
        "fetch url",
        "read website",
        "web page",
        "documentation",
        "http",
    ]

    def __init__(
        self, timeout: float = 20.0, logger: logging.Logger | None = None
    ) -> None:
        self._timeout = timeout
        self._log = logger or logging.getLogger("ultron.agents.browser")

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if _URL_RE.search(task.description) or any(
            w in text
            for w in (
                "browse",
                "fetch",
                "read the website",
                "read the doc",
                "web page",
                "url",
            )
        ):
            return 0.9
        return 0.15

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        description = task.description.strip()
        url_match = _URL_RE.search(description)

        if url_match:
            content = self.fetch_url(url_match.group(0))
            if content is None:
                return AgentResult(
                    success=False, output="", error="Could not fetch the page."
                )
            return AgentResult(success=True, output=content)

        if "search" in description.lower():
            query = description.lower()
            for prefix in ("search for ", "search ", "google ", "look up "):
                if query.startswith(prefix):
                    query = description[len(prefix) :].strip()
                    break
            res = ctx.tools.execute(ToolCall("search_google", query))
            return AgentResult(success=res.success, output=res.output)

        # Fall back to the LLM for research-style queries.
        prompt = (
            f"You are Ultron's Browser Agent. Research this request concisely "
            f"and answer with citations where possible:\n{description}"
        )
        try:
            reply = ctx.llm.chat([{"role": "user", "content": prompt}])
            return AgentResult(success=True, output=reply)
        except Exception as exc:
            return AgentResult(
                success=False, output="", error=f"Browser agent failed: {exc}"
            )

    def fetch_url(self, url: str) -> str | None:
        """Fetch a URL and return its readable text content.

        Returns:
            Extracted plain text, or None on failure.
        """
        if not _HTTPX_AVAILABLE:
            self._log.warning("httpx not installed; cannot fetch URLs.")
            return None
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "UltronBot/0.2"})
            response.raise_for_status()
        except Exception as exc:
            self._log.warning("Fetch failed for %s: %s", url, exc)
            return None

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.text[:_MAX_PAGE_CHARS]
        if "text/" in content_type or "html" in content_type:
            return html_to_text(response.text)[:_MAX_PAGE_CHARS]
        return response.text[:_MAX_PAGE_CHARS]
