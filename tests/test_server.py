"""Model-free checks for the llama.cpp server process lifecycle."""

import unittest
from unittest.mock import patch

from src.server import LlamaServer

SERVER_CONFIG = {
    "model": "model-id",
    "parallel_slots": 2,
    "context_size": 4096,
    "host": "127.0.0.1",
    "port": 9931,
}


class LlamaServerTests(unittest.TestCase):
    @patch("src.server.subprocess.Popen")
    @patch("src.server.load_config")
    def test_start_builds_command_and_stop_terminates_process(
        self, load_config, popen
    ):
        process = popen.return_value
        process.poll.return_value = None
        server = LlamaServer(SERVER_CONFIG)

        self.assertIs(server.start(), process)
        popen.assert_called_once_with(
            [
                "llama", "serve",
                "-hf", "model-id",
                "--device", "none",
                "--gpu-layers", "0",
                "--metrics",
                "-np", "2",
                "-c", "4096",
                "--host", "127.0.0.1",
                "--port", "9931",
            ]
        )
        server.stop()
        server.stop()

        load_config.assert_not_called()
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with()
        self.assertIsNone(server.process)

    @patch("src.server.load_config")
    def test_start_rejects_an_already_running_process(self, load_config):
        server = LlamaServer(SERVER_CONFIG)
        server.process = unittest.mock.Mock()
        server.process.poll.return_value = None

        with self.assertRaisesRegex(RuntimeError, "already running"):
            server.start()

        load_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
