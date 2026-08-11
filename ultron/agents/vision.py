"""Vision Agent for screenshot analysis, OCR, and image understanding.

Uses a local multimodal model via Ollama when available, otherwise falls
back to macOS OCR tooling (``shortcuts`` / Apple Vision) or ``tesseract``
if installed. All backends degrade gracefully when absent.
"""

from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path

import requests

from ultron.agents.base import Agent, AgentContext, AgentResult, Task
from ultron.tools.base import ToolCall
from ultron.utils import truncate

_MAX_OCR_CHARS = 4000


class VisionAgent(Agent):
    """Vision Agent: understands screenshots, images, and OCRs text."""

    name = "vision"
    description = (
        "Analyzes screenshots and images, extracts text via OCR, understands UI."
    )
    capabilities = ["vision", "image", "screenshot", "ocr", "see", "screen"]

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llava:7b",
        logger: logging.Logger | None = None,
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model
        self._log = logger or logging.getLogger("ultron.agents.vision")

    def can_handle(self, task: Task) -> float:
        text = task.description.lower()
        if any(
            w in text
            for w in (
                "look at",
                "read the screen",
                "describe",
                "screenshot",
                "image",
                "ocr",
                "see what",
            )
        ):
            return 0.85
        return 0.1

    def handle(self, task: Task, ctx: AgentContext) -> AgentResult:
        description = task.description.strip()

        # If a file path is provided, analyze it directly.
        path = self._resolve_image_path(description)
        if path is None:
            # Otherwise grab a fresh screenshot.
            res = ctx.tools.execute(ToolCall("take_screenshot", ""))
            if not res.success:
                return AgentResult(success=False, output="", error=res.output)
            shot = self._extract_path(res.output)
            path = Path(shot) if shot else None

        if path is None or not path.exists():
            return AgentResult(
                success=False, output="", error="No screenshot or image available."
            )

        ocr_text = self._ocr(path)
        if ocr_text:
            output = f"OCR of {path.name}:\n{truncate(ocr_text, _MAX_OCR_CHARS)}"
            return AgentResult(success=True, output=output)

        # Try multimodal analysis via a local Ollama model.
        analysis = self._describe_image(path, description)
        if analysis:
            return AgentResult(success=True, output=analysis)

        return AgentResult(
            success=False,
            output="",
            error=(
                "No OCR tooling or multimodal model is available to analyze the image."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_image_path(self, text: str) -> Path | None:
        """Find an image file path mentioned in the task text."""
        for token in text.split():
            candidate = Path(token).expanduser()
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _extract_path(text: str) -> str | None:
        """Extract a screenshot path from a tool result line."""
        for line in text.splitlines():
            if "saved to" in line:
                return line.split("saved to", 1)[1].strip().rstrip(".")
        return None

    def _ocr(self, path: Path) -> str:
        """Extract text from an image using available OCR machinery."""
        try:
            result = subprocess.run(
                ["tesseract", str(path), "stdout"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._log.debug("OCR unavailable: %s", exc)
        return ""

    def _describe_image(self, path: Path, prompt: str) -> str:
        """Ask a local multimodal model (via Ollama) to describe the image."""
        try:
            image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            self._log.warning("Could not read image: %s", exc)
            return ""
        try:
            response = requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt or "Describe this image in detail.",
                    "images": [image_b64],
                    "stream": False,
                },
                timeout=(5.0, 120.0),
            )
        except requests.RequestException as exc:
            self._log.warning("Ollama vision unavailable: %s", exc)
            return ""
        if response.status_code != 200:
            self._log.warning("Ollama vision returned HTTP %s", response.status_code)
            return ""
        try:
            return str(response.json()["response"]).strip()
        except (KeyError, ValueError):
            return ""
