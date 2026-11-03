"""Reproducible, shuffled memory-budget matrix; each child has its own watchdog."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workload', type=Path, required=True)
    p.add_argument('--server', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--libraries', required=True)
    p.add_argument('--budgets-mib', type=int, nargs='+', required=True)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--seed', type=int, default=20261103)
    a = p.parse_args()
    if a.repeats < 1 or any(v <= 0 for v in a.budgets_mib) or len(set(a.budgets_mib)) != len(a.budgets_mib):
        p.error('Positive repeats and distinct positive budgets are required')
    a.output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(a.seed)
    plan = []
    for repeat in range(1, a.repeats+1):
        order = a.budgets_mib.copy()
        rng.shuffle(order)
        for budget in order:
            plan.append(dict(repeat=repeat, budget_mib=budget, name=f'r{repeat}-m{budget}'))
    (a.output / 'matrix-plan.json').write_text(json.dumps(dict(seed=a.seed, order=plan,
        workload_sha256=hashlib.sha256(a.workload.read_bytes()).hexdigest(),
        concurrency=2, created_wall=time.time()), indent=2))
    for index, trial in enumerate(plan, 1):
        cmd = [sys.executable, '-m', 'experiments.run_memory_budget', '--server', a.server,
               '--model', a.model, '--libraries', a.libraries, '--budget-mib', str(trial['budget_mib']),
               '--workload', str(a.workload), '--output', str(a.output / trial['name'])]
        print('TRIAL_START', index, len(plan), trial['name'], time.time(), flush=True)
        subprocess.run(cmd, check=True, timeout=1200)
        print('TRIAL_DONE', index, len(plan), trial['name'], time.time(), flush=True)
    print('MATRIX_FINISHED', flush=True)


if __name__ == '__main__':
    main()
