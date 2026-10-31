"""HTTP client for streaming OpenAI-compatible chat completion endpoints.

This module translates server-sent events (SSE) into one result mapping used
by the scheduler. A response is successful only after both a finish reason and
the terminal ``[DONE]`` event are observed. Model content and reasoning are
kept separately; timing fields are elapsed seconds except ``t_start`` (epoch
seconds). Stream chunks are events and must not be interpreted as tokens.
"""

import json
import time
import requests


def send_request(body, timeout=30, url="http://127.0.0.1:9931/v1/chat/completions"):
    """POST ``body`` and collect the streamed completion.

    Args:
        body: JSON request body, generally assembled by ``agent_runner``.
        timeout: Requests connect/read inactivity timeout, not a total deadline.
        url: OpenAI-compatible chat completions endpoint.

    Returns:
        A mapping with ``status``, response/reasoning text, chunk count, TTFT,
        finish reason, usage when supplied, total duration, and error details.
        Non-200, incomplete, transport, and protocol failures are represented
        as statuses instead of being raised. Invalid nonpositive timeouts raise
        ``ValueError`` before the request begins.
    """
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
        # Stream the response so first-token timing and partial output survive
        # even if the server or connection fails before the stream completes.
        with requests.post(url, json=body, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                result["status"] = f"http_{response.status_code}"
            else:
                # Accumulate SSE deltas until the protocol's explicit terminal
                # marker. A finish reason without [DONE] remains incomplete.
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
    # Convert network/protocol errors into result statuses so the scheduler can
    # log the failure and terminate only the affected task.
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
