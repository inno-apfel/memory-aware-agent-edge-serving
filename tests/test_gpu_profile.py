"""Pinned GPU configuration, argument resolution and version/hash safeguards."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.server import LlamaServer, load_launch_config, main


class GPUProfileTests(unittest.TestCase):
    def test_gpu_profile_matches_recorded_flags_and_paths(self):
        root = Path(__file__).resolve().parents[1]
        config = load_launch_config(root / 'phase1-gpu.yml', binary='/tmp/llama-server')
        command = LlamaServer(config['server']).build_command()
        self.assertEqual(command[0], str(Path('/tmp/llama-server').resolve()))
        self.assertEqual(command[command.index('-m')+1], str(root / 'models/Qwen3.5-0.8B-Q8_0.gguf'))
        self.assertNotIn('--device', command)
        expected = {'--gpu-layers':'all', '-np':'10', '-c':'40960', '-fa':'on',
                    '-t':'8', '-tb':'8', '--cache-ram':'0', '--host':'127.0.0.1', '--port':'9931'}
        for flag, value in expected.items():
            self.assertEqual(command[command.index(flag)+1], value)
        for flag in ('--no-cache-idle-slots', '--no-context-shift', '--no-kv-unified', '--metrics'):
            self.assertIn(flag, command)

    @patch.dict(os.environ, {'GGML_CUDA_DISABLE_GRAPHS':'1', 'PROFILE_TEST_KEEP':'yes'})
    def test_gpu_profile_clears_disable_graph_env_only_in_child(self):
        config = load_launch_config(Path(__file__).resolve().parents[1] / 'phase1-gpu.yml')
        env = LlamaServer(config['server']).launch_environment()
        self.assertNotIn('GGML_CUDA_DISABLE_GRAPHS', env)
        self.assertEqual(env['PROFILE_TEST_KEEP'], 'yes')
        self.assertEqual(os.environ['GGML_CUDA_DISABLE_GRAPHS'], '1')

    @patch('src.server.subprocess.run')
    def test_pinned_profile_rejects_wrong_model_and_runtime(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'model.gguf'
            model.write_bytes(b'fixture')
            server = LlamaServer(dict(command=['llama-server'],model_file=str(model),
                model_sha256='wrong',expected_version_text=['build 11960'],
                parallel_slots=10,context_size=40960,host='127.0.0.1',port=9931))
            with self.assertRaisesRegex(RuntimeError, 'Model SHA256'):
                server.verify_profile()
            run.assert_not_called()
            server.server_config['model_sha256'] = hashlib.sha256(b'fixture').hexdigest()
            run.return_value.stdout, run.return_value.stderr = 'build 1', ''
            with self.assertRaisesRegex(RuntimeError, 'Runtime version'):
                server.verify_profile()
            run.return_value.stdout = 'build 11960'
            server.verify_profile()

    @patch('src.server.subprocess.Popen')
    def test_dry_run_resolves_profile_without_launching(self, popen):
        with patch('builtins.print'):
            self.assertEqual(main(['--config',str(Path(__file__).resolve().parents[1]/'phase1-gpu.yml'), '--dry-run']),0)
        popen.assert_not_called()
