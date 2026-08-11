"""Web tools: open URLs, search Google."""

from __future__ import annotations

import re
import subprocess
import urllib.parse

from ultron.tools.base import Tool, ToolResult


class OpenWebsiteTool(Tool):
    """Open a URL in the default browser."""

    name = "open_website"
    description = (
        "Open a website in the default browser. "
        "Example: open_website(https://news.ycombinator.com)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        url = arg.strip()
        if not url:
            return ToolResult(False, "No URL given.")
        if "://" not in url:
            url = "https://" + url
        if not re.match(r"^https?://[^\s]+$", url):
            return ToolResult(False, f"Invalid URL: {url}")
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return ToolResult(True, f"Opened {url}.")
        return ToolResult(False, f"Could not open {url}: {result.stderr.strip()}")


class SearchGoogleTool(Tool):
    """Perform a Google search in the default browser."""

    name = "search_google"
    description = (
        "Search Google for a query and open the results in the browser. "
        "Example: search_google(best espresso machines 2026)"
    )
    result_is_final = True

    def run(self, arg: str) -> ToolResult:
        query = arg.strip()
        if not query:
            return ToolResult(False, "No search query given.")
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return ToolResult(True, f"Searching Google for {query}.")
        return ToolResult(False, f"Could not open search: {result.stderr.strip()}")
