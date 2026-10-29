import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from scripts.mock_server import Handler, answer
from src.agent_runner import run_tasks, validate
from src.transport import send_request
from workloads.generate import generate


class BaselineTests(unittest.TestCase):
    def test_json_answers_require_correct_integer_and_exact_shape(self):
        step = {"answer_format": "json_integer", "expected": "95"}
        self.assertTrue(validate(step, '{"answer":95}'))
        for value in [
            "95",
            '{"answer":94}',
            '{"answer":"95"}',
            '{"answer":95.0}',
            '{"answer":true}',
            '{"answer":95,"explanation":"x"}',
            "40+55=95",
        ]:
            self.assertFalse(validate(step, value))

    def test_v2_three_step_uses_model_output_and_generation_settings(self):
        tasks = generate(4, seed=101, profile="v2")
        calls = []

        def sender(body, **kw):
            calls.append(body)
            text = answer(body["messages"])
            if body.get("response_format"):
                copying = "latest Tool result" in body["messages"][-1]["content"]
                self.assertEqual(
                    body["chat_template_kwargs"]["enable_thinking"], not copying
                )
                if not copying:
                    self.assertEqual(body["reasoning_budget_tokens"], 512)
                else:
                    self.assertNotIn("reasoning_budget_tokens", body)
                    prompt = body["messages"][-1]["content"]
                    self.assertNotIn("{tool_result}", prompt)
                    latest_tool = next(
                        m["content"]
                        for m in reversed(body["messages"])
                        if m["content"].startswith("Tool result:")
                    )
                    self.assertIn("returned " + latest_tool.split(": ")[1], prompt)
                self.assertNotIn("expected", body)
                text = json.dumps({"answer": int(text)})
            return dict(status="ok", response_text=text)

        with tempfile.TemporaryDirectory() as tmp:
            rows, _ = run_tasks(tasks, 2, tmp, sender=sender)
            self.assertTrue(all(r["status"] == "completed" for r in rows))
            chain = next(r for r in rows if r["task_type"] == "three_step")
            self.assertEqual(chain["steps_completed"], 3)
        self.assertEqual(len(calls), 6)
        tools = [
            m["content"]
            for b in calls
            for m in b["messages"]
            if m["content"].startswith("Tool result:")
        ]
        self.assertIn("Tool result: 102", tools)
        self.assertIn("Tool result: 105", tools)

    def test_seeded_workload(self):
        self.assertEqual(generate(), generate())
        self.assertNotEqual(generate(seed=1), generate(seed=2))
        self.assertEqual(len({t["task_type"] for t in generate()}), 4)

    def test_fifo_cap_dependencies_and_tool_release(self):
        tasks = generate(count=8, interval=0, tool_delay=0.04)
        lock = threading.Lock()
        active = 0
        peak = 0

        def sender(body, **kw):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            text = answer(body["messages"])
            with lock:
                active -= 1
            return dict(status="ok", response_text=text)

        for k in [1, 2, 4]:
            with tempfile.TemporaryDirectory() as tmp:
                peak = 0
                rows, _ = run_tasks(tasks, k, tmp, sender=sender)
                self.assertEqual([r["status"] for r in rows], ["completed"] * 8)
                self.assertLessEqual(peak, k)
                events = [
                    json.loads(x)
                    for x in (Path(tmp) / "events.jsonl").read_text().splitlines()
                ]
                first = [
                    e["task_id"]
                    for e in events
                    if e["event"] == "admit" and e["step_id"] == 0
                ]
                self.assertEqual(first, [t["task_id"] for t in tasks])
                requests = [
                    json.loads(x)
                    for x in (Path(tmp) / "requests.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(requests), 12)
                self.assertTrue(all(r["queue_s"] >= 0 for r in requests))
                if k == 1:
                    self.assertGreater(requests[1]["queue_s"], 0.005)
                    wait = next(e for e in events if e["event"] == "tool_wait")
                    self.assertTrue(
                        any(
                            wait["tool_start"] <= r["dispatch"] < wait["tool_end"]
                            for r in requests
                            if r["task_id"] != wait["task_id"]
                        )
                    )

    def test_failure_releases_slot_and_stops_chain(self):
        tasks = generate(count=4, interval=0)

        def sender(body, **kw):
            return dict(status="timeout", response_text="")

        with tempfile.TemporaryDirectory() as tmp:
            rows, _ = run_tasks(tasks, 1, tmp, sender=sender)
            self.assertEqual(len(rows), 4)
            self.assertTrue(
                all(
                    r["status"] == "timeout" and r["steps_completed"] == 0 for r in rows
                )
            )
            self.assertEqual(
                len((Path(tmp) / "requests.jsonl").read_text().splitlines()), 4
            )

    def test_http_success_failure_timeout_and_truncated_stream(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        try:
            for prompt, expected in [
                ("Return only the integer sum of 2 and 3.", "ok"),
                ("HTTP_ERROR", "http_500"),
                ("INCOMPLETE", "incomplete_stream"),
                ("TIMEOUT", "timeout"),
            ]:
                result = send_request(
                    dict(messages=[dict(role="user", content=prompt)], max_tokens=64),
                    timeout=0.07,
                    url=url,
                )
                self.assertEqual(result["status"], expected)
                if expected == "ok":
                    self.assertEqual(result["response_text"], "5")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
