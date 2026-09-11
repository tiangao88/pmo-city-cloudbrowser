from types import SimpleNamespace
import pytest
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter


@pytest.mark.parametrize("urls,closed", [(["about:blank"], 0),
    (["about:blank", "chrome://newtab/"], 1),
    (["about:blank", "https://example.test"], 1)])
def test_desktop_cleanup_keeps_one_window(urls, closed):
    calls = []
    chrome = SimpleNamespace(json_request=lambda _: [dict(type="page", id=str(i), url=url) for i, url in enumerate(urls)],
        text_request=lambda *a, **kw: calls.append(a))
    ChromeBrowserAdapter(chrome, "alice", "g", preserve_last_page=True).close_empty_pages()
    assert len(calls) == closed
