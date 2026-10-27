"""Streaming adapter; requires an explicit terminal SSE event."""

import json
import time
import requests


def send_request(body, timeout=30, url="http://127.0.0.1:9931/v1/chat/completions"):
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    start = time.perf_counter()
    result = dict(
        t_start=time.time(),
        status="incomplete_stream",
        response_text="",
        reasoning_text="",
        chunks=0,
        ttft=None,
        ttft_content=None,
        usage=None,
        finish_reason=None,
        error=None,
    )
    try:
        with requests.post(url, json=body, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                result["status"] = f"http_{response.status_code}"
            else:
                for line in response.iter_lines(chunk_size=1):
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        result["status"] = (
                            "ok" if result["finish_reason"] else "incomplete_stream"
                        )
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        result.update(status="server_error", error=str(event["error"]))
                        break
                    if event.get("usage"):
                        result["usage"] = event["usage"]
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        result["finish_reason"] = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content") or ""
                    elapsed = time.perf_counter() - start
                    if content or reasoning:
                        result["chunks"] += 1
                        if result["ttft"] is None:
                            result["ttft"] = elapsed
                    if content and result["ttft_content"] is None:
                        result["ttft_content"] = elapsed
                    result["response_text"] += content
                    result["reasoning_text"] += reasoning
    except requests.exceptions.Timeout as exc:
        result.update(status="timeout", error=str(exc))
    except requests.exceptions.ConnectionError as exc:
        result.update(
            status="timeout" if "Read timed out" in str(exc) else "connection_error",
            error=str(exc),
        )
    except (requests.exceptions.RequestException, ValueError) as exc:
        result.update(status="protocol_error", error=str(exc))
    result["total"] = time.perf_counter() - start
    return result
