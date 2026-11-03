"""Aggregate enforced-budget experiments; retain startup and request failures."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import statistics
from src.utils import percentile


def json_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def analyze_trial(path):
    manifest = read_json(path / 'manifest.json')
    outcome = read_json(path / 'outcome.json')
    if not manifest or not outcome:
        return None
    inputs = json_rows(path / 'workload.jsonl')
    tasks = json_rows(path / 'measured/tasks.jsonl')
    requests = json_rows(path / 'measured/requests.jsonl')
    warmup = json_rows(path / 'warmup/tasks.jsonl')
    cgroup = json_rows(path / 'cgroup.jsonl')
    complete = [row for row in tasks if row['status'] == 'completed']
    raw_worker = read_json(path / 'measured/worker_summary.json')
    drain = raw_worker.get('drain_s')
    start = read_json(path / 'measured/timeline.json').get('origin_wall')
    # Timeline schema can differ by upstream version: use explicit emitted key.
    timeline = read_json(path / 'measured/timeline.json')
    start = timeline.get('t_wall_origin', timeline.get('origin_wall', timeline.get('wall_time')))
    if start is None:
        start = min((r.get('t_start') for r in requests if r.get('t_start')), default=None)
    measured_cgroup = [r for r in cgroup if start is not None and r['wall_time'] >= start
                       and (drain is None or r['wall_time'] <= start + drain)]
    psi = None
    if len(measured_cgroup) > 1:
        first, last = measured_cgroup[0], measured_cgroup[-1]
        elapsed = last['monotonic'] - first['monotonic']
        psi = (last['memory.pressure']['some']['total'] - first['memory.pressure']['some']['total']) / (elapsed * 1e6) * 100
    good_requests = [r for r in requests if r['status'] == 'ok']
    def vals(key):
        return [r[key] for r in good_requests if isinstance(r.get(key), (int, float))]
    event = outcome.get('before_shutdown', {}).get('memory.events', {})
    peak = max((r['memory.peak'] for r in cgroup), default=None)
    row = dict(run=path.name, budget_mib=manifest['budget_mib'], concurrency=manifest['concurrency'],
        status=outcome['status'], ready=outcome.get('ready'), startup_s=outcome.get('startup_s'),
        input_tasks=len(inputs), terminal_tasks=len(tasks), completed=len(complete),
        failure_rate=1-len(complete)/len(inputs) if inputs else None,
        warmup_completed=sum(r['status'] == 'completed' for r in warmup),
        request_count=len(requests), http_ok=sum(r['status'] == 'ok' for r in requests),
        task_statuses=dict(Counter(r['status'] for r in tasks)),
        drain_s=drain, successful_tasks_s=len(complete)/drain if drain else None,
        task_p50_s=percentile([r['latency_s'] for r in complete], .5),
        task_p95_s=percentile([r['latency_s'] for r in complete], .95),
        ttft_p50_s=percentile(vals('ttft'), .5), ttft_p95_s=percentile(vals('ttft'), .95),
        content_ttft_p50_s=percentile(vals('ttft_content'), .5),
        content_ttft_p95_s=percentile(vals('ttft_content'), .95),
        ready_to_first_p95_s=percentile([r['queue_s']+r['ttft'] for r in good_requests
            if isinstance(r.get('ttft'), (int, float))], .95),
        ttft_samples=len(vals('ttft')), peak_cgroup_mib=peak/1024**2 if peak else None,
        memory_max_events=event.get('max'), oom=event.get('oom'), oom_kill=outcome.get('oom_kill'),
        memory_psi_some_pct=psi, pressure_samples=len(measured_cgroup),
        generated_tokens=sum((r.get('usage') or {}).get('completion_tokens', 0) for r in requests),
        three_step_completed=sum(r['task_type']=='three_step' for r in complete),
        collector_errors=outcome.get('monitor_errors', []) + read_json(path / 'measured/resource_errors.json')
            if (path / 'measured/resource_errors.json').exists() else outcome.get('monitor_errors', []))
    # Startup failures have no measured throughput/TTFT, not zero latency.
    return row


def stratify_trial(path):
    kinds = {r['task_id']: r['task_type'] for r in json_rows(path / 'workload.jsonl')}
    groups = defaultdict(list)
    for request in json_rows(path / 'measured/requests.jsonl'):
        groups[(kinds.get(request['task_id']), request['step_id'])].append(request)
    rows = []
    for (kind, step), group in sorted(groups.items()):
        values = [r['ttft'] for r in group if r['status'] == 'ok' and r.get('ttft') is not None]
        rows.append(dict(run=path.name, task_type=kind, step=step, requests=len(group),
            http_ok=sum(r['status'] == 'ok' for r in group),
            ttft_p50_s=percentile(values, .5), ttft_p95_s=percentile(values, .95)))
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    rows = [r for path in sorted(a.input.iterdir()) if path.is_dir() and (r := analyze_trial(path))]
    a.output.mkdir(exist_ok=True, parents=True)
    (a.output / 'analysis.json').write_text(json.dumps(rows, indent=2))
    strata = [r for path in sorted(a.input.iterdir()) if path.is_dir()
              for r in stratify_trial(path) if (path / 'manifest.json').exists()]
    (a.output / 'ttft_by_type_step.json').write_text(json.dumps(strata, indent=2))
    if rows:
        with (a.output / 'aggregate.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['budget_mib']].append(row)
    summaries = []
    for budget, group in sorted(grouped.items(), reverse=True):
        metrics = {}
        for key in ('drain_s', 'ttft_p50_s', 'ttft_p95_s', 'task_p95_s', 'successful_tasks_s', 'peak_cgroup_mib', 'memory_psi_some_pct'):
            values = [r[key] for r in group if r[key] is not None]
            metrics[key] = dict(n=len(values), mean=statistics.mean(values) if values else None,
                                min=min(values) if values else None, max=max(values) if values else None)
        summaries.append(dict(budget_mib=budget, repeats=len(group),
            completed=sum(r['completed'] for r in group), input_tasks=sum(r['input_tasks'] for r in group),
            oom_kills=sum(r['oom_kill'] or 0 for r in group), metrics=metrics))
    (a.output / 'by_budget.json').write_text(json.dumps(summaries, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
