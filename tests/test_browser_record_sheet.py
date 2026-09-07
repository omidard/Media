"""A record sheet must open from every page that links to one.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
Opening a medium from families.html rendered "Could not load <id> / The library
could not be reached ... Cannot read properties of null (reading
'evidence_classes')".

Two faults in one message, and both are asserted below.

1. The trigger. `catalog` in assets/media.js is the library-wide payload, and it
   is where the six evidence classes live; no per-medium record carries them.
   openMedium() awaited the record, the twin groups and the reference tables, and
   never the vocabulary. index.html and compare.html call loadCatalog() and
   patterns.html/methods.html call loadSummary(), so `catalog` happened to be
   populated there. families.html loads ONLY families.json, so every one of the
   1,170 medium links on it opened with `catalog === null` and renderMedium threw.

2. The misdiagnosis. Whatever the exception, the handler asserted "This is a
   network or server problem" and told the reader to reload. The fetch had
   succeeded; reloading could not help. A failure while rendering is now reported
   as what it is.

The test drives the real bundle in a real browser over a real HTTP server,
because both faults live in the interaction between a page's load path and a
shared module, which no unit test of either half can see.
"""
import functools
import http.server
import json
import os
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first_family_member():
    """A medium id that families.html actually links to."""
    path = os.path.join(REPO, "data", "web", "families.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        fams = json.load(fh)["families"]
    for fam in fams:
        for m in fam["members"]:
            if os.path.exists(os.path.join(REPO, "data", "media", m["id"] + ".json")):
                return m["id"]
    return None


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=REPO)
    handler.log_message = lambda *a, **k: None          # noqa: ARG005
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None   # noqa: ARG005
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % port
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                                   # noqa: BLE001
            pytest.skip("chromium is not installed for playwright: %s" % e)
        yield b
        b.close()


@pytest.mark.parametrize("page_name", ["families.html", "patterns.html",
                                       "index.html", "compare.html",
                                       "methods.html"])
def test_a_record_opens_from_every_page_that_can_open_one(server, browser, page_name):
    mid = _first_family_member()
    if mid is None:
        pytest.skip("the browser payload is not built in this tree")
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto("%s/%s" % (server, page_name), wait_until="load")
        page.wait_for_function("typeof MDB !== 'undefined'")
        page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=10000)
        # inner_text returns RENDERED text and the kicker is CSS-uppercased, so
        # this comparison is case-folded. Matching "Could not load" literally was
        # a test that passed against a reproduced failure.
        text = page.inner_text(".sheet").lower()
    finally:
        page.close()
    assert "could not load" not in text, (
        "%s could not open %s: %r. The record sheet must not depend on a payload "
        "the page's own load path never fetches." % (page_name, mid, text[:400]))
    assert not errors, "uncaught page error on %s: %s" % (page_name, errors[:2])


def test_a_render_failure_is_not_reported_as_a_network_fault(server, browser):
    """The misdiagnosis, asserted directly.

    The record is served with HTTP 200 and a body this code cannot render. The
    fetch therefore SUCCEEDS and the render fails, which is the exact case the
    old handler described as "a network or server problem" while telling the
    reader to reload.
    """
    mid = _first_family_member()
    if mid is None:
        pytest.skip("the browser payload is not built in this tree")
    page = browser.new_page()
    try:
        page.route("**/data/media/%s.json" % mid, lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"id": mid, "name": mid, "components": None,
                             "provenance": {}})))
        page.goto("%s/index.html" % server, wait_until="load")
        page.wait_for_function("typeof MDB !== 'undefined' && MDB.catalog")
        page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=10000)
        text = page.inner_text(".sheet").lower()
    finally:
        page.close()
    assert "network or server" not in text, (
        "a fault raised while rendering a record that was fetched successfully "
        "was reported to the reader as a network problem: %r" % text[:300])
    assert "could not be displayed" in text, (
        "a render failure must say what actually happened: %r" % text[:300])
    assert "reload the page and try again" not in text, (
        "a remedy that cannot work must not be offered")
