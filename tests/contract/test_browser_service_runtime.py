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


def test_router_wires_supervisor_urls_and_identity_link_env(monkeypatch):
    captured = {}

    class FakeNamespace:
        def __init__(self, instance_id):
            captured["instance_id"] = instance_id

    class FakeStore:
        def __init__(self, path, *, slots, clock, **kwargs):
            captured["state_path"] = str(path)
            captured["slot_ids"] = sorted(slot.slot_id for slot in slots)
            captured["supervisor_urls"] = sorted(slot.supervisor_url for slot in slots)
            captured["clock"] = clock

    class FakeResolver:
        pass

    class FakeApi:
        def __init__(self, *, session_store, supervisor_client, identity_client, **kwargs):
            captured["api"] = (session_store, supervisor_client, identity_client)

    class FakeServer:
        def serve_forever(self):
            captured["served"] = True

        def server_close(self):
            captured["closed"] = True

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8080")
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", "router-test-secret-0123456789")
    monkeypatch.setenv("CB_SLOT_SUPERVISOR_URLS", "slot-1=http://slot-1:8081,slot-2=http://slot-2:8081")
    monkeypatch.setenv("CB_EDGE_AUTH", "traefik-forwardauth")
    monkeypatch.setenv("CB_IDENTITY_LINK_BASE_URL", "http://identity-link:8091")
    monkeypatch.setenv("CB_IDENTITY_LINK_SHARED_SECRET", "identity-link-router-secret-0123456789ab")
    monkeypatch.setenv("CB_OIDC_ISSUER", "https://auth.example.test")
    monkeypatch.setenv("CB_TINYAUTH_REALM", "tinyauth.example.test")
    # CB_ROUTER_STATE stays unset: the runtime must persist RouterSessionStore
    # under the compose-mounted router-state volume by default
    # (/data/state/router-state.json), like other components default their
    # state paths.
    monkeypatch.delenv("CB_ROUTER_STATE", raising=False)

    import cloudbrowser.router.router_api as router_api

    monkeypatch.setattr("cloudbrowser.router.sessions.RouterSessionStore", FakeStore)
    monkeypatch.setattr(
        "cloudbrowser.identity_links.build_identity_link_client", lambda: FakeResolver()
    )
    monkeypatch.setattr("cloudbrowser.router.router_api.RouterApi", FakeApi)
    monkeypatch.setattr(
        "cloudbrowser.router.router_api.create_router_server",
        lambda api, *, address: FakeServer(),
    )
    # RED: until run_service has a real router branch it falls through to the
    # bare health server; make that fallback fail loudly instead of hanging.
    monkeypatch.setattr(
        service_runtime,
        "serve_health",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("router fell back to health")),
    )

    service_runtime.run_service("router")

    assert captured["instance_id"] == "test-instance"
    assert captured["slot_ids"] == ["slot-1", "slot-2"]
    assert captured["supervisor_urls"] == ["http://slot-1:8081", "http://slot-2:8081"]
    assert captured["state_path"] == "/data/state/router-state.json"
    session_store, supervisor_client, identity_client = captured["api"]
    assert isinstance(supervisor_client, object)
    assert isinstance(identity_client, FakeResolver)
    assert session_store is not None
    assert captured["served"] is True
    assert captured["closed"] is True
    assert callable(captured["clock"])


def test_router_never_falls_back_to_health(monkeypatch):
    class FakeNamespace:
        def __init__(self, instance_id):
            pass

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8080")

    def _health_fallback(*args, **kwargs):
        raise AssertionError("router runtime fell back to the bare health server")

    monkeypatch.setattr(service_runtime, "serve_health", _health_fallback)

    try:
        service_runtime.run_service("router")
    except SystemExit:
        pass
    else:
        raise AssertionError("router runtime must not be a bare health server")
