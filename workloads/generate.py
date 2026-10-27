"""Seeded task fixtures. Lengths are not measured token counts."""

import argparse
import json
import random
from pathlib import Path


def generate(count=16, seed=42, interval=0.02, tool_delay=0.1):
    if count < 1 or interval < 0 or tool_delay < 0:
        raise ValueError("Invalid workload size/timing")
    rng = random.Random(seed)
    tasks = []
    for i in range(count):
        kind = ["short", "long_context", "long_output", "three_step"][i % 4]
        a, b = rng.randint(10, 40), rng.randint(50, 90)
        prompt = f"Return only the integer sum of {a} and {b}."
        steps = [dict(prompt=prompt, max_tokens=64, expected=str(a + b))]
        if kind == "long_context":
            records = "\n".join(
                f"Record {j}: value {rng.randint(100,999)}." for j in range(100)
            )
            steps[0]["prompt"] = records + "\nIgnore the records. " + prompt
        elif kind == "long_output":
            steps = [
                dict(
                    prompt="Explain FIFO scheduling in at least 180 words. End with END.",
                    max_tokens=512,
                    min_words=180,
                    suffix="END",
                )
            ]
        elif kind == "three_step":
            steps[0].update(tool_delay_s=tool_delay, tool_add=7)
            steps += [
                dict(
                    prompt="Return only the integer in the latest tool result.",
                    max_tokens=64,
                    expected=str(a + b + 7),
                    tool_delay_s=tool_delay,
                    tool_add=3,
                ),
                dict(
                    prompt="Return only the integer in the latest tool result.",
                    max_tokens=64,
                    expected=str(a + b + 10),
                ),
            ]
        tasks.append(
            dict(
                task_id=f"task-{i:04}",
                task_type=kind,
                arrival_offset_s=round(i * interval, 6),
                steps=steps,
            )
        )
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="workloads/tasks.jsonl")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interval", type=float, default=0.02)
    a = parser.parse_args()
    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(t) + "\n" for t in generate(a.count, a.seed, a.interval)),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
