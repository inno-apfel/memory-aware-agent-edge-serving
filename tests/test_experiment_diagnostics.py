"""Check collector cleanup and ownership of managed versus external servers."""
from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.run_experiment import parse_args, run_one


class ExperimentDiagnosticsTests(unittest.TestCase):
    def test_cli_diagnostics_are_opt_in(self):
        self.assertFalse(parse_args([]).diagnostics)
        args = parse_args(["--pid", "123", "--diagnostics"])
        self.assertEqual(args.pid, 123)
        self.assertTrue(args.diagnostics)

    def test_collectors_close_on_success_and_failure_without_stopping_external_server(self):
        for external in (False, True):
            for failing in (False, True):
                with self.subTest(external=external, failing=failing), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                    mocks = {name: stack.enter_context(patch("experiments.run_experiment." + name))
                             for name in ("LlamaServer", "psutil.Process", "requests.get",
                                          "wait_for_server", "create_manifest", "monitor_process",
                                          "ResourceMonitor", "run_tasks")}
                    mocks["create_manifest"].return_value = {"mode": "REAL_MODEL"}
                    mocks["monitor_process"].return_value = iter(())
                    mocks["run_tasks"].return_value = ([], 1.0)
                    if failing:
                        mocks["run_tasks"].side_effect = RuntimeError("scheduler failed")
                    args = Namespace(pid=123 if external else None, diagnostics=True, timeout=1)
                    call = lambda: run_one(args, Path(tmp), b"", [],
                        "http://127.0.0.1:9931/v1/chat/completions", Path(tmp), "test", False,
                        {"server": {"host": "127.0.0.1", "port": 9931}}, 1)
                    if failing:
                        with self.assertRaisesRegex(RuntimeError, "scheduler failed"):
                            call()
                    else:
                        self.assertEqual(call()["tasks"], 0)
                    collector = mocks["ResourceMonitor"].return_value
                    collector.start.assert_called_once_with()
                    collector.close.assert_called_once_with()
                    if external:
                        mocks["LlamaServer"].assert_not_called()
                        mocks["psutil.Process"].return_value.terminate.assert_not_called()
                        mocks["psutil.Process"].return_value.kill.assert_not_called()
                    else:
                        mocks["LlamaServer"].return_value.stop.assert_called_once_with()
