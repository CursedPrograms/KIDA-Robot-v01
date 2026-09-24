"""
llm.py - the one place the mind (and kida_chat_wakeword.py) talks to Ollama.

Two things a bare ollama.chat() call doesn't do:
  * If Ollama's GPU mode crashes (a CUDA build the graphics driver can't run),
    fall back to the CPU once and stay there instead of failing every reply.
  * One generation at a time. Background thinking (reflection) never
    queues up behind - or in front of - a conversation: with blocking=False it
    simply skips if the model is busy.
"""

import threading

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:0.5b"   # kida_chat_wakeword.OLLAMA_MODEL; configure() keeps them in step

_lock = threading.Lock()
_gpu_broken = False
last_error = ""


class LLMError(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind  # "timeout" | "http" | "unavailable"


def configure(model=None, url=None):
    global MODEL, OLLAMA_URL
    if model:
        MODEL = model
    if url:
        OLLAMA_URL = url


def available(timeout=2) -> bool:
    try:
        return requests.get(OLLAMA_URL.replace("/api/generate", "/api/tags"), timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def busy() -> bool:
    return _lock.locked()


def _post(payload, timeout):
    return requests.post(OLLAMA_URL, json=payload, timeout=timeout)


def generate(prompt, *, num_predict=150, temperature=0.7, timeout=120, blocking=True, stop=None):
    """Returns the model's text, or None if blocking=False and the model is busy.
    Raises LLMError on failure."""
    global _gpu_broken, last_error
    if not _lock.acquire(blocking=blocking):
        return None
    try:
        def ask(num_gpu):
            options = {"temperature": temperature, "num_predict": num_predict, "num_gpu": num_gpu}
            if stop:
                options["stop"] = stop
            return _post({"model": MODEL, "prompt": prompt, "stream": False, "options": options}, timeout)

        try:
            r = ask(0 if _gpu_broken else 20)
            if r.status_code == 500 and not _gpu_broken and "CUDA" in r.text:
                _gpu_broken = True
                last_error = "GPU mode failed; using the CPU from now on"
                r = ask(0)
        except requests.exceptions.Timeout:
            raise LLMError("timeout")
        except requests.RequestException as e:
            raise LLMError("unavailable", str(e))
        if r.status_code != 200:
            last_error = r.text[:200]
            raise LLMError("http", f"{r.status_code} {r.text[:120]}")

        text = (r.json().get("response") or "").strip()
        if "<think>" in text:
            end = text.find("</think>")
            if end != -1:
                text = text[end + 8:].strip()
        return text
    finally:
        _lock.release()


def chat(messages, *, num_predict=150, temperature=0.7, timeout=120, blocking=True):
    """Like generate(), through Ollama's /api/chat (so the model's own chat
    template is applied - what kida_chat_wakeword's ollama.chat() did). Same
    one-at-a-time lock and CPU fallback. messages: [{"role", "content"}]."""
    global _gpu_broken, last_error
    if not _lock.acquire(blocking=blocking):
        return None
    url = OLLAMA_URL.replace("/api/generate", "/api/chat")
    try:
        def ask(num_gpu):
            options = {"temperature": temperature, "num_predict": num_predict, "num_gpu": num_gpu}
            return requests.post(url, json={"model": MODEL, "messages": messages, "stream": False,
                                            "options": options}, timeout=timeout)

        try:
            r = ask(0 if _gpu_broken else 20)
            if r.status_code == 500 and not _gpu_broken and "CUDA" in r.text:
                _gpu_broken = True
                last_error = "GPU mode failed; using the CPU from now on"
                r = ask(0)
        except requests.exceptions.Timeout:
            raise LLMError("timeout")
        except requests.RequestException as e:
            raise LLMError("unavailable", str(e))
        if r.status_code != 200:
            last_error = r.text[:200]
            raise LLMError("http", f"{r.status_code} {r.text[:120]}")

        text = ((r.json().get("message") or {}).get("content") or "").strip()
        if "<think>" in text:
            end = text.find("</think>")
            if end != -1:
                text = text[end + 8:].strip()
        return text
    finally:
        _lock.release()
