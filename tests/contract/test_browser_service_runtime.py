from cloudbrowser import service_runtime


def test_slot_supervisor_uses_browser_sidecar_port_by_default(monkeypatch):
    captured = {}

    class FakeNamespace:
        def __init__(self, instance_id):
            captured["instance_id"] = instance_id

    class FakeTransport:
        def __init__(self, client, *, expected_owner, expected_generation):
            captured["browser_base_url"] = client._base_url
            captured["expected_owner"] = expected_owner
            captured["expected_generation"] = expected_generation

    class FakeLifecycle:
        def __init__(self, *args, **kwargs):
            pass

    class FakeSupervisor:
        def __init__(self, *args, **kwargs):
            pass

    class FakeControlApi:
        def __init__(self, *args, **kwargs):
            pass

    class FakeServer:
        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8081")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-1")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "owner@example.test")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-1")
    monkeypatch.setenv("CB_BINDING_GENERATION", "generation-1")
    monkeypatch.delenv("CB_BROWSER_API_URL", raising=False)

    import cloudbrowser.browser_slots.http_transport as http_transport
    import cloudbrowser.router.control_api as control_api

    monkeypatch.setattr(http_transport, "HttpBrowserTransport", FakeTransport)
    monkeypatch.setattr(control_api, "ControlApi", FakeControlApi)
    monkeypatch.setattr(control_api, "create_control_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr("cloudbrowser.browser_slots.OwnerBoundLifecycle", FakeLifecycle)
    monkeypatch.setattr("cloudbrowser.browser_slots.SlotSupervisor", FakeSupervisor)

    service_runtime.run_service("slot-supervisor")

    assert captured["browser_base_url"] == "http://browser:9230"
    assert captured["expected_owner"] == "owner@example.test"
    assert captured["expected_generation"] == "generation-1"
