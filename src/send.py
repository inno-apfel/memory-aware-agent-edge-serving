# send.py

from concurrent.futures import ThreadPoolExecutor
import time

from src.utils import load_config


def send_request(body, timeout=120, url=None):
    """Compatible wrapper around the validated streaming transport."""
    from src.transport import send_request as transport

    if url is None:
        server = load_config()["server"]
        url = f"http://{server['host']}:{server['port']}/v1/chat/completions"
    return transport(body, timeout=timeout, url=url)


def timed_request(i, body, ready=None):
    """Wrap one_request so a failure doesn't kill the batch, and record timing."""
    start = time.perf_counter()
    try:
        result = send_request(body)
    except Exception as e:
        result = {"status": "error", "error": repr(e)}
    end = time.perf_counter()
    return {
        "idx": i,
        "start": start,
        "end": end,
        "latency": end - start,
        "queue_s": start - (ready if ready is not None else start),
        **result,
    }


def run_workload(workload, concurrency=4):
    """Submit all prompts in order; at most `concurrency` run at once."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(timed_request, i, body, time.perf_counter())
            for i, body in enumerate(workload)
        ]
        return [f.result() for f in futures]  # results in submission order
