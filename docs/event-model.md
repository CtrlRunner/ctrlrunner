# Event model (for reporter/plugin authors)

[← Back to README](../README.md)

This page covers *observing* a run. To actually do something around it
(start/stop shared infrastructure, per-test instrumentation) see
[hooks.md](hooks.md)'s `ctrlrunner_configure`/`ctrlrunner_sessionfinish`/
`ctrlrunner_runtest_*` instead -- `ConsoleReporter.on_run_start(total: int)`
below only ever receives a test count, not the config, because reporting
and driving a run are deliberately different jobs here.

Two independent, stable interfaces observe a run -- neither depends on
or breaks the other:

- **`ConsoleReporter`** (`ctrlrunner.reporting.reporters`) -- the existing
  `on_run_start`/`on_test_start`/`on_test_end`/`on_run_end`, unchanged.
  What `line`/`dots`/`json` already are; write your own the same way.
- **`EventSubscriber`** (`ctrlrunner.reporting.events`) -- one method,
  `on_event(envelope)`, receiving a versioned, JSON-serializable
  `EventEnvelope` (`schemaVersion`, `type`, `timestamp`, `payload`) for
  every lifecycle point, including `worker_spawned`/`worker_terminated`
  which `ConsoleReporter` doesn't expose. This is the surface future
  hooks/plugins/IDE integrations build on -- ignore any `type` you don't
  recognize, since that's what keeps adding new event types additive
  rather than breaking.

```python
from ctrlrunner.reporting.events import EventSubscriber

class MySubscriber(EventSubscriber):
    def on_event(self, event):
        if event.type == "test_end":
            print(event.payload["id"], event.payload["outcome"])

orch = Orchestrator(root, num_workers, timeout, event_subscribers=[MySubscriber()])
```
