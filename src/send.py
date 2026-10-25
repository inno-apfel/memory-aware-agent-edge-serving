# send.py
# usage: python send.py --n 4 --concurrency 2 --prompt-tokens 500 --max-tokens 64
import json, time, requests

from src.utils import load_url

URL = load_url()

def one_request(prompt, max_tokens=256, timeout=120, url=URL):
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": 0,
        "seed": 42,
        "ignore_eos": True,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},   # try to turn thinking off
    }

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

    return dict(prompt=prompt, response_text=response_text,
                reasoning_text=reasoning_text,                 
                t_start=t0, ttft=ttft, ttft_content=ttft_content,   
                total=time.time() - t0, chunks=chunks, status=status)