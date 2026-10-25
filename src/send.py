# send.py

from concurrent.futures import ThreadPoolExecutor
import json, time, requests

from src.utils import load_config

server_port = load_config().get("server").get("port")

def send_request(body, timeout=120, url=f'http://127.0.0.1:{server_port}/v1/chat/completions'):

    t0 = time.time()
    ttft = None               # first token of any kind (thinking or answer)
    ttft_content = None       # first visible answer token
    chunks = 0
    status = "ok"
    response_text = ""
    reasoning_text = ""       # NEW: thinking text is collected separately

    try:
        with requests.post(url, json=body, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                status = f"http_{response.status_code}"
            else:
                for line in response.iter_lines():
                    if not line.startswith(b"data: ") or line == b"data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    choices = event.get("choices") or []
                    if not choices:
                        continue

                    d = choices[0].get("delta", {})
                    reasoning = d.get("reasoning_content")
                    content = d.get("content")

                    if reasoning or content:
                        chunks += 1
                        if ttft is None:
                            ttft = time.time() - t0
                    if reasoning:
                        reasoning_text += reasoning
                    if content:
                        response_text += content
                        if ttft_content is None:
                            ttft_content = time.time() - t0
    except requests.exceptions.Timeout:
        status = "timeout"
    except requests.exceptions.ConnectionError:
        status = "connection_error"

    return dict(prompt=body.get("messages", [{}])[0].get("content"), response_text=response_text,
                reasoning_text=reasoning_text,                 
                t_start=t0, ttft=ttft, ttft_content=ttft_content,   
                total=time.time() - t0, chunks=chunks, status=status)

def timed_request(i, body):
    """Wrap one_request so a failure doesn't kill the batch, and record timing."""
    start = time.time()
    try:
        result = send_request(body)
    except Exception as e:
        result = {"status": "error", "error": repr(e)}
    end = time.time()
    return {"idx": i, "start": start, "end": end, "latency": end - start, **result}

def run_workload(workload, concurrency=4):
    """Submit all prompts in order; at most `concurrency` run at once."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(timed_request, i, body)
                   for i, body in enumerate(workload)]
        return [f.result() for f in futures]  # results in submission order