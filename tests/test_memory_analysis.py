import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from experiments.analyze_memory_budget import analyze_trial
from workloads.memory_budget import generate_memory_tasks


class MemoryAnalysisTests(unittest.TestCase):
    def test_frozen_measured_and_warmup_inputs_match_original_experiment(self):
        def digest(tasks):
            return hashlib.sha256(''.join(json.dumps(t)+'\n' for t in tasks).encode()).hexdigest()
        expected = '78abb94470ab122c202ae33671dc70cd5ef2b8c89ec97afb8b9a29f64815da7d'
        self.assertEqual(digest(generate_memory_tasks()), expected)
        fixture = Path(__file__).resolve().parents[1] / 'workloads/memory-budget-cpu-v1.jsonl'
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), expected)
        self.assertEqual(digest(generate_memory_tasks(4, 101)),
                         'a516d6fbf35c8f31875fee7f62e25ae1a45fc9f4fa30d84093a813cd9dc3b797')

    def test_profile_is_deterministic_and_preserves_quality_threshold(self):
        self.assertEqual(generate_memory_tasks(), generate_memory_tasks())
        tasks = generate_memory_tasks()
        self.assertEqual(len(tasks), 32)
        self.assertEqual(sum(t['task_type'] == 'three_step' for t in tasks), 8)
        prose = next(t for t in tasks if t['task_type'] == 'long_output')['steps'][0]
        self.assertEqual(prose['min_words'], 140)
        self.assertEqual(prose['max_tokens'], 1024)

    def test_startup_oom_is_failure_and_has_no_zero_ttft(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'manifest.json').write_text(json.dumps({'budget_mib': 100, 'concurrency': 2}))
            (path / 'outcome.json').write_text(json.dumps({'status': 'startup_exit', 'ready': False,
                'oom_kill': 1, 'before_shutdown': {'memory.events': {'oom': 1, 'oom_kill': 1}}}))
            (path / 'workload.jsonl').write_text('{}\n{}\n')
            row = analyze_trial(path)
            self.assertEqual(row['input_tasks'], 2)
            self.assertEqual(row['failure_rate'], 1)
            self.assertEqual(row['oom_kill'], 1)
            self.assertIsNone(row['ttft_p50_s'])
            self.assertIsNone(row['drain_s'])

    def test_ttft_excludes_missing_first_tokens_but_retains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'measured').mkdir()
            (path / 'manifest.json').write_text(json.dumps({'budget_mib': 100, 'concurrency': 2}))
            (path / 'outcome.json').write_text(json.dumps({'status': 'finished', 'oom_kill': 0}))
            (path / 'workload.jsonl').write_text('{}\n{}\n')
            (path / 'measured/requests.jsonl').write_text(
                json.dumps(dict(status='ok', ttft=.2, ttft_content=.3, queue_s=2)) + '\n' +
                json.dumps(dict(status='timeout', ttft=None, ttft_content=None)) + '\n')
            row = analyze_trial(path)
            self.assertEqual(row['ttft_p50_s'], .2)
            self.assertEqual(row['ready_to_first_p95_s'], 2.2)
            self.assertEqual(row['http_ok'], 1)
            self.assertEqual(row['request_count'], 2)
