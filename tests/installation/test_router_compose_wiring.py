"""Compose/runtime contract for the owner-bound router control plane.

The router service runtime (``cloudbrowser.service_runtime.run_service("router")``)
authenticates every session request through the shared PMO identity-link
service, dispatches slot lifecycle commands to private slot supervisors over
``CB_SLOT_SUPERVISOR_URLS``, and is itself authenticated downstream with
``CB_ROUTER_SHARED_SECRET`` (same trusted-secret boundary pattern as
agent-control/downloads). Both compose variants must therefore wire the router
exactly like the viewer/cloudfiles services (edge switch + identity-link client
configuration), require the control-plane secrets, order the router after
``identity-link``, and keep the durable ``router-state`` volume mounted at the
runtime's state path.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "coolify"


def _router_block(filename: str) -> str:
    compose = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
    return compose.split("  router:", 1)[1].split("  slot-supervisor:", 1)[0]


def test_compose_router_carries_identity_link_env_and_edge_switch() -> None:
    # The router control plane authenticates every session request through
    # the shared identity-link resolver; the edge switch and client
    # configuration must be present in both the source-build and the
    # deployed image-based variants.
    # Coolify variant wires the shared secret via a magic env and carries
    # deploy-safe defaults for the edge/identity configuration.
    for filename, markers in (
        (
            "compose.yaml",
            (
                "CB_IDENTITY_LINK_SHARED_SECRET: ${CB_IDENTITY_LINK_SHARED_SECRET",
                "CB_OIDC_ISSUER: ${CB_OIDC_ISSUER",
                "CB_TINYAUTH_REALM: ${CB_TINYAUTH_REALM",
            ),
        ),
        (
            "compose.coolify.yaml",
            (
                "CB_IDENTITY_LINK_SHARED_SECRET: ${SERVICE_PASSWORD_64_IDLINKSECRET}",
                "CB_OIDC_ISSUER: ${CB_OIDC_ISSUER:-https://auth.aikumi.app/application/o/pmoc-sso/}",
                "CB_TINYAUTH_REALM: ${CB_TINYAUTH_REALM:-tinyauth-pmo}",
            ),
        ),
    ):
        block = _router_block(filename)
        assert "CB_IDENTITY_LINK_BASE_URL: http://identity-link:8091" in block
        for marker in markers:
            assert marker in block, f"{filename}: missing {marker}"
        assert "CB_EDGE_AUTH" in block


def test_compose_router_requires_control_plane_secrets_and_supervisor_map() -> None:
    # Fail-closed control plane: no supervisor map and no downstream trusted
    # secret means the router must refuse to start in every variant (same
    # `${VAR:?...}` contract as agent-control/downloads).
    for filename, secret_marker, supervisor_marker in (
        (
            "compose.yaml",
            "CB_ROUTER_SHARED_SECRET: ${CB_ROUTER_SHARED_SECRET:?CB_ROUTER_SHARED_SECRET is required}",
            "CB_SLOT_SUPERVISOR_URLS: ${CB_SLOT_SUPERVISOR_URLS:?CB_SLOT_SUPERVISOR_URLS is required}",
        ),
        (
            "compose.coolify.yaml",
            "CB_ROUTER_SHARED_SECRET: ${SERVICE_PASSWORD_64_ROUTERSECRET}",
            "CB_SLOT_SUPERVISOR_URLS: ${CB_SLOT_SUPERVISOR_URLS:-slot-1=http://slot-supervisor:8081}",
        ),
    ):
        block = _router_block(filename)
        assert secret_marker in block, f"{filename}: missing secret marker"
        assert supervisor_marker in block, f"{filename}: missing supervisor map"


def test_compose_slot_supervisor_receives_router_trusted_secret() -> None:
    for filename, secret_marker in (
        ("compose.yaml", "CB_ROUTER_SHARED_SECRET: ${CB_ROUTER_SHARED_SECRET:?CB_ROUTER_SHARED_SECRET is required}"),
        ("compose.coolify.yaml", "CB_ROUTER_SHARED_SECRET: ${SERVICE_PASSWORD_64_ROUTERSECRET}"),
    ):
        block = (COMPOSE_DIR / filename).read_text(encoding="utf-8").split(
            "  slot-supervisor:", 1
        )[1].split("  browser:", 1)[0]
        assert secret_marker in block


def test_compose_router_waits_for_identity_link_and_keeps_state_volume() -> None:
    # Depends-on mirrors the cloudfiles ordering (identity-link must be
    # healthy before the resolver client is used) and the state volume stays
    # mounted at /data/state, where RouterSessionStore persists its JSON.
    for filename in ("compose.yaml", "compose.coolify.yaml"):
        block = _router_block(filename)
        assert "identity-link:" in block
        assert "condition: service_healthy" in block
        assert "- router-state:/data/state" in block


def test_router_edge_and_identity_vars_match_deployed_contract() -> None:
    # Behind the authenticated edge the deployed router must refuse to start
    # without the edge mode and identity-link secrets (same `:?` contract as
    # the deployed viewer/cloudfiles); the local build variant stays
    # edge-optional so local/CI runs keep the health-only posture.
    deployed = _router_block("compose.coolify.yaml")
    assert "CB_EDGE_AUTH: ${CB_EDGE_AUTH:-traefik-forwardauth}" in deployed
    assert "CB_IDENTITY_LINK_SHARED_SECRET: ${SERVICE_PASSWORD_64_IDLINKSECRET}" in deployed
    assert "CB_OIDC_ISSUER: ${CB_OIDC_ISSUER:-https://auth.aikumi.app/application/o/pmoc-sso/}" in deployed
    assert "CB_TINYAUTH_REALM: ${CB_TINYAUTH_REALM:-tinyauth-pmo}" in deployed

    local = _router_block("compose.yaml")
    assert "CB_EDGE_AUTH: ${CB_EDGE_AUTH:-}" in local


def test_compose_router_is_not_a_public_host() -> None:
    # Public hosts are Coolify Domains entries; the router must not gain
    # host-published ports or compose-authored Traefik routers / TinyAuth
    # app keys (env VALUES like the edge-auth mode are config, not routing).
    for filename in ("compose.yaml", "compose.coolify.yaml"):
        block = _router_block(filename)
        assert "ports:" not in block
        assert "traefik.http" not in block
        assert "tinyauth.apps" not in block



def test_compose_router_requires_agent_control_forwarding_env() -> None:
    # §3.1: the router relays allowlisted page-actions to agent-control over
    # CB_AGENT_CONTROL_URLS with its own trusted secret. Both compose variants
    # must require both vars so the deployed router boots fail-closed with
    # forwarding configured (and the runtime refuses short secrets).
    for filename, urls_marker, secret_marker in (
        (
            "compose.yaml",
            "CB_AGENT_CONTROL_URLS: ${CB_AGENT_CONTROL_URLS:?CB_AGENT_CONTROL_URLS is required}",
            "CB_AGENT_CONTROL_SHARED_SECRET: "
            "${CB_AGENT_CONTROL_SHARED_SECRET:?CB_AGENT_CONTROL_SHARED_SECRET is required}",
        ),
        (
            "compose.coolify.yaml",
            "CB_AGENT_CONTROL_URLS: ${CB_AGENT_CONTROL_URLS:-slot-1=http://agent-control:8090}",
            "CB_AGENT_CONTROL_SHARED_SECRET: ${SERVICE_PASSWORD_64_AGENTCTRLSECRET}",
        ),
    ):
        block = _router_block(filename)
        assert urls_marker in block, f"{filename}: missing urls marker"
        assert secret_marker in block, f"{filename}: missing secret marker"
