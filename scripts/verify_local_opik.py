"""Send synthetic traces only, then verify persistence through Opik's read API."""
import argparse
import json
import tempfile
import time
from pathlib import Path

from digital_twin_sensor import observability as obs
from digital_twin_sensor.opik_exporter import _sdk, _wire, export_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:5173/api")
    parser.add_argument("--project", default="digital-twin-sensor")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="dts-opik-smoke-") as folder:
        db = Path(folder) / "synthetic.sqlite"
        obs.configure(db, mode="opik", endpoint=args.endpoint, project=args.project)
        with obs.operation(db, "observability.test"):
            with obs.operation(db, "context.pack") as span:
                span.outcome("blocked")
                span.counts(deny=1)
        result = export_once(db)
        if result["status"] != "accepted":
            raise RuntimeError("Synthetic export failed: " + result.get("error", result["status"]))
        OpikApi, TraceWrite, SpanWrite, httpx, uuid6 = _sdk()
        root, _ = _wire(obs.status(db)["recent"][0], obs.settings(db), TraceWrite, SpanWrite, uuid6)
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as transport:
            client = OpikApi(base_url=args.endpoint, workspace_name="default", httpx_client=transport)
            trace = None
            for _ in range(15):
                try:
                    trace = client.traces.get_trace_by_id(root.id, request_options={"max_retries": 0})
                    break
                except Exception:
                    time.sleep(1)
            if trace is None:
                raise RuntimeError("Synthetic trace was accepted but could not be read back")
            assert trace.name == "observability.test" and trace.input is None and trace.output is None
            # Use the server's supported shortest retention on this dedicated project.
            rule = client.retention_rules.create_retention_rule(retention="short_14d", project_id=trace.project_id,
                                                               apply_to_past=False, request_options={"max_retries": 0})
            print(json.dumps({"persisted": True, "trace_id": trace.id, "project_id": trace.project_id,
                              "project": args.project, "retention": rule.retention}))


if __name__ == "__main__":
    main()
