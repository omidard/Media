"""What the record sheet says when a record does not arrive, or arrives unreadable.

THE DEFECTS THIS FILE EXISTS FOR
--------------------------------
Four separate ways the browser told a reader something the code had not
established. Each one is asserted here against a real bundle in a real browser,
because every one of them lives in the interaction between the fetch layer, the
per-page load path and the render, which no unit test of any single half sees.

1. A 404 ON A CATALOGUED IDENTIFIER WAS CALLED AN UNKNOWN IDENTIFIER.
   renderMissing() branched only on the tombstone table. A record file that did
   not come back therefore rendered "It is not in the library of 13,515 media",
   while `catalog.media` in the same page held that identifier and the "closest
   identifiers" list six lines lower offered the record its own name. On
   families.html the catalogue is never loaded at all, so the contradicting list
   was skipped and the false sentence stood alone.

2. AN UNPARSEABLE BODY WAS CALLED A NETWORK FAULT.
   getJSON() typed fetch rejection, 404 and non-ok status, then returned
   `response.json()` untyped. Its SyntaxError carried no `kind`, so a 200 whose
   body cannot be parsed (a captive-portal block page, a corrupted cache object,
   a truncated file) fell through to "The library could not be reached ...
   Reloading the page may succeed." The response had arrived intact and reloading
   returns the same bytes.

3. THE SAME UNTAGGED REJECTION FABRICATED A SCIENTIFIC CLAIM.
   loadTwins/loadTombstones/loadRefs record `_error: e.kind`, and undefined is
   falsy, so their "could not be checked" guards never fired for a parse failure.
   A twins.json that never loaded rendered "None. The set of exchange reactions
   and bounds this record hands a model is unique among the ... media in this
   library" -- an absent value rendered as a confident finding.

4. THE FIRST RECORD CLICKED WON.
   openMedium() rendered and pushed history whenever its own await resolved, with
   no check against a newer call. On a slow or variable link a reader who clicked
   a second medium was silently left on the first, with the URL rewritten to
   match, so the permalink they copied named a record they did not choose.

A fifth assertion covers the suggestion list itself: it ranked candidates by
common leading characters of the identifier, which for a withdrawn id means the
collection prefix plus however many digits of a PubMed Central accession happen
to agree. That is string identity presented as closeness.
"""
import functools
import http.server
import json
import os
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "data", "web")


# --------------------------------------------------------------- fixtures --
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


def _require_payload():
    """These tests assert on the shipped browser payload; it must be present."""
    for name in ("catalog.json", "families.json", "tombstones.json"):
        if not os.path.exists(os.path.join(WEB, name)):
            pytest.skip("the browser payload is not built in this tree")


def _catalogued_id():
    """An identifier the catalogue lists AND whose record file exists.

    Both halves matter: the defect is that a 404 on a record the catalogue DOES
    list was reported as an identifier the library does not hold. A test seeded
    with an id that is genuinely absent would pass vacuously.
    """
    _require_payload()
    with open(os.path.join(WEB, "catalog.json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    idx = cat["columns"].index("id")
    for row in cat["rows"]:
        mid = row[idx]
        if os.path.exists(os.path.join(REPO, "data", "media", mid + ".json")):
            return mid
    pytest.skip("no catalogued record file to test against")


def _family_member_id():
    """An id families.html links to, and which the catalogue also lists."""
    _require_payload()
    with open(os.path.join(WEB, "families.json"), encoding="utf-8") as fh:
        fams = json.load(fh)["families"]
    for fam in fams:
        for m in fam["members"]:
            if os.path.exists(os.path.join(REPO, "data", "media", m["id"] + ".json")):
                return m["id"]
    pytest.skip("families.json links to no record present in this tree")


def _tombstone_id():
    _require_payload()
    with open(os.path.join(WEB, "tombstones.json"), encoding="utf-8") as fh:
        tomb = json.load(fh)
    ids = sorted((tomb.get("records") or {}).keys())
    if not ids:
        pytest.skip("no withdrawn identifiers in this tree")
    return ids[0]


def _sheet_text(page):
    return page.inner_text(".sheet").lower()


# ------------------------------------------- 1. a 404 on a catalogued id ---
@pytest.mark.parametrize("how", ["in_page", "deep_link", "families"])
def test_a_404_on_a_catalogued_id_is_not_called_an_unknown_identifier(
        server, browser, how):
    """The record file does not come back; the catalogue still lists the id.

    The honest statement is that the request returned 404, which is a serving
    fault. Saying "it is not in the library" asserts a cause the code has not
    established, and the code is holding the catalogue that disproves it.

    `families` is the path that matters most and the one the original finding
    missed: that page loads summary.json, which has no `.media`, so the code
    could not check even in principle and the contradicting suggestion list was
    not rendered either. The false sentence stood there with no tell at all.
    """
    mid = _family_member_id() if how == "families" else _catalogued_id()
    page = browser.new_page()
    try:
        page.route("**/data/media/%s.json" % mid,
                   lambda route: route.fulfill(status=404, body="not found"))
        if how == "deep_link":
            page.goto("%s/index.html?medium=%s" % (server, mid), wait_until="load")
        else:
            page_name = "families.html" if how == "families" else "index.html"
            page.goto("%s/%s" % (server, page_name), wait_until="load")
            page.wait_for_function("typeof MDB !== 'undefined'")
            page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=15000)
        text = _sheet_text(page)
        # Precondition, so this test cannot pass by testing nothing: the
        # catalogue really does list the identifier the sheet is talking about.
        listed = page.evaluate(
            "(id) => MDB.catalog && MDB.catalog.media"
            " ? MDB.catalog.media.some((r) => r.id === id) : null", mid)
    finally:
        page.close()
    assert listed is True, (
        "precondition failed: after the sheet rendered, the page does not hold a "
        "catalogue listing %s, so this test would prove nothing" % mid)
    assert "is not in the library" not in text, (
        "a record that returned HTTP 404 while the catalogue lists its identifier "
        "was reported as an identifier the library does not hold: %r" % text[:400])
    assert "404" in text, (
        "the sheet must name what actually happened, an HTTP 404 on the record "
        "file: %r" % text[:400])
    assert "never published" not in text
    # The suggestion list must not offer the record back to itself.
    assert "closest identifiers" not in text, (
        "a record whose own identifier is catalogued must not be offered a list of "
        "near misses headed by itself: %r" % text[:400])


# ------------------------------------- 2. a 200 whose body cannot be read ---
@pytest.mark.parametrize("body,content_type", [
    ("{not json", "application/json"),
    ("<html><body>Access blocked by your network.</body></html>", "text/html"),
])
def test_an_unparseable_record_body_is_not_reported_as_a_network_fault(
        server, browser, body, content_type):
    """The fetch completed. Calling that a network fault is a false cause, and
    the remedy it offers (reload) returns the same bytes."""
    mid = _catalogued_id()
    page = browser.new_page()
    try:
        page.route("**/data/media/%s.json" % mid, lambda route: route.fulfill(
            status=200, content_type=content_type, body=body))
        page.goto("%s/index.html" % server, wait_until="load")
        page.wait_for_function("typeof MDB !== 'undefined' && MDB.catalog")
        page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=15000)
        text = _sheet_text(page)
    finally:
        page.close()
    assert "network or server" not in text, (
        "a response that arrived with HTTP 200 was reported as a network or "
        "server fault: %r" % text[:400])
    assert "could not be reached" not in text, (
        "the library was reached; it answered: %r" % text[:400])
    assert "reloading the page may succeed" not in text, (
        "the same bytes will come back, so that remedy cannot work: %r" % text[:400])
    assert "could not be read" in text, (
        "the sheet must say what actually happened: %r" % text[:400])


def test_an_unparseable_twins_payload_does_not_claim_the_record_is_unique(
        server, browser):
    """The load-bearing one: this is a scientific claim, not a wording problem.

    twins.json arrives with a body that cannot be parsed, so the degeneracy check
    never ran. The record sheet must say the check could not be run. Saying the
    model input is "unique among the N media in this library" is an absent value
    rendered as a finding. The 404 case on the same file was already handled
    correctly, which is what made the parse case invisible.
    """
    mid = _catalogued_id()
    page = browser.new_page()
    try:
        page.route("**/data/web/twins.json", lambda route: route.fulfill(
            status=200, content_type="application/json", body="{not json"))
        page.goto("%s/index.html" % server, wait_until="load")
        page.wait_for_function("typeof MDB !== 'undefined' && MDB.catalog")
        page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=15000)
        text = _sheet_text(page)
    finally:
        page.close()
    assert "unique among" not in text, (
        "a degeneracy payload that never loaded produced a confident claim that "
        "this record's model input is unique: %r" % text[:600])
    assert "could not be run" in text, (
        "an unrunnable check must say so: %r" % text[:600])


# ------------------------------------------------ 3. the click-order race ---
def test_the_medium_clicked_last_is_the_one_displayed(server, browser):
    """A slow first record must not overwrite a fast second one.

    Driven with genuine mouse clicks, and the delay applied with the ASYNC route
    API: a synchronous sleep inside a Playwright route handler blocks the driver
    and lets the first sheet mount before the second click lands, which is a
    false pass rather than a test.
    """
    pytest.importorskip("playwright.async_api")
    import asyncio

    from playwright.async_api import async_playwright

    first = _catalogued_id()
    # The async body runs on its own loop in its own thread. Calling asyncio.run()
    # inline raises "cannot be called from a running event loop" when anything
    # else in the session (a plugin, another async fixture) already owns one.
    result = {}
    with open(os.path.join(WEB, "catalog.json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    idx = cat["columns"].index("id")
    ids = [r[idx] for r in cat["rows"]]
    second = None
    for mid in ids:
        if mid != first and os.path.exists(
                os.path.join(REPO, "data", "media", mid + ".json")):
            second = mid
            break
    if second is None:
        pytest.skip("need two catalogued records")

    async def run():
        async with async_playwright() as p:
            b = await p.chromium.launch()
            page = await b.new_page()

            async def slow(route):
                await asyncio.sleep(3.0)
                await route.continue_()

            await page.route("**/data/media/%s.json" % first, slow)
            await page.goto("%s/index.html" % server, wait_until="load")
            await page.wait_for_function("typeof MDB !== 'undefined' && MDB.catalog")
            # Two real links on the page, clicked in order.
            await page.evaluate(
                """([a, b]) => {
                     const host = document.createElement('div');
                     host.id = 'racetest';
                     host.style.cssText =
                       'position:fixed;top:0;left:0;z-index:99999;background:#fff';
                     host.innerHTML =
                       '<a id="ra" href="#" data-medium="' + a + '">A</a> ' +
                       '<a id="rb" href="#" data-medium="' + b + '">B</a>';
                     document.body.appendChild(host);
                   }""", [first, second])
            await page.click("#ra")
            await asyncio.sleep(0.3)
            await page.click("#rb")
            # Long enough for the slow first record to land and clobber.
            await asyncio.sleep(5.0)
            title = await page.inner_text("#sheet-title")
            url = page.url
            sheets = await page.eval_on_selector_all(".sheet", "n => n.length")
            await b.close()
            return title, url, sheets

    def worker():
        try:
            result["value"] = asyncio.run(run())
        except BaseException as e:                                # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join(180)
    assert not t.is_alive(), "the race reproduction did not finish"
    if "error" in result:
        raise result["error"]
    title, url, sheets = result["value"]
    assert sheets == 1, "more than one record sheet is mounted: %d" % sheets
    assert ("medium=%s" % second) in url, (
        "the reader clicked %s last; the URL names %s, so the permalink they copy "
        "points at a record they did not choose: %s" % (second, first, url))
    assert first not in title and title, (
        "the reader clicked %s last and is looking at %s: %r"
        % (second, first, title))


# --------------------------------- 4. suggestions a computation supports ---
def test_a_withdrawn_identifier_is_offered_no_closest_identifiers(server, browser):
    """Prefix similarity is not closeness.

    Scored on common leading characters, every one of the 333 `complexlit_`
    identifiers clears the threshold on the shared prefix alone, and the ranking
    is then decided by how many leading digits of a PubMed Central accession
    agree. PMC accessions are assigned by deposit order. For 42 of the 77
    withdrawn identifiers not one of the five suggestions shared a single content
    word with the withdrawn record's own name.

    A withdrawn record also has no composition to rank by: tombstones carry a
    name and a reason code and nothing else, and the reasons include
    "no composition recorded". So there is no honest list to show here at all,
    and the card already says no other record is a substitute for it.
    """
    tid = _tombstone_id()
    page = browser.new_page()
    try:
        page.goto("%s/index.html?medium=%s" % (server, tid), wait_until="load")
        page.wait_for_selector(".sheet", timeout=15000)
        text = _sheet_text(page)
    finally:
        page.close()
    assert "withdrawn" in text, (
        "expected the tombstone sheet for %s: %r" % (tid, text[:300]))
    assert "closest identifiers" not in text, (
        "a withdrawn identifier was offered substitutes ranked by how many leading "
        "characters of the identifier string agreed: %r" % text[:600])
