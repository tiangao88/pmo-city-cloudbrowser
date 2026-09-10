"""Validate the digest-pinned installable release bundle."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    "router",
    "slot-supervisor",
    "browser",
    "viewer",
    "agent-control",
    "downloads",
    "credential-broker",
    "cloudfiles",
    "identity-link",
)
MANIFEST = ROOT / "deploy" / "coolify" / "releases" / "v0.2.0-dev1" / "release-manifest.yaml"
COMPOSE = ROOT / "deploy" / "coolify" / "compose.coolify.yaml"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def fail(message: str) -> None:
    print(f"installation validation: FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    if "services: {}" in compose:
        fail("Compose bundle is empty")
    # The Coolify bundle supplies service-to-service secrets through magic envs,
    # while the custody KEK and Vault endpoint remain explicit operator inputs.
    for marker in (
        "name: ${CB_INSTANCE_ID:-cloudbrowser2-dev-v01}-network",
        "name: ${CB_INSTANCE_ID:-cloudbrowser2-dev-v01}-router-state",
        "CB_VIEWER_TOKEN_SECRET: ${SERVICE_PASSWORD_64_VIEWERSECRET:?SERVICE_PASSWORD_64_VIEWERSECRET is required}",
        "CB_ROUTER_SHARED_SECRET: ${SERVICE_PASSWORD_64_ROUTERSECRET:?SERVICE_PASSWORD_64_ROUTERSECRET is required}",
        "CB_AGENT_CONTROL_SHARED_SECRET: ${SERVICE_PASSWORD_64_AGENTCTRLSECRET:?SERVICE_PASSWORD_64_AGENTCTRLSECRET is required}",
        "CB_IDENTITY_LINK_SHARED_SECRET: ${SERVICE_PASSWORD_64_IDLINKSECRET:?SERVICE_PASSWORD_64_IDLINKSECRET is required}",
        "CB_DOWNLOADS_SHARED_SECRET: ${SERVICE_PASSWORD_64_DLSECRET:?SERVICE_PASSWORD_64_DLSECRET is required}",
        "CB_DOWNLOADS_INGEST_SECRET: ${SERVICE_PASSWORD_64_INGESTSECRET:?SERVICE_PASSWORD_64_INGESTSECRET is required}",
        "CB_CREDENTIAL_BROKER_TIMEOUT_S: ${CB_CREDENTIAL_BROKER_TIMEOUT_S:-25}",
        "CB_CREDENTIAL_CAPABILITY_TTL_S: ${CB_CREDENTIAL_CAPABILITY_TTL_S:-26}",
        "CB_BROKER_SSO_STAGE_TIMEOUT_S: ${CB_BROKER_SSO_STAGE_TIMEOUT_S:-24}",
    ):
        if marker not in compose:
            fail(f"missing installation marker: {marker}")
    if "legacy/" in compose or "scripts:/app" in compose:
        fail("Compose bundle imports legacy runtime paths")
    if compose.count("healthcheck:") < len(SERVICES):
        fail("every service must define a healthcheck")
    for service in SERVICES:
        entrypoint = ROOT / "services" / service / "entrypoint.py"
        dockerfile = ROOT / "services" / service / "Dockerfile"
        if not entrypoint.is_file() or not dockerfile.is_file():
            fail(f"missing image inputs for {service}")
        docker_text = dockerfile.read_text(encoding="utf-8")
        for marker in (
            "COPY src/ /app/src/",
            f"COPY services/{service}/entrypoint.py",
            "HEALTHCHECK",
        ):
            if marker not in docker_text:
                fail(f"{service} Dockerfile missing {marker}")
        if not ("FROM python:3.12-slim" in docker_text or "FROM debian:bookworm-slim" in docker_text):
            fail(f"{service} Dockerfile missing supported base image")

    manifest = MANIFEST.read_text(encoding="utf-8")
    for marker in (
        "apiVersion: cloudbrowser.pmo.city/v1",
        "kind: CloudBrowserRelease",
        "productVersion: 0.2.0-dev1",
        "specificationBaseline: v0.2.0",
        "qualification:",
        "rollbackSupported: true",
        "status: pre-build-not-installable",
        "installable: false",
        "sourceState: pending-build",
        "imageState: stale-pre-change",
    ):
        if marker not in manifest:
            fail(f"release manifest missing {marker}")
    prior_run_match = re.search(
        r"^    run: (https://github\.com/[^\s]+/actions/runs/[0-9]+)$",
        manifest,
        re.MULTILINE,
    )
    prior_commit_match = re.search(
        r"^    commit: ([0-9a-f]{40})$", manifest, re.MULTILINE
    )
    if not prior_run_match:
        fail("release manifest is missing the prior qualification run")
    if not prior_commit_match:
        fail("release manifest is missing the prior qualification commit")
    if "QUALIFICATION_RUN_REQUIRED" in manifest or "QUALIFICATION_COMMIT_REQUIRED" in manifest:
        fail("release manifest contains provenance placeholders")
    for component in (
        "router",
        "slotSupervisor",
        "browser",
        "viewer",
        "agentControl",
        "downloads",
        "credentialBroker",
        "cloudfiles",
    ):
        match = re.search(rf"^    {component}: (sha256:\S+)$", manifest, re.MULTILINE)
        if not match or not DIGEST.fullmatch(match.group(1)):
            fail(f"{component} does not have a valid immutable digest")
    identity_match = re.search(r"^    identityLink: (sha256:\S+)$", manifest, re.MULTILINE)
    if not identity_match or not DIGEST.fullmatch(identity_match.group(1)):
        fail("identityLink does not have a valid immutable digest")
    print("installation validation: PASS")


if __name__ == "__main__":
    main()
