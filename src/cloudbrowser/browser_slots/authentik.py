"""Exact Authentik browser capability over local page actions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

from ..security.policy import canonical_identity
from .page_actions import BrokerPageActions
from .transport import BrowserUnavailable

_UID = "ak-flow-executor ak-stage-identification input[name=uidField]"
_PASSWORD = "ak-flow-executor ak-stage-identification ak-flow-input-password input[name=password]"
_SUBMIT = "ak-flow-executor ak-stage-identification button[type=submit]"
_REJECTED = "ak-flow-executor ak-stage-identification [role=alert]"
_MFA = "ak-flow-executor ak-stage-authenticator-validate"
_MAX_URL_BYTES = 2048
_MAX_IDENTITY_BYTES = 512
_MAX_POLL_INTERVAL_S = 0.25
_MAX_STAGE_TIMEOUT_S = 30.0
_IDENTITY_CLAIM_PREFIX = "attribute:"


class AuthentikActions(BrokerPageActions, Protocol):
    def broker_authentik_mfa(self, target_id: str, *, selector: str) -> dict[str, object]: ...

    def broker_navigate(self, target_id: str, url: str) -> None: ...

    def broker_authentik_identification(
        self,
        target_id: str,
        *,
        expected_origins: tuple[str, ...],
        username_selector: str,
        password_selector: str,
        submit_selector: str,
        rejected_selector: str,
        username: str,
        password: str,
    ) -> dict[str, str]: ...

    def broker_authentik_rejection(
        self,
        target_id: str,
        *,
        expected_origins: tuple[str, ...],
        rejected_selector: str,
    ) -> dict[str, str]: ...

    def broker_authentik_proof(
        self,
        target_id: str,
        *,
        application_origins: tuple[str, ...],
        success_paths: tuple[str, ...],
        selector: str,
        claim: str,
    ) -> dict[str, str | None]: ...


@dataclass
class AuthentikCapability:
    actions: AuthentikActions
    idp_origins: tuple[str, ...]
    application_origins: tuple[str, ...]
    success_paths: tuple[str, ...]
    identity_selector: str | None = None
    identity_claim: str | None = None
    stage_timeout_s: float = 30.0
    poll_interval_s: float = 0.1
    deadline: "BrokerDeadline | None" = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.stage_timeout_s, bool)
            or not isinstance(self.stage_timeout_s, (int, float))
            or self.stage_timeout_s <= 0
            or self.stage_timeout_s > _MAX_STAGE_TIMEOUT_S
        ):
            raise ValueError("Authentik stage timeout is invalid")
        if not self.idp_origins or any(_origin(origin) != origin for origin in self.idp_origins):
            raise ValueError("Authentik IdP origins are invalid")
        if any(_origin(origin) != origin for origin in self.application_origins):
            raise ValueError("Authentik application origins are invalid")
        if any(
            not path.startswith("/") or "?" in path or "#" in path
            for path in self.success_paths
        ):
            raise ValueError("Authentik success paths are invalid")
        if self.poll_interval_s <= 0 or self.poll_interval_s > _MAX_POLL_INTERVAL_S:
            raise ValueError("Authentik poll interval is invalid")
        if (self.identity_selector is None) != (self.identity_claim is None):
            raise ValueError("Authentik identity proof rule is incomplete")
        if self.identity_selector is not None:
            from .page_actions import _validate_selector

            _validate_selector(self.identity_selector)
            claim = self.identity_claim or ""
            if not claim.startswith(_IDENTITY_CLAIM_PREFIX):
                raise ValueError("Authentik identity claim is invalid")
            attribute = claim.removeprefix(_IDENTITY_CLAIM_PREFIX)
            if (
                not attribute
                or len(attribute.encode("utf-8")) > 128
                or not attribute.replace("-", "").replace("_", "").isalnum()
                or attribute.lower().startswith("on")
            ):
                raise ValueError("Authentik identity claim is invalid")

    def _check_deadline(self, deadline: "BrokerDeadline | None" = None) -> float | None:
        effective = deadline if deadline is not None else self.deadline
        return effective.check() if effective is not None else None

    def _stage_end(self) -> float:
        remaining = self._check_deadline()
        return time.monotonic() + min(
            self.stage_timeout_s,
            remaining if remaining is not None else self.stage_timeout_s,
        )

    def _sleep_poll(self, stage_end: float) -> None:
        remaining = stage_end - time.monotonic()
        shared_remaining = self._check_deadline()
        if shared_remaining is not None:
            remaining = min(remaining, shared_remaining)
        if remaining > 0:
            time.sleep(min(self.poll_interval_s, remaining))

    def _info(self, target_id: str, selector: str | None = None) -> dict[str, object]:
        self._check_deadline()
        value = self.actions.broker_page_info(target_id, selector)
        if not isinstance(value, dict):
            raise BrowserUnavailable("invalid Authentik page state")
        return dict(value)

    def _url(self, target_id: str) -> str:
        raw = self._info(target_id)
        url = raw.get("url")
        if not isinstance(url, str) or not url or len(url.encode("utf-8")) > _MAX_URL_BYTES:
            raise BrowserUnavailable("invalid Authentik page URL")
        return _state_url(url)

    def state(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | None]:
        previous_deadline = self.deadline
        if deadline is not None:
            self.deadline = deadline
        try:
            self._check_deadline()
            url = self._url(target_id)
            origin = _origin(url)
            parsed = urlsplit(url)
            if origin in self.application_origins and parsed.path in self.success_paths:
                return {"stage": "application", "modality": None, "url": url}
            if origin not in self.idp_origins:
                return {"stage": "unknown", "modality": None, "url": url}
            result: object = None
            callback = getattr(self.actions, "broker_authentik_mfa", None)
            if callable(callback):
                try:
                    result = callback(target_id, selector=_MFA)
                except (BrowserUnavailable, AssertionError, IndexError):
                    result = None
            if isinstance(result, dict) and result.get("found") is True:
                device_class = result.get("device_class")
                modality = "totp" if device_class == "totp" else "unknown"
                return {"stage": "mfa", "modality": modality, "url": url}
            identification = self._info(target_id, _UID)
            if identification.get("found") is True:
                return {"stage": "identification", "modality": None, "url": url}
            return {"stage": "unknown", "modality": None, "url": url}
        finally:
            self.deadline = previous_deadline

    def _mfa_metadata(self, target_id: str) -> dict[str, object]:
        probe = getattr(self.actions, "broker_authentik_mfa", None)
        if callable(probe):
            try:
                result = probe(target_id, selector=_MFA)
            except (BrowserUnavailable, AssertionError, IndexError):
                result = None
            if isinstance(result, dict) and result.get("found") is True:
                return dict(result)
        raw = self._info(target_id, _MFA)
        return {"found": bool(raw.get("found") is True), "device_class": None}

    def begin(
        self,
        *,
        target_id: str,
        entry_url: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None:
        previous_deadline = self.deadline
        if deadline is not None:
            self.deadline = deadline
        try:
            self._check_deadline()
            if _origin(entry_url) not in self.idp_origins:
                raise BrowserUnavailable("undeclared Authentik entry origin")
            self.actions.broker_navigate(target_id, entry_url)
        finally:
            self.deadline = previous_deadline

    def identification(
        self,
        *,
        target_id: str,
        username: str,
        password: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str]:
        previous_deadline = self.deadline
        if deadline is not None:
            self.deadline = deadline
        try:
            return self._identification(target_id=target_id, username=username, password=password)
        finally:
            self.deadline = previous_deadline

    def _identification(self, *, target_id: str, username: str, password: str) -> dict[str, str]:
        _validate_credential(username, "username", 512)
        _validate_credential(password, "password", 4096)
        stage_end = self._stage_end()
        submitted = False
        while time.monotonic() < stage_end:
            self._check_deadline()
            result = self.actions.broker_authentik_identification(
                target_id,
                expected_origins=self.idp_origins,
                username_selector=_UID,
                password_selector=_PASSWORD,
                submit_selector=_SUBMIT,
                rejected_selector=_REJECTED,
                username=username,
                password=password,
            )
            stage = result.get("stage") if isinstance(result, dict) else None
            if stage == "submitted":
                submitted = True
                break
            if stage == "rejected":
                return {"outcome": "rejected"}
            if stage == "invalid_target":
                raise BrowserUnavailable("invalid Authentik identification target")
            if stage != "not_ready":
                raise BrowserUnavailable("invalid Authentik identification state")
            self._sleep_poll(stage_end)
        if not submitted:
            raise BrowserUnavailable("Authentik identification stage timed out")

        while time.monotonic() < stage_end:
            self._check_deadline()
            rejection = self.actions.broker_authentik_rejection(
                target_id,
                expected_origins=self.idp_origins,
                rejected_selector=_REJECTED,
            )
            if not isinstance(rejection, dict) or rejection.get("state") not in {"clear", "rejected", "invalid_target"}:
                raise BrowserUnavailable("invalid Authentik rejection state")
            if rejection["state"] == "invalid_target":
                raise BrowserUnavailable("invalid Authentik rejection target")
            if rejection["state"] == "rejected":
                return {"outcome": "rejected"}
            after = self.state(target_id=target_id, deadline=self.deadline)
            if after["stage"] in {"mfa", "application"}:
                return {"outcome": "submitted"}
            self._sleep_poll(stage_end)
        raise BrowserUnavailable("Authentik identification transition timed out")

    def proof(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | None]:
        previous_deadline = self.deadline
        if deadline is not None:
            self.deadline = deadline
        try:
            self._check_deadline()
            if self.identity_selector is None or self.identity_claim is None:
                return {"account": None}
            proof = self.actions.broker_authentik_proof(
                target_id,
                application_origins=self.application_origins,
                success_paths=self.success_paths,
                selector=self.identity_selector,
                claim=self.identity_claim,
            )
            account = proof.get("account") if isinstance(proof, dict) else None
            if account is None:
                return {"account": None}
            if not isinstance(account, str) or not account or len(account.encode("utf-8")) > _MAX_IDENTITY_BYTES or any(ord(char) < 0x20 or ord(char) == 0x7F for char in account):
                raise BrowserUnavailable("invalid Authentik identity proof")
            if canonical_identity(account) is None:
                raise BrowserUnavailable("invalid Authentik identity proof")
            return {"account": account}
        finally:
            self.deadline = previous_deadline


def _validate_credential(value: str, label: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum or any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError(f"Authentik {label} is invalid")


def _state_url(url: str) -> str:
    parsed = urlsplit(url)
    origin = _origin(url)
    if origin is None:
        raise BrowserUnavailable("invalid Authentik page URL")
    return origin + (parsed.path or "/")


def _origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    return f"https://{parsed.netloc}"


__all__ = ["AuthentikActions", "AuthentikCapability"]
