import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.memory_budget import MemoryBudget, key_values, parse_pressure, snapshot


class MemoryBudgetTests(unittest.TestCase):
    def test_counters_and_pressure_preserve_units(self):
        self.assertEqual(key_values('oom 2\noom_kill 1\n'), {'oom': 2, 'oom_kill': 1})
        result = parse_pressure('some avg10=0.00 avg60=0.00 avg300=0.00 total=123\n')
        self.assertEqual(result['some']['total'], 123)
        self.assertNotIn('full', result)

    def test_budget_rejects_invalid_limit_or_missing_delegation(self):
        with self.assertRaises(ValueError):
            MemoryBudget(0)
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'cgroup.subtree_control').write_text('cpu pids')
            with self.assertRaisesRegex(RuntimeError, 'delegate'):
                MemoryBudget(1024, root).create()

    @unittest.skipUnless(os.environ.get('MEMORY_CGROUP_TEST') == '1', 'Explicit Linux integration opt-in')
    def test_actual_budget_kills_only_owned_over_limit_child(self):
        group = MemoryBudget(64 * 1024**2)
        group.create()
        try:
            command = [sys.executable, '-m', 'scripts.cgroup_exec', str(group.path), '--',
                       sys.executable, '-c', 'x=bytearray(256*1024*1024); print(len(x))']
            result = subprocess.run(command, timeout=30, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            data = snapshot(group.path)
            self.assertEqual(data['memory.max'], 64 * 1024**2)
            self.assertEqual(data['memory.swap.max'], 0)
            self.assertGreaterEqual(data['memory.events']['oom_kill'], 1)
            self.assertFalse((group.path / 'cgroup.procs').read_text().strip())
        finally:
            group.close()
