"""Build the deterministic v2 JSONL workload used by the benchmark.

The fixture contains four task types in a repeating order: short arithmetic,
long-context arithmetic, long prose, and a three-step tool chain. Random values
come from a private ``random.Random`` instance, so a seed does not affect or get
affected by the rest of the Python process. Prompt lengths are character-based
fixtures, not tokenizer-measured context sizes.
"""

import argparse
import json
import random
from pathlib import Path


def generate(count=16, seed=42, interval=0.02, tool_delay=0.1):
    """Return ``count`` deterministic v2 task dictionaries.

    Args:
        count: Number of tasks. Must be positive; task types cycle through four
            categories, so counts need not be divisible by four.
        seed: Seed for arithmetic operands and long-context distractor values.
        interval: Scheduled arrival spacing in seconds.
        tool_delay: Simulated external-tool delay for each tool-chain step.

    Returns:
        Task mappings accepted by :func:`src.agent_runner.run_tasks`. Arithmetic
        steps request bounded thinking and a strict integer JSON object;
        long-prose steps disable thinking and use length/ending checks.

    Raises:
        ValueError: If count is less than one or either duration is negative.
    """
    if count < 1 or interval < 0 or tool_delay < 0:
        raise ValueError("Invalid workload size/timing")
    rng = random.Random(seed)
    tasks = []

    # First make the task skeletons: task types cycle in a fixed order while
    # arithmetic and distractor values come from the seeded random generator.
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

    # Convert the skeletons to the only supported benchmark profile. Arithmetic
    # uses bounded thinking plus strict JSON; prose uses length and suffix checks.
    for task in tasks:
        task["workload_profile"] = "v2-bounded-thinking-json"
        for step_index, step in enumerate(task["steps"]):
            if "expected" in step:
                step["prompt"] = (
                    step["prompt"]
                    .replace("Return only the integer sum of", "Calculate the sum of")
                    .replace(
                        "Return only the integer in the latest tool result.",
                        "Read the number in the latest Tool result message. "
                        "The external tool has now returned {tool_result}. "
                        "Copy this NEW value, replacing your previous answer.",
                    )
                    + " Return a JSON object with the result in the answer field."
                )
                # The schema constrains the response shape; local validation
                # still compares the returned integer with the expected value.
                step["answer_format"] = "json_integer"
                step["max_tokens"] = 768
                step["generation"] = {
                    "chat_template_kwargs": {"enable_thinking": True},
                    "reasoning_budget_tokens": 512,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "calculation",
                            "schema": {
                                "type": "object",
                                "properties": {"answer": {"type": "integer"}},
                                "required": ["answer"],
                                "additionalProperties": False,
                            },
                        },
                    },
                }
                if step_index > 0:
                    # Tool-copy steps use the actual prior tool value, not expected.
                    step["max_tokens"] = 128
                    step["generation"]["chat_template_kwargs"][
                        "enable_thinking"
                    ] = False
                    step["generation"].pop("reasoning_budget_tokens")
            else:
                # The prose task gets a system instruction and a longer output
                # budget, with thinking disabled to reserve tokens for the answer.
                task["initial_messages"] = [
                    {
                        "role": "system",
                        "content": "Follow the user's length requirement. "
                        "Always end your final response with END alone on its own line. "
                        "FIFO means the oldest queued job is processed first.",
                    }
                ]
                step["prompt"] = (
                    "Explain FIFO scheduling in six paragraphs of 40 to 50 words each. "
                    "Cover arrival order, queue operation, a practical example, advantages, "
                    "head-of-line blocking, and comparison with other scheduling policies. "
                    "Write at least 240 words in total. After all six paragraphs, "
                    "write END alone on the final line."
                )
                step["max_tokens"] = 1024
                step["generation"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }
    return tasks


def main():
    """Write generated tasks as one JSON object per line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="workloads/tasks-v2.jsonl")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interval", type=float, default=0.02)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(task) + "\n"
            for task in generate(args.count, args.seed, args.interval)
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
