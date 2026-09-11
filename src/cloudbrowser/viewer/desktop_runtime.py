"""Unqualified, opt-in single-slot desktop candidate. Never a default runtime."""
import os
import signal
import threading
import time
from urllib.parse import urlsplit

from cloudbrowser.browser_service import build_browser_service
from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.identity_links import build_identity_link_client
from . import AuthenticatedViewer, ViewerSessionStore, create_viewer_server
from .display import DesktopProcess
from .fence_control import create_fence_server
from .interaction import InteractionGate
from .session_surface import RouterHttpClient, ViewerSessionSurface
from .slot_authority import SlotViewerAuthority


def validate_environment(env):
    if env.get("CB_EXPERIMENTAL_DESKTOP") != "1":
        raise ValueError("desktop candidate requires explicit opt-in")
    if env.get("CB_EDGE_AUTH") != "traefik-forwardauth":
        raise ValueError("desktop candidate requires an authenticated sanitizing edge")
    origin = env.get("CB_VIEWER_PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("desktop requires an exact HTTPS public origin")
    for key in ("CB_VIEWER_TOKEN_SECRET", "CB_VIEWER_CONTROL_SECRET"):
        if len(env.get(key, "")) < 32:
            raise ValueError(f"{key} must contain at least 32 characters")
    if env["CB_VIEWER_TOKEN_SECRET"] == env["CB_VIEWER_CONTROL_SECRET"]:
        raise ValueError("viewer and control secrets must be distinct")
    if not env.get("CB_ROUTER_BASE_URL"):
        raise ValueError("router URL required")
    if env.get("CB_BROWSER_AUTOSTART") != "0" or "--headless" in env.get("CB_CHROME_EXTRA_ARGS", ""):
        raise ValueError("desktop must boot stopped and run headed")
    # Browser-side exclusion alone does not fence upstream credential retrieval.
    # Keep this candidate credential-free until whole-job broker fencing exists.
    if env.get("CB_BROKER_SUBMIT_SECRET") or env.get("CB_BROKER_SSO_IDP_ORIGINS"):
        raise ValueError("credential broker is not qualified for desktop candidate")
    return origin


def main():
    origin = validate_environment(os.environ)
    from .desktop_transport import create_desktop_transport

    identity = build_identity_link_client()
    from cloudbrowser.broker_jobs import BrokerJobs
    jobs_directory = os.environ.get("CB_EXPERIMENTAL_BROKER_JOBS_DIR")
    jobs = BrokerJobs(jobs_directory) if jobs_directory else None
    if jobs is not None:
        jobs.claim_authority()
    gate = InteractionGate(broker_jobs=jobs)
    process, browser_server, stop, registry = build_browser_service(
        process_wrapper=lambda browser: DesktopProcess(browser, gate), interaction_gate=gate)
    registry.attach_stop_event(stop)
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=time.time),
        token_secret=os.environ["CB_VIEWER_TOKEN_SECRET"].encode(), identity_client=identity)
    authority = SlotViewerAuthority(viewer=viewer, identity_client=identity,
        readiness=lambda: BrowserReadiness(process.config.owner, process.config.generation,
            bool(process.readiness())), stream_endpoint="/websockify",
        interaction_gate=gate, set_input=process.set_input)
    process.fence = lambda: authority.fence(BrowserBinding(process.config.profile_id,
        process.config.owner, process.config.browser_id, process.config.generation))
    servers = [browser_server]
    threads = []
    try:
        servers.append(create_viewer_server(viewer, address=("127.0.0.1", 6081),
            allow_edge_identity=True, stream_authority=authority, public_origin=origin,
            credential_login_enabled=False,
            session_surface=ViewerSessionSurface(identity_client=identity,
                router_api=RouterHttpClient(base_url=os.environ["CB_ROUTER_BASE_URL"])) ))
        servers.append(create_fence_server(authority,
            shared_secret=os.environ["CB_VIEWER_CONTROL_SECRET"],
            address=("0.0.0.0", 6083), reset_display=lambda: process.set_input(False)))
        servers.append(create_desktop_transport(authority, public_origin=origin))
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        # Do not invoke BrowserProcess.watch: its self-recovery would bypass X
        # reset. Supervisor lifecycle must own recovery of the entire desktop.
        while not stop.wait(0.5):
            if not all(thread.is_alive() for thread in threads):
                raise RuntimeError("desktop service stopped")
            with gate.lock:
                if gate.mode in ("agent", "human") and not process.readiness():
                    process.stop()
    finally:
        stop.set()
        try:
            process.stop()
        finally:
            for server, thread in reversed(list(zip(servers, threads))):
                if thread.is_alive():
                    server.shutdown()
            for server in reversed(servers):
                server.server_close()
            registry.close()
            if jobs is not None:
                jobs.close()


if __name__ == "__main__":
    main()
