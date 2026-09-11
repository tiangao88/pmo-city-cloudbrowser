from types import SimpleNamespace
import pytest
from cloudbrowser.service_runtime import run_service


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("serve_fails", [False, True])
def test_runtime_worker_lifecycle(monkeypatch, tmp_path, enabled, serve_fails):
    for key in ("CB_EXPERIMENTAL_VIEWER_CONTROL", "CB_VIEWER_CONTROL_URL", "CB_VIEWER_CONTROL_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CB_INSTANCE_ID", "synthetic-runtime")
    monkeypatch.setenv("CB_RELEASE_VERSION", "experiment")
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", "synthetic-router-secret")
    monkeypatch.setenv("CB_SNAPSHOT_PATH", str(tmp_path / "tabs.json"))
    if enabled:
        monkeypatch.setenv("CB_EXPERIMENTAL_VIEWER_CONTROL", "1")
        monkeypatch.setenv("CB_VIEWER_CONTROL_URL", "http://127.0.0.1:12345")
        monkeypatch.setenv("CB_VIEWER_CONTROL_SECRET", "x" * 32)
    events, captured = [], {}
    class Worker:
        def __init__(self, callback):
            captured["callback"] = callback
        def start(self):
            events.append("start")
        def stop(self):
            events.append("stop")
    def serve():
        events.append("serve")
        if serve_fails:
            raise RuntimeError("synthetic server failure")
    server = SimpleNamespace(serve_forever=serve, server_close=lambda: events.append("close"))
    def control(supervisor, *args, **kwargs):
        captured["supervisor"] = supervisor
        return object()
    monkeypatch.setattr("cloudbrowser.viewer.renewal.ViewerRenewalWorker", Worker)
    monkeypatch.setattr("cloudbrowser.router.control_api.ControlApi", control)
    monkeypatch.setattr("cloudbrowser.router.control_api.create_control_server", lambda *a, **kw: server)
    if serve_fails:
        with pytest.raises(RuntimeError, match="synthetic server failure"):
            run_service("slot-supervisor")
    else:
        run_service("slot-supervisor")
    assert events == (["start", "serve", "close", "stop"] if enabled else ["serve", "close"])
    assert (captured["supervisor"]._viewer_renew is not None) == enabled
    if enabled:
        assert captured["callback"].__self__ is captured["supervisor"]
