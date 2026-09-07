"""The pages speak about the data, not about the machinery that built it.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
Two rules of the house voice standard were being broken on four of the five
browser pages, while both sibling tools scored zero on the same sweep, so the
three sites did not read as one resource.

1. BUILD PLUMBING NAMED AS AN ACTOR. Fifteen rendered sentences named "this
   pipeline" or "the pipeline", including the index hero, the compare page's own
   lead paragraph, two figure captions, the patterns warning banner and two
   methods stat tiles. Every one of them can be written about the components:
   the evidence class is `derived`, and the chip beside the sentence already
   said so, so the prose was repeating a label the reader had been given.

2. RAW PAYLOAD PATHS IN BODY PROSE. Five, across four pages: the sentence under
   the results table, the families footer, the methods degeneracy note, the
   patterns footer and the methods reproducibility line, plus one in the
   catalogue error message telling a reader to go and read the repository
   layout. A path is not actionable for the scientist using the resource, and
   the documented route to the same data is the API page.

WHY THE ASSERTIONS ARE SHAPED THIS WAY
--------------------------------------
* The path pattern is NOT anchored on `.json`. An earlier version of it was, and
  it passed on patterns.html while `data/cluster/` was still on screen.
* innerText cannot see `<meta name="description">`, and two of them carried the
  banned phrase, so search results and link previews would have kept saying it
  after a rendered-only check went green. The meta tags are asserted separately.
* index.html is loaded a second time with its catalogue payload failing, because
  the error branch renders copy the happy path never shows.
* One regression guard on a NUMBER, because the tempting rewrite of the patterns
  banner ("the standard base carried by every record") is false: the site's own
  methods page measures the derived base in 12,327 of 13,515 media, not all of
  them. A voice fix must not become a wrong count.
"""
import functools
import http.server
import os
import re
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index.html", "families.html", "compare.html", "patterns.html",
         "methods.html"]

# Bare `pipeline`, not only "this pipeline" / "the pipeline". The hyphenated form
# was the evidence class's own published label, so a rule that allowed it would
# have left the machinery named in a filter label, two methods table cells and
# every component chip while the prose around them was rewritten. The class is
# `derived` in the payload and is now called that everywhere it is shown.
PIPELINE = re.compile(r"\bpipelines?\b", re.I)
# Any repository path, not only a *.json one.
PAYLOAD_PATH = re.compile(r"(?:^|[\s(<\"'])data/[a-z0-9_]+/", re.I)


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=REPO)
    handler.log_message = lambda *a, **k: None                    # noqa: ARG005
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None  # noqa: ARG005
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
        except Exception as e:                                    # noqa: BLE001
            pytest.skip("chromium is not installed for playwright: %s" % e)
        yield b
        b.close()


def _rendered(browser, server, page_name, block=None):
    """The page's rendered text, every <details> forced open.

    `block` fails one payload, so the error branch's copy is measured too.
    """
    if not os.path.exists(os.path.join(REPO, "data", "web", "summary.json")):
        pytest.skip("the browser payload is not built in this tree")
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        if block:
            page.route(block, lambda route: route.fulfill(
                status=500, content_type="text/plain", body="upstream failure"))
        page.goto("%s/%s" % (server, page_name), wait_until="load")
        page.wait_for_function("typeof MDB !== 'undefined'")
        # The payload-driven copy replaces the static placeholders, so wait for
        # it rather than measuring the markup shipped in the file.
        page.wait_for_timeout(2500)
        page.evaluate("document.querySelectorAll('details').forEach(d => { d.open = true; })")
        page.wait_for_timeout(300)
        return page.inner_text("body")
    finally:
        page.close()


def _hits(rx, text):
    out = []
    for m in rx.finditer(text):
        a = max(0, m.start() - 90)
        z = min(len(text), m.end() + 90)
        out.append(text[a:z].replace("\n", " | "))
    return out


@pytest.mark.parametrize("page_name", PAGES)
def test_no_page_makes_the_build_pipeline_its_subject(browser, server, page_name):
    text = _rendered(browser, server, page_name)
    hits = _hits(PIPELINE, text)
    assert not hits, (
        "%s names the build pipeline in %d rendered sentence(s). The subject of a "
        "sentence on this site is the data: %s" % (page_name, len(hits), hits))


@pytest.mark.parametrize("page_name", PAGES)
def test_no_page_prints_a_payload_path_in_its_prose(browser, server, page_name):
    text = _rendered(browser, server, page_name)
    hits = _hits(PAYLOAD_PATH, text)
    assert not hits, (
        "%s prints a repository path in body prose. The route to the data is the "
        "API page, and a path is not actionable for a reader: %s" % (page_name, hits))


@pytest.mark.parametrize("page_name,block", [
    ("index.html", "**/data/web/catalog.json"),
    ("families.html", "**/data/web/families.json"),
    ("patterns.html", "**/data/cluster/clustergram.json"),
    ("methods.html", "**/data/web/summary.json"),
])
def test_the_failure_copy_is_held_to_the_same_voice(browser, server, page_name, block):
    """The error branch shows copy the happy path never renders."""
    text = _rendered(browser, server, page_name, block=block)
    bad = _hits(PIPELINE, text) + _hits(PAYLOAD_PATH, text)
    assert not bad, (
        "%s with its payload failing renders build plumbing to the reader: %s"
        % (page_name, bad))


@pytest.mark.parametrize("page_name", PAGES)
def test_the_meta_description_is_held_to_the_same_voice(page_name):
    """innerText never sees these, and a search result or link preview does."""
    path = os.path.join(REPO, page_name)
    if not os.path.exists(path):
        pytest.skip("%s is not in this tree" % page_name)
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    metas = re.findall(
        r"<meta[^>]+(?:name|property)=\"(?:description|og:description)\"[^>]*>",
        html, re.I)
    for tag in metas:
        assert not PIPELINE.search(tag), (
            "%s describes itself to search engines by naming the build pipeline: %s"
            % (page_name, tag))
        assert not PAYLOAD_PATH.search(tag), (
            "%s puts a repository path in its meta description: %s" % (page_name, tag))


def test_the_derived_base_keeps_its_denominator(browser, server):
    """A voice fix must not become a wrong count.

    The natural rewrite of the patterns banner is "the standard base carried by
    every record". It is false: derived components appear in 12,327 of 13,515
    media by the site's own measurement, so the honest words are "almost every"
    with the count published beside it on the methods page.
    """
    patterns = _rendered(browser, server, "patterns.html")
    methods = _rendered(browser, server, "methods.html")
    for name, text in (("patterns.html", patterns), ("methods.html", methods)):
        assert not re.search(
            r"base[^.]{0,60}\b(?:in|carried by|present in) every (?:record|medium)\b",
            text, re.I), (
            "%s claims the derived base is in every record; it is in 12,327 of "
            "13,515 media" % name)
    assert "12,327 of 13,515" in methods, (
        "the methods page must keep publishing the count and its denominator for "
        "the media carrying a derived component")
