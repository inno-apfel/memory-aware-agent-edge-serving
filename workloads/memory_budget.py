"""Freeze a separately versioned 32-task profile after CPU-model calibration.

Keep the upstream 140-word prose validator and output-token cap. Strengthen the
requested length rather than relaxing quality to accommodate short answers.
"""
import argparse
import json
from pathlib import Path
from workloads._memory_budget_base import generate


def generate_memory_tasks(count=32, seed=20261103):
    tasks = generate(count=count, seed=seed, interval=.02, context_records=100,
                     prefix_mode='unique', tool_delay=.1)
    for task in tasks:
        task['workload_profile'] = 'memory-budget-cpu-v1'
        if task['task_type'] == 'long_output':
            task['initial_messages'][0]['content'] += (
                ' The response must contain at least 300 words. Do not summarize early. '
                'Write six detailed paragraphs before the final END line.')
            task['steps'][0]['prompt'] = (
                'Write a detailed explanation of FIFO scheduling in exactly six paragraphs. '
                'Each paragraph must contain 50 to 60 words, for at least 300 words total. '
                'Paragraph 1: arrival order and fairness. Paragraph 2: how enqueue and dequeue work. '
                'Paragraph 3: a concrete queue example with three jobs and their order. '
                'Paragraph 4: implementation simplicity and advantages. '
                'Paragraph 5: explain head-of-line blocking with an example. '
                'Paragraph 6: compare FIFO with priority and shortest-job scheduling. '
                'Expand every topic with details. Do not merge the paragraphs or finish early. '
                'After all six paragraphs, write END alone on the final line.')
    return tasks


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--count', type=int, default=32)
    p.add_argument('--seed', type=int, default=20261103)
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        for task in generate_memory_tasks(a.count, a.seed):
            f.write(json.dumps(task) + '\n')


if __name__ == '__main__':
    main()
