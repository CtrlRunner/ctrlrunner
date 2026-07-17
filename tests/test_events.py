import unittest

from ctrlrunner.reporting.events import EVENT_TYPES, SCHEMA_VERSION, EventEnvelope, EventSubscriber


class EventEnvelopeTests(unittest.TestCase):
    def test_defaults_schema_version_and_project(self):
        env = EventEnvelope(type="run_start", timestamp=1.0, payload={"total": 5})
        self.assertEqual(env.schema_version, SCHEMA_VERSION)
        self.assertIsNone(env.project)

    def test_explicit_project_is_kept(self):
        env = EventEnvelope(type="run_start", timestamp=1.0, payload={}, project="smoke")
        self.assertEqual(env.project, "smoke")
        self.assertEqual(env.to_dict()["project"], "smoke")

    def test_to_dict_shape(self):
        env = EventEnvelope(type="test_end", timestamp=2.0, payload={"outcome": "passed"})
        d = env.to_dict()
        self.assertEqual(
            d,
            {
                "schemaVersion": SCHEMA_VERSION,
                "type": "test_end",
                "timestamp": 2.0,
                "project": None,
                "payload": {"outcome": "passed"},
            },
        )

    def test_to_dict_is_json_serializable(self):
        import json

        env = EventEnvelope(
            type="run_end", timestamp=3.0, payload={"total": 1, "passed": 1, "failed": 0}
        )
        json.dumps(env.to_dict())  # must not raise

    def test_unknown_event_type_raises_at_construction(self):
        # EVENT_TYPES is declared but was never enforced at emit
        # time -- a typo'd event type must fail loudly, not silently
        # ship as an unrecognized type to every subscriber.
        with self.assertRaises(ValueError):
            EventEnvelope(type="test_finished", timestamp=1.0, payload={})

    def test_all_emitted_event_types_are_declared(self):
        # sanity check that the constant tracking "known" types actually
        # covers what the orchestrator emits (see test_orchestrator_and_worker.py)
        for t in (
            "run_start",
            "test_start",
            "test_end",
            "run_end",
            "worker_spawned",
            "worker_terminated",
        ):
            self.assertIn(t, EVENT_TYPES)


class UnifiedResultShapeTests(unittest.TestCase):
    """This module promises ONE schema for streaming and reporting.
    The test_end event payload and the JSON reporter's per-test entry
    must be the identical dict, built by result_to_public_dict()."""

    def _make_result(self):
        from ctrlrunner.reporting.reporter import Result

        return Result(
            test_id="mod::test_x[a]",
            outcome="passed",
            error=None,
            duration=1.23456,
            case_id="TC-1",
            tags=("smoke", "auth"),
            properties={"team": "backend"},
            attempts=2,
            artifacts=("shot.png",),
            steps=[{"name": "test body"}],
            groups={"file": "mod.py"},
            project="smoke",
            retries_configured=1,
            worker_restart_overhead=0.5,
            quarantined=False,
            quarantine_reason=None,
            worker_id=3,
            near_timeout=True,
            assert_details={"expr": "a == b"},
            logs=[{"attempt": 1, "stdout": "hi", "stderr": "", "records": [], "truncated": False}],
        )

    def test_json_reporter_entry_equals_test_end_payload(self):
        import json
        import os
        import tempfile

        from ctrlrunner.execution.orchestrator import Orchestrator
        from ctrlrunner.reporting.events import result_to_public_dict
        from ctrlrunner.reporting.reporters import JsonReporter

        result = self._make_result()
        expected = result_to_public_dict(result)

        self.assertEqual(Orchestrator._result_payload(result), expected)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = os.path.join(tmp, "results.json")
            JsonReporter(out).on_run_end([result], 2.0)
            with open(out, encoding="utf-8") as f:
                payload = json.load(f)
        self.assertEqual(payload["tests"][0], expected)

    def test_public_dict_uses_camel_case_id_key(self):
        from ctrlrunner.reporting.events import result_to_public_dict

        d = result_to_public_dict(self._make_result())
        self.assertEqual(d["id"], "mod::test_x[a]")
        self.assertNotIn("test_id", d)
        self.assertEqual(d["retriesConfigured"], 1)
        self.assertEqual(d["workerId"], 3)
        self.assertTrue(d["nearTimeout"])
        self.assertEqual(d["duration"], 1.235)

    def test_public_dict_includes_assert_details(self):
        from ctrlrunner.reporting.events import result_to_public_dict

        d = result_to_public_dict(self._make_result())
        self.assertEqual(d["assertDetails"], {"expr": "a == b"})

    def test_public_dict_includes_logs(self):
        from ctrlrunner.reporting.events import result_to_public_dict

        d = result_to_public_dict(self._make_result())
        self.assertEqual(d["logs"][0]["stdout"], "hi")

    def test_public_dict_includes_flaky(self):
        from ctrlrunner.reporting.events import result_to_public_dict
        from ctrlrunner.reporting.reporter import Result

        r = Result(test_id="m::t", outcome="passed", error=None, duration=0.1, flaky=True)
        self.assertTrue(result_to_public_dict(r)["flaky"])

    def test_public_dict_includes_started_at(self):
        from ctrlrunner.reporting.events import result_to_public_dict
        from ctrlrunner.reporting.reporter import Result

        r = Result(test_id="m::t", outcome="passed", error=None, duration=0.1, started_at=1000.5)
        self.assertEqual(result_to_public_dict(r)["startedAt"], 1000.5)


class EventSubscriberTests(unittest.TestCase):
    def test_base_class_on_event_is_not_implemented(self):
        sub = EventSubscriber()
        with self.assertRaises(NotImplementedError):
            sub.on_event(EventEnvelope(type="run_start", timestamp=0.0, payload={}))

    def test_subclass_can_override_on_event(self):
        received = []

        class MySubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        sub = MySubscriber()
        env = EventEnvelope(type="test_start", timestamp=1.0, payload={"id": "mod::x"})
        sub.on_event(env)
        self.assertEqual(received, [env])


if __name__ == "__main__":
    unittest.main()
