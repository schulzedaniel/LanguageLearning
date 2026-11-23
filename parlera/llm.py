"""Minimal async Ollama client (chat streaming + structured JSON output)."""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Callable

import httpx


class LLMError(RuntimeError):
    pass


class ThinkFilter:
    """Removes <think>…</think> blocks from a token stream (reasoning models)."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False

    def feed(self, text: str) -> str:
        self.buf += text
        out = []
        while self.buf:
            if self.inside:
                i = self.buf.find(self.CLOSE)
                if i == -1:
                    # keep a tail in case the close tag is split across tokens
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[i + len(self.CLOSE):]
                self.inside = False
            else:
                i = self.buf.find(self.OPEN)
                if i == -1:
                    # emit everything except a possible partial "<think" at the end
                    keep = 0
                    for k in range(1, len(self.OPEN)):
                        if self.buf.endswith(self.OPEN[:k]):
                            keep = k
                    out.append(self.buf[: len(self.buf) - keep])
                    self.buf = self.buf[len(self.buf) - keep:]
                    break
                out.append(self.buf[:i])
                self.buf = self.buf[i + len(self.OPEN):]
                self.inside = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf = ""
        return rest


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def parse_json_loose(text: str) -> Any:
    """Parse JSON even if the model wrapped it in prose or code fences."""
    text = strip_think(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise LLMError("The model did not return valid JSON.")


class OllamaClient:
    def __init__(self, settings_getter: Callable[[], dict]):
        self._settings = settings_getter

    @property
    def cfg(self) -> dict:
        return self._settings()["llm"]

    def _url(self, path: str) -> str:
        return self.cfg["base_url"].rstrip("/") + path

    def _body(self, messages: list[dict], model: str | None, stream: bool,
              fmt: Any = None, options: dict | None = None) -> dict:
        cfg = self.cfg
        body: dict[str, Any] = {
            "model": model or cfg["model"],
            "messages": messages,
            "stream": stream,
            "keep_alive": cfg.get("keep_alive", "30m"),
            "options": {"temperature": cfg.get("temperature", 0.7),
                        "num_ctx": int(cfg.get("num_ctx", 16384)), **(options or {})},
        }
        if fmt is not None:
            body["format"] = fmt
        if cfg.get("disable_thinking"):
            body["think"] = False
        return body

    async def _post_with_think_fallback(self, client: httpx.AsyncClient, body: dict) -> httpx.Response:
        r = await client.post(self._url("/api/chat"), json=body)
        if r.status_code == 400 and "think" in body and "think" in r.text.lower():
            body = {k: v for k, v in body.items() if k != "think"}
            r = await client.post(self._url("/api/chat"), json=body)
        return r

    async def chat_stream(self, messages: list[dict], model: str | None = None,
                          options: dict | None = None) -> AsyncIterator[str]:
        body = self._body(messages, model, True, options=options)
        filt = ThinkFilter()
        timeout = httpx.Timeout(connect=10, read=300, write=30, pool=10)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                for attempt in (0, 1):
                    async with client.stream("POST", self._url("/api/chat"), json=body) as r:
                        if r.status_code != 200:
                            text = (await r.aread()).decode("utf-8", "replace")
                            if attempt == 0 and r.status_code == 400 and "think" in body and "think" in text.lower():
                                body.pop("think", None)
                                continue
                            raise LLMError(self._explain(r.status_code, text, body["model"]))
                        async for line in r.aiter_lines():
                            if not line.strip():
                                continue
                            data = json.loads(line)
                            if data.get("error"):
                                raise LLMError(data["error"])
                            chunk = (data.get("message") or {}).get("content", "")
                            if chunk:
                                visible = filt.feed(chunk)
                                if visible:
                                    yield visible
                            if data.get("done"):
                                break
                        tail = filt.flush()
                        if tail:
                            yield tail
                        return
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach Ollama at {self.cfg['base_url']}. Is Ollama running? ({e})") from e

    async def chat(self, messages: list[dict], model: str | None = None, fmt: Any = None,
                   options: dict | None = None, timeout: float = 600) -> str:
        body = self._body(messages, model, False, fmt=fmt, options=options)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await self._post_with_think_fallback(client, body)
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach Ollama at {self.cfg['base_url']}. Is Ollama running? ({e})") from e
        if r.status_code != 200:
            raise LLMError(self._explain(r.status_code, r.text, body["model"]))
        data = r.json()
        return strip_think((data.get("message") or {}).get("content", ""))

    async def chat_json(self, messages: list[dict], schema: dict | None = None,
                        model: str | None = None, temperature: float = 0.2) -> Any:
        text = await self.chat(messages, model=model, fmt=schema or "json",
                               options={"temperature": temperature})
        return parse_json_loose(text)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(self._url("/api/tags"))
            r.raise_for_status()
            return sorted(m.get("name") or m.get("model") for m in r.json().get("models", []))

    async def warm(self, model: str | None = None) -> None:
        """Load the model into memory so the first reply is fast."""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                await client.post(self._url("/api/generate"),
                                  json={"model": model or self.cfg["model"],
                                        "keep_alive": self.cfg.get("keep_alive", "30m")})
        except httpx.HTTPError:
            pass

    async def unload(self, model: str | None = None) -> None:
        """Free the model's memory right away (instead of waiting for keep_alive to expire)."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(self._url("/api/generate"),
                                  json={"model": model or self.cfg["model"], "keep_alive": 0})
        except httpx.HTTPError:
            pass

    @staticmethod
    def _explain(status: int, text: str, model: str) -> str:
        if status == 404 and "not found" in text.lower():
            return f"Model '{model}' is not installed. Run: ollama pull {model}"
        return f"Ollama error {status}: {text[:300]}"
