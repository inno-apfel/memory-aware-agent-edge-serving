# Frozen generator from main 39aea8c for memory-budget-cpu-v1.
# Keep this experimental recipe independent of upstream workload revisions.
"""Deterministic workload generation for context, tool-delay and prefix-cache sweeps."""
import argparse
import json
import random
from pathlib import Path


def generate(count=16, seed=42, interval=0.02, tool_delay=0.1,
             context_records=100, prefix_mode="unique"):
    if count < 1 or interval < 0 or tool_delay < 0 or context_records < 0:
        raise ValueError("Invalid workload size/timing/context")
    if prefix_mode not in {"shared", "unique"}:
        raise ValueError("prefix_mode must be shared or unique")
    rng = random.Random(seed)
    tasks = []
    shared_records = "\n".join(
        f"Common record {j}: reference value {100 + (j % 887)}."
        for j in range(context_records)
    )
    for i in range(count):
        kind = ["short", "long_context", "long_output", "three_step"][i % 4]
        a, b = rng.randint(10, 40), rng.randint(50, 90)
        prompt = f"Calculate the sum of {a} and {b}. Return a JSON object with the result in the answer field."
        steps = [{"prompt": prompt, "max_tokens": 768, "expected": str(a + b), "answer_format": "json_integer"}]
        initial_messages = []
        if kind == "long_context":
            if prefix_mode == "shared":
                records = shared_records
            else:
                records = "\n".join(
                    f"Record {j}: value {rng.randint(100, 999)}."
                    for j in range(context_records)
                )
            steps[0]["prompt"] = (
                records + ("\n" if records else "")
                + "Ignore the records. " + prompt
            )
        elif kind == "long_output":
            initial_messages = [{"role": "system", "content": (
                "Follow the user's length requirement. Always end your final response "
                "with END alone on its own line. FIFO means the oldest queued job is processed first."
            )}]
            steps = [{
                "prompt": "Explain FIFO scheduling in six paragraphs, one paragraph for each topic: "
                          "arrival order, queue operation, a practical example, advantages, "
                          "head-of-line blocking, and comparison with other scheduling policies. "
                          "Write 25 to 35 words per paragraph and at least 150 words total. "
                          "After all six paragraphs, write END alone on the final line.",
                "max_tokens": 1024, "min_words": 140, "suffix": "END",
                "generation": {"chat_template_kwargs": {"enable_thinking": False}},
            }]
        elif kind == "three_step":
            steps[0].update(tool_delay_s=tool_delay, tool_add=7)
            steps += [
                {"prompt": "Read the number in the latest Tool result message. The external tool has now returned {tool_result}. Copy this NEW value, replacing your previous answer. Return a JSON object with the result in the answer field.",
                 "max_tokens": 128, "expected": str(a + b + 7), "answer_format": "json_integer",
                 "tool_delay_s": tool_delay, "tool_add": 3,
                 "generation": {"chat_template_kwargs": {"enable_thinking": False}}},
                {"prompt": "Read the number in the latest Tool result message. The external tool has now returned {tool_result}. Copy this NEW value, replacing your previous answer. Return a JSON object with the result in the answer field.",
                 "max_tokens": 128, "expected": str(a + b + 10), "answer_format": "json_integer",
                 "generation": {"chat_template_kwargs": {"enable_thinking": False}}},
            ]
        for s in steps:
            if s.get("answer_format") == "json_integer":
                s["generation"] = s.get("generation", {})
                if not s.get("generation", {}).get("chat_template_kwargs", {}).get("enable_thinking") is False:
                    s["generation"].update({
                        "chat_template_kwargs": {"enable_thinking": True},
                        "reasoning_budget_tokens": 512,
                    })
                s["generation"]["response_format"] = {
                    "type": "json_schema", "json_schema": {
                        "name": "calculation", "schema": {
                            "type": "object", "properties": {"answer": {"type": "integer"}},
                            "required": ["answer"], "additionalProperties": False,
                        }
                    }
                }
        tasks.append({
            "task_id": f"task-{i:04d}", "task_type": kind,
            "arrival_offset_s": round(i * interval, 6), "steps": steps,
            "initial_messages": initial_messages,
            "workload_profile": "phase1-sweep-v1",
            "context_records": context_records if kind == "long_context" else 0,
            "prefix_mode": prefix_mode,
            "workload_seed": seed,
            "arrival_interval_s": interval,
        })
    return tasks

