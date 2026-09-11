import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_standalone_candidate_has_private_runtime_and_no_broker():
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI unavailable")
    env = {**os.environ, "CB_DESKTOP_PROJECT": "cb-synthetic-config-check",
        "CB_VIEWER_PUBLIC_ORIGIN": "https://desktop.example.test:18443",
        "CB_DESKTOP_HOST": "desktop.example.test", "CB_DESKTOP_ROUTER_HOST": "router.example.test",
        "CB_DESKTOP_EDGE_IMAGE": "traefik:v3.6", "CB_DESKTOP_TLS_CERT": "/tmp/cb-fixture-cert",
        "CB_DESKTOP_TLS_KEY": "/tmp/cb-fixture-key", "CB_DESKTOP_FORWARD_AUTH_URL": "https://auth.example.test/check",
        "CB_OIDC_ISSUER": "https://issuer.example.test", "CB_TINYAUTH_REALM": "synthetic"}
    for name in ("CB_ROUTER_SHARED_SECRET", "CB_AGENT_CONTROL_SHARED_SECRET", "CB_VIEWER_TOKEN_SECRET",
                 "CB_VIEWER_CONTROL_SECRET", "CB_IDENTITY_LINK_SHARED_SECRET"):
        env[name] = "synthetic-config-only-" + name
    result = subprocess.run(["docker", "compose", "-f", str(ROOT / "deploy/desktop/compose.candidate.yaml"),
        "config", "--format", "json"], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    services = config["services"]
    assert set(services) == {"edge", "router", "browser", "slot-supervisor", "agent-control", "identity-link"}
    assert all(not service.get("ports") for name, service in services.items() if name != "edge")
    assert services["edge"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["router"]["environment"]["CB_CREDENTIAL_BROKER_URL"] == ""
    assert services["router"]["environment"]["CB_CREDENTIAL_CAPABILITY_SECRET"] == ""
    assert services["browser"]["environment"]["CB_BROKER_SUBMIT_SECRET"] == ""
    assert services["slot-supervisor"]["environment"]["CB_VIEWER_CONTROL_URL"] == "http://browser:6083"
    assert services["agent-control"]["environment"]["CB_PRINCIPAL_ID"] == "principal-unassigned"
    assert services["agent-control"]["environment"]["CB_BROWSER_ID"] == "browser-slot-1"
    assert services["browser"]["environment"]["CB_ROUTER_BASE_URL"] == "http://router:8080"
    assert all(not any(key.startswith("CB_VAULT") for key in service.get("environment", {})) for service in services.values())
    edge = config["configs"]["edge"]["content"]
    assert "trustForwardHeader: false" in edge and "authResponseHeadersRegex: '(?i)^Remote-'" in edge
    assert edge.count("middlewares: [identity]") == 2
    assert "http://browser:8082" in edge and "http://router:8080" in edge
    assert "docker.sock" not in json.dumps(config)


def test_candidate_uses_supported_python_and_separate_transport_install():
    dockerfile = (ROOT / "services/desktop/Dockerfile").read_text()
    assert "FROM python:3.12-slim-bookworm" in dockerfile
    assert "python -m pip install --no-cache-dir websockify==0.10.0" in dockerfile
