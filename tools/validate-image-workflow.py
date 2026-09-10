"""Validate the image publication workflow's static qualification contract."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-images.yml"
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


def fail(message: str) -> None:
    print(f"image-workflow validation: FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "uses: astral-sh/setup-uv@v5",
        "uv sync --dev",
        "uv run make check",
        "needs: validate",
        "docker/setup-buildx-action@v3",
        "docker/login-action@v3",
        "docker/metadata-action@v5",
        "docker/build-push-action@v6",
        "provenance: true",
        "sbom: true",
        "docker pull",
        "docker image inspect",
        "docker buildx imagetools inspect",
        "State.Health.Status",
        "Config.User",
        "docker exec",
        "curl --fail",
        "actions/upload-artifact@v4",
        "GITHUB_STEP_SUMMARY",
    )
    for marker in required:
        if marker not in text:
            fail(f"missing workflow marker: {marker}")

    # The broker runtime no longer accepts the legacy request secret or
    # Vaultwarden login credentials. Keep its qualification-only custody
    # configuration scoped to the broker matrix service, while leaving the
    # common service arguments harmless for other matrix entries.
    if 'if [ "$SERVICE" = credential-broker ]; then' not in text:
        fail("credential-broker qualification env is not service-scoped")
    for marker in (
        "broker_args=()",
        "--mount type=tmpfs,destination=/data/state,tmpfs-mode=1777",
        '"${broker_args[@]}"',
        "--env CB_CREDENTIAL_CAPABILITY_SECRET=",
        "--env CB_CREDENTIAL_BROKER_AUDIENCE=",
        "--env CB_CREDENTIAL_NONCE_DB_PATH=/data/state/nonces.sqlite3",
        "--env CB_BROKER_IDEMPOTENCY_DB_PATH=/data/state/idempotency.sqlite3",
        "--env CB_BROKER_GRANT_DB_PATH=/data/state/grant-custody-v1.sqlite3",
        "--env CB_BROKER_SUBMIT_SECRET=",
        "--env CB_VAULT_BASE_URL=",
    ):
        if marker not in text:
            fail(f"missing credential-broker qualification marker: {marker}")
    grant_kek = re.search(
        r"--env CB_BROKER_GRANT_KEK_HEX=([0-9a-f]+)", text
    )
    if not grant_kek or not re.fullmatch(r"[0-9a-f]{64}", grant_kek.group(1)):
        fail("qualification grant KEK must be a 64-character hexadecimal dummy")
    capability_secret = re.search(
        r"--env CB_CREDENTIAL_CAPABILITY_SECRET=([^\s]+)", text
    )
    if not capability_secret or len(capability_secret.group(1).encode("utf-8")) < 16:
        fail("qualification capability secret must be at least 16 bytes")
    for marker in (
        "CB_BROKER_SHARED_SECRET",
        "CB_VAULT_EMAIL",
        "CB_VAULT_PASSWORD",
    ):
        if marker in text:
            fail(f"obsolete credential-broker env remains: {marker}")

    if text.count("dockerfile: services/") != len(SERVICES):
        fail("build matrix does not contain exactly one Dockerfile per service")
    for service in SERVICES:
        if f"name: {service}" not in text:
            fail(f"missing matrix service: {service}")
        if not (ROOT / "services" / service / "Dockerfile").is_file():
            fail(f"missing Dockerfile: {service}")
        if not (ROOT / "services" / service / "entrypoint.py").is_file():
            fail(f"missing entrypoint: {service}")
        if not (ROOT / "deploy" / "coolify" / "image-qualification" / f"{service}.md").is_file():
            fail(f"missing qualification template: {service}")

    manifest = (ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml").read_text(
        encoding="utf-8"
    )
    if "installable: false" not in manifest:
        fail("pre-build release must not be installable")
    if "status: pre-build-not-installable" not in manifest:
        fail("release manifest is missing pre-build status")
    for marker in ("sourceState: pending-build", "imageState: stale-pre-change"):
        if marker not in manifest:
            fail(f"release manifest is missing {marker}")
    if "identityLink" not in manifest:
        fail("release manifest lacks identityLink component")
    identity_link_match = re.search(
        r"^    identityLink: (sha256:\S+)$", manifest, re.MULTILINE
    )
    if not identity_link_match or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity_link_match.group(1)):
        fail("identityLink must have a published immutable digest")
    print("image-workflow validation: PASS")


if __name__ == "__main__":
    main()
