import unittest
from src.resource_monitor import parse_psi, thread_deltas, core_percent


class ResourceTests(unittest.TestCase):
    def test_psi_preserves_cumulative_stall_and_missing_full(self):
        parsed = parse_psi("some avg10=1.20 avg60=0.40 avg300=0.10 total=123456\n")
        self.assertEqual(parsed["some"]["total"], 123456)
        self.assertNotIn("full", parsed)

    def test_thread_cpu_deltas_and_new_threads(self):
        self.assertEqual(thread_deltas({1: 2, 2: 4}, {1: 2.5, 3: 10}, .5), {1: 100})
        self.assertEqual(thread_deltas({1: 2}, {1: 3}, 0), {})

    def test_subsecond_idle_is_not_false_busy(self):
        self.assertEqual(core_percent({'user': 1, 'idle': 2}, {'user': 1, 'idle': 2.5}), (0, 0, .5))
        busy, wait, total = core_percent({'user': 0, 'idle': 0, 'iowait': 0},
                                        {'user': .25, 'idle': .2, 'iowait': .05})
        self.assertAlmostEqual(busy, 50)
        self.assertAlmostEqual(wait, 10)
        self.assertAlmostEqual(total, .5)

    def test_guest_time_not_double_counted(self):
        self.assertEqual(core_percent({'user': 0, 'idle': 0, 'guest': 0},
                                     {'user': .5, 'idle': .5, 'guest': .5}), (50, 0, 1))
        self.assertIsNone(core_percent({'idle': 1}, {'idle': 1}))
