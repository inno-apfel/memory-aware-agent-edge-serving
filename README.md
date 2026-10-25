# Memory-aware agent edge serving

This repository contains a small experiment for measuring streamed chat
completion requests alongside the serving process's memory and CPU usage. The
main workflow is in [`main.ipynb`](./main.ipynb); request and process-monitoring
helpers are in `src/`.

## Project structure

```text
.
├── config.yml             # Chat-completions endpoint
├── environment.yml        # Conda environment dependencies
├── launch_server.py       # Server launcher
├── main.ipynb             # Experiment notebook
├── results/               # Generated request data and plots
├── src/
│   ├── monitor.py         # Process resource monitoring
│   ├── runner.py          # Request workload runner
│   ├── send.py            # Streaming request helper
│   └── utils.py           # Shared configuration and process helpers
└── workloads/
    └── examples.jsonl     # Example request workloads
```

## Requirements and configuration

The supplied [`environment.yml`](./environment.yml) lists the Python
dependencies for the notebook and helpers. It includes a machine-specific
Conda `prefix`; update or remove that line if you create the environment on a
different machine.

Set the OpenAI-compatible chat completions endpoint in [`config.yml`](./config.yml):

```yaml
url: http://127.0.0.1:9931/v1/chat/completions
```

The endpoint is loaded when `src.send` is imported. Start the model server
before using the request helper, and make sure the configured URL is reachable.
The request helper sends streaming chat-completion requests to this endpoint.

## Install Llama.cpp

```bash
# install llama.cpp
curl -LsSf https://llama.app/install.sh | sh
```

```bash
# Download and run a model directly from Hugging Face
llama serve -hf ggml-org/Qwen3.5-0.8B-GGUF
```

## Run the experiment

Open `main.ipynb` in Jupyter and run its cells in order. It demonstrates:

1. Sending a single request and displaying its status, timing metrics, answer,
   and reasoning text.
2. Sampling the serving process while a request runs.
3. Viewing the collected samples as a table and plotting process memory and CPU.

The monitor looks for the first process whose name or command line contains
`llama` when `src.monitor` is imported. Start that process before importing the
monitor. The notebook's `run_monitor` helper collects samples in memory; it
does not write them to a CSV file.

## Sending a request from Python

`one_request` sends one prompt and returns a dictionary with the request
metrics and collected text:

```python
from src.send import one_request

result = one_request("Say hi", max_tokens=64)
print(result["status"])
print(result["response_text"])
print(result["reasoning_text"])
print("TTFT:", result["ttft"])
print("First answer token:", result["ttft_content"])
```

The result includes:

- `response_text`: streamed answer content.
- `reasoning_text`: streamed reasoning content, if the server provides it.
- `ttft`: seconds until the first reasoning or answer content arrives.
- `ttft_content`: seconds until the first answer content arrives.
- `total`: total request duration in seconds.
- `chunks`: number of streamed events containing answer or reasoning text.
- `status`: `ok`, `timeout`, `connection_error`, or an HTTP status label such
  as `http_500`.
- `prompt` and `t_start`: the submitted prompt and request start time.

The helper accepts `prompt`, `max_tokens` (default `256`), `timeout` (default
`120` seconds), and an optional `url` override.

## Monitoring process resources

`monitor_process` yields one resource-sample dictionary per interval for the
target process and its child processes. By default, it monitors the process
detected by `find_server_pid()`; you can pass a PID explicitly:

```python
from src.monitor import monitor_process

for sample in monitor_process(pid=server_pid, interval=0.2):
    print(sample["rss"], sample["cpu_pct"])
    if sample["rss"] == "DEAD":
        break
```

Samples contain wall-clock and monotonic timestamps, process-tree RSS/USS/VMS,
system available memory, swap used, and CPU percentage. Memory values are in
bytes. When the process exits, the iterator yields a final sample with
`rss` equal to `"DEAD"`.

For the threaded pattern used in the notebook, `run_monitor(stop_event,
samples)` appends samples to a list until the event is set:

```python
import threading
from src.monitor import run_monitor

samples = []
stop_event = threading.Event()
monitor_thread = threading.Thread(
    target=run_monitor,
    args=(stop_event, samples),
    daemon=True,
)
monitor_thread.start()

# Run the request or other work to measure here.

stop_event.set()
monitor_thread.join()
```
