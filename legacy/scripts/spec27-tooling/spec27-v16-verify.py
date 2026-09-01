#!/usr/bin/env python3
"""Spec 27 S6 (v1.6.0) verification: SW EXT_VERSION + LRU eviction + toast
on slot-2, light state check on slot-1 and viewer.

Run: /opt/data/cdp-venv/bin/python /opt/data/spec27-v16-verify.py
Requires tunnels: slot-1 9231, slot-2 9232 (viewer via 10.0.37.9:9223).
"""
import asyncio, json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, "/opt/data/cdp-venv/lib/python3.13/site-packages")
import websockets

TARGETS = {"slot-1": ("127.0.0.1", 9231), "slot-2": ("127.0.0.1", 9232),
           "viewer": ("10.0.37.9", 9223)}
HOST, PORT = "127.0.0.1", 9232  # slot-2 for the functional test


def cdp_http(path, method="GET", data=None):
    url = f"http://{HOST}:{PORT}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            try:
                return json.load(r)
            except Exception:
                return r.read().decode()[:120]
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:200]}


async def eval_ws(ws_url, expr, await_promise=False):
    params = {"expression": expr, "returnByValue": True}
    if await_promise:
        params["awaitPromise"] = True
    async with websockets.connect(ws_url, max_size=2**22, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": params}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            if msg.get("id") == 1:
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    return {"error": res["exceptionDetails"].get("exception", {}).get("description", "")[:200]}
                return res.get("result", {}).get("value")


def tabs_now():
    return [t for t in cdp_http("/json/list") if t.get("type") == "page"]


async def sw_version(host, port):
    ts = json.load(urllib.request.urlopen(f"http://{host}:{port}/json/list", timeout=5))
    sws = [t for t in ts if t.get("type") == "service_worker" and "background.js" in t.get("url", "")]
    out = []
    for sw in sws:
        out.append({
            "manifest": await eval_ws(sw["webSocketDebuggerUrl"], "chrome.runtime.getManifest().version"),
            "extVersion": await eval_ws(sw["webSocketDebuggerUrl"], "EXT_VERSION"),
            "config": await eval_ws(sw["webSocketDebuggerUrl"], "JSON.stringify(CONFIG)"),
        })
    return out


async def eval_on_page(ws_url, expr):
    return await eval_ws(ws_url, expr)


async def click_plus_submit(page_ws, url):
    """Click ＋, fill the popover, submit; returns popover state + response."""
    base = "document.querySelector('div[style*=\"2147483647\"]').shadowRoot"
    await eval_on_page(page_ws, f"{base}.getElementById('plus').click()")
    await asyncio.sleep(0.3)
    await eval_on_page(page_ws, f"{base}.getElementById('urlpop-in').value = {json.dumps(url)}")
    await asyncio.sleep(0.1)
    await eval_on_page(page_ws, f"{base}.getElementById('urlpop-ok').click()")
    await asyncio.sleep(2.5)


async def main():
    print("== SW version check (all three) ==")
    for name, (h, p) in TARGETS.items():
        try:
            print(json.dumps({name: await sw_version(h, p)}, indent=1))
        except Exception as e:
            print(f"{name}: ERROR {e}")

    print("\n== LRU eviction test on slot-2 ==")
    # Baseline: exactly one pmo.city tab
    tabs = tabs_now()
    print("baseline:", [t["url"][:60] for t in tabs])
    assert len(tabs) >= 1, "no tabs on slot-2"

    # Bring to 3 real tabs: keep pmo.city, add two example.com tabs
    pmo = next(t for t in tabs_now() if "pmo.city" in t["url"])
    for u in ("http://example.com/alpha", "http://example.com/beta"):
        cdp_http("/json/new?" + urllib.parse.quote(u, safe=""), method="PUT")
        await asyncio.sleep(2.0)
    # Activate pmo.city so it is the most recently accessed
    cdp_http(f"/json/activate/{pmo['id']}")
    await asyncio.sleep(1.0)
    tabs = tabs_now()
    print("at limit (3):", [t["url"][:60] for t in tabs])
    # lastAccessed ordering
    for t in tabs:
        print("  lastAccessed:", t.get("lastAccessed"), t["url"][:50])
    assert len(tabs) == 3, f"expected 3 tabs, got {len(tabs)}"

    # Phase A: open gamma via the ＋ popover on the pmo.city page
    page_ws = pmo["webSocketDebuggerUrl"]
    # re-fetch: pmo may have a new target after activate? no — same target
    await click_plus_submit(page_ws, "example.com/gamma")
    tabs = tabs_now()
    urls = [t["url"][:50] for t in tabs]
    print("after gamma open:", urls)
    assert len(tabs) == 3, f"eviction failed: {len(tabs)} tabs (limit 3)"
    assert any("gamma" in u for u in urls), "gamma missing"
    assert not any("alpha" in u for u in urls), "alpha should have been evicted (LRU)"
    print("PASS: alpha evicted (LRU), gamma opened, still 3 tabs")

    # Toast check: the submitting tab (pmo.city) shows it from the OPEN_URL
    # response; broadcast also reaches other settled tabs.
    pmo_t = next(t for t in tabs_now() if "pmo.city" in t["url"])
    toast = await eval_on_page(pmo_t["webSocketDebuggerUrl"],
        "(() => { const h = document.querySelector('div[style*=\"2147483647\"]'); "
        "if (!h) return 'no bar'; const r = h.shadowRoot.getElementById('toast'); "
        "return r ? JSON.stringify({hidden: r.hidden, text: r.textContent}) : 'no toast'; })()")
    print("toast on pmo.city tab:", toast)
    assert "alpha" in str(toast).lower() or "Tab closed" in str(toast), "toast missing/empty"

    # Buttons never disabled at limit
    btns = await eval_on_page(pmo_t["webSocketDebuggerUrl"],
        "(() => { const h = document.querySelector('div[style*=\"2147483647\"]'); "
        "const s = h.shadowRoot; return JSON.stringify({home: s.getElementById('home').disabled, "
        "plus: s.getElementById('plus').disabled, "
        "homeTip: s.getElementById('home').title, plusTip: s.getElementById('plus').title}); })()")
    print("button state at limit:", btns)
    assert '"home":false' in btns and '"plus":false' in btns, "buttons should stay enabled"

    # Phase B: activate beta, open delta → expect pmo.city evicted (LRU),
    # beta survives (active), gamma survives (newer than pmo)
    beta = next(t for t in tabs_now() if "beta" in t["url"])
    cdp_http(f"/json/activate/{beta['id']}")
    await asyncio.sleep(1.0)
    await click_plus_submit(beta["webSocketDebuggerUrl"], "example.com/delta")
    tabs = tabs_now()
    urls = [t["url"][:50] for t in tabs]
    print("after delta open:", urls)
    assert len(tabs) == 3
    assert any("delta" in u for u in urls), "delta missing"
    assert not any("pmo.city" in u for u in urls), "pmo.city should have been evicted (oldest)"
    assert any("beta" in u for u in urls), "beta (active) must survive"
    print("PASS: pmo.city evicted (LRU), active beta survived")

    print("\nALL V1.6.0 CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
