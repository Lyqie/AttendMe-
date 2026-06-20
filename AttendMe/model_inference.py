"""
Cloud multimodal model inference for AttendMe.

Uses DashScope (Alibaba Cloud) OpenAI-compatible API to call Qwen VL models.
The inference runs inside a QThread worker to keep the UI responsive.

Supports any OpenAI-compatible endpoint (DashScope, OpenAI, vLLM, etc.).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests
from PySide6.QtCore import QThread, Signal


# ── Prompt template ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an attention monitoring system. Analyze this screenshot of the user's computer screen.

Determine what activity the user is engaged in and rate their focus/attention level on a scale of 0-100.

Scoring guidelines:
- 80-100 (High Focus): Coding/IDE, programming, writing documentation, reading technical materials, using design tools (Figma, Photoshop, Blender), data analysis in spreadsheets, terminal/command line, learning platforms, taking notes, reading PDFs/academic papers
- 40-79 (Medium Focus): Email clients, general web browsing, file management, video meetings/calls, project management tools (Jira, Notion, Trello), work chat (Slack, Teams, Discord for work), system settings, online shopping, reading news
- 0-39 (Low Focus): Social media feeds (Twitter/X, Reddit, Weibo, Instagram, TikTok), video streaming/entertainment (YouTube, Netflix, Bilibili, Twitch), gaming, meme sites, idle desktop/blank screen/screensaver, stock trading/gambling sites

Respond ONLY with a valid JSON object. No markdown, no code fences, no extra text:
{"score": <0-100 integer>, "category": "<high|medium|low>", "activity": "<brief description>", "reasoning": "<one sentence>"}"""


# ── Response parser ───────────────────────────────────────────────────────────

def parse_model_response(text: str) -> dict[str, Any]:
    """Extract a JSON score object from the model's raw output.

    Handles common failure modes: code fences, trailing commas, bare numbers.
    """
    cleaned = text.strip()
    for fence in ("```json", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    m = re.search(r'\{[^{}]*"score"\s*:\s*\d+[^{}]*\}', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    m = re.search(r'\b(\d{1,3})\b', cleaned)
    if m:
        score = max(0, min(100, int(m.group(1))))
        return {"score": score, "category": "medium", "activity": "unknown",
                "reasoning": "fallback parse"}

    return {"score": 50, "category": "medium", "activity": "parse_error",
            "reasoning": "could not parse model output"}


# ── Cloud VL API client (OpenAI-compatible) ──────────────────────────────────

class CloudVLClient:
    """OpenAI-compatible multimodal chat client.

    Works with:
      - DashScope:    https://dashscope.aliyuncs.com/compatible-mode/v1
      - OpenAI:       https://api.openai.com/v1
      - vLLM / Ollama OpenAI endpoint
    """

    def __init__(self, api_key: str = "",
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 model: str = "qwen3.5-vl-flash",
                 timeout: int = 30):
        # API key priority: argument > env var
        self._api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def chat(self, prompt: str, image_base64: str) -> str:
        """Send a prompt + image and return the text response."""
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def health_check(self) -> bool:
        """Return True if the API endpoint is reachable and authenticated."""
        if not self._api_key:
            return False
        try:
            r = requests.get(f"{self._base_url}/models",
                             headers={"Authorization": f"Bearer {self._api_key}"},
                             timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """Return available model IDs from the endpoint."""
        try:
            r = requests.get(f"{self._base_url}/models",
                             headers={"Authorization": f"Bearer {self._api_key}"},
                             timeout=5)
            if r.status_code == 200:
                data = r.json()
                return [m["id"] for m in data.get("data", [])]
        except Exception:
            pass
        return []


# ── QThread worker ────────────────────────────────────────────────────────────

class InferenceWorker(QThread):
    """Runs multimodal inference in a background thread.

    Signals:
        result_ready(dict)  – emitted with parsed score data on success
        error_occurred(str) – emitted with error message on failure
    """

    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, client: CloudVLClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._pending_image: str | None = None
        self._pending_prompt: str = ""
        self._running = True
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def infer(self, image_base64: str, prompt: str = "") -> None:
        """Queue an inference request. No-op if already processing."""
        if self._busy:
            return
        self._pending_image = image_base64
        self._pending_prompt = prompt or SYSTEM_PROMPT
        self._busy = True
        if not self.isRunning():
            self.start()
        else:
            self._do_infer()

    def _do_infer(self) -> None:
        if self._pending_image is None:
            self._busy = False
            return

        image = self._pending_image
        prompt = self._pending_prompt
        self._pending_image = None
        self._pending_prompt = ""

        try:
            t0 = time.perf_counter()
            raw = self._client.chat(prompt, image)
            elapsed = time.perf_counter() - t0
            result = parse_model_response(raw)
            result["_inference_time"] = round(elapsed, 2)
            self.result_ready.emit(result)
        except requests.ConnectionError:
            self.error_occurred.emit("无法连接 API 服务器，请检查网络")
        except requests.Timeout:
            self.error_occurred.emit(
                f"API 请求超时 ({self._client._timeout}s)"
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = ""
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text if exc.response is not None else ""
            self.error_occurred.emit(
                f"API 错误 HTTP {status}: {body}"
            )
        except Exception as exc:
            self.error_occurred.emit(f"推理错误: {exc}")
        finally:
            self._busy = False

    def run(self) -> None:
        """Main thread loop — processes inference requests."""
        while self._running:
            if self._pending_image is not None:
                self._do_infer()
            self.msleep(200)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)
