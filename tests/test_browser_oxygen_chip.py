"""The browse table and the record sheet must say the same thing about oxygen.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
The oxygen regime is published as recorded, so 11,926 records whose source stated
nothing now read as unknown in the catalogue. The record sheet does not read the
catalogue: it reads the per-medium file, which still carries the pipeline's
`facultative` default with the reason in `oxygen_note`. Without the rule applied
in both places, the browse row for a medium would say "O2 unknown" and the sheet
opened from that very row would say "facultative", which is worse than either
being wrong on its own.

The rule lives in ONE place, the payload's `oxygen_basis.unstated_notes`, and both
the builder and the browser read it from there.
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


def _a_defaulted_record():
    """A record whose facultative regime came from the no-statement default.

    Selected through web_payload.oxygen_recorded(), NOT by matching
    oxygen == "facultative" on the record. That spelling was the defect, and when
    54_oxygen_regime_absent_when_unstated corrected it this fixture stopped finding
    any record at all and skipped: 11,926 records still needed exactly this test and
    the suite reported nothing. `make test-browser-strict` refuses a skip, which is
    the only reason it was noticed, and a guard that disappears when its defect is
    fixed is a guard that cannot catch the defect coming back.

    The condition is "no source stated this record's regime", which is true of the
    same 11,926 records before and after the correction.
    """
    import web_payload
    path = os.path.join(REPO, "data", "media")
    if not os.path.isdir(path):
        pytest.skip("no corpus in this tree")
    for name in sorted(os.listdir(path))[:4000]:
        if not name.endswith(".json"):
            continue
        with open(os.path.join(path, name), encoding="utf-8") as fh:
            rec = json.load(fh)
        regime, assumed = web_payload.oxygen_recorded(rec)
        if regime is None and assumed == "facultative":
            return rec["id"]
    pytest.fail("no record in the first 4,000 has a regime no source stated, and "
                "11,926 of the 13,515 do. Either the corpus changed shape or this "
                "fixture stopped describing the condition it selects for; a skip "
                "here silently retires the test.")


@pytest.mark.parametrize("page_name", ["index.html", "families.html"])
def test_the_record_sheet_and_the_browse_table_agree(server, browser, page_name):
    mid = _a_defaulted_record()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        # index.html reads ?medium=; families.html does not (it reads ?family=),
        # so a record is opened there the way the page itself opens one.
        if page_name == "index.html":
            page.goto("%s/%s?medium=%s" % (server, page_name, mid), wait_until="load")
        else:
            page.goto("%s/%s" % (server, page_name), wait_until="load")
            page.wait_for_function("typeof MDB !== 'undefined'")
            page.evaluate("(id) => MDB.openMedium(id)", mid)
        page.wait_for_selector(".sheet", timeout=20000)
        sheet = page.inner_text(".sheet").lower()
    finally:
        page.close()
    assert "facultative" not in sheet, (
        "%s renders 'facultative' for %s, whose own oxygen_note says the source "
        "stated no regime at all. The browse table calls it unknown: %r"
        % (page_name, mid, sheet[:400]))
    assert "o₂ unknown" in sheet or "o2 unknown" in sheet, (
        "the record sheet must show the regime as unknown: %r" % sheet[:400])
    assert "the oxygen regime is unknown" in sheet, (
        "the record sheet's own caution must fire for a medium whose regime no "
        "source stated: %r" % sheet[:600])


def test_the_unknown_filter_returns_the_whole_unknown_set(server, browser):
    """The filter a modeller uses to find the records they must decide.

    It returned 439 and silently missed 11,926 that need the same decision.
    """
    with open(os.path.join(WEB, "summary.json"), encoding="utf-8") as fh:
        want = json.load(fh)["by_oxygen"]["None"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto("%s/index.html" % server, wait_until="load")
        page.wait_for_selector("table.grid tbody tr", timeout=20000)
        page.select_option("#f-oxygen", "__unknown")
        page.wait_for_timeout(1200)
        line = page.inner_text("#resultline")
    finally:
        page.close()
    assert "{:,}".format(want) in line, (
        "the 'Unknown (not recorded)' filter reports %r; the library holds %s media "
        "with no recorded regime" % (line, "{:,}".format(want)))


def test_the_sheet_says_what_the_exported_medium_does_with_ex_o2_e(server, browser):
    """Unknown is only half the answer; the reader is about to copy a medium.

    The sheet used to add "The medium exported below still opens EX_o2_e, by the
    same convention that supplies the mineral base" whenever the record STATED a
    regime we do not publish. That test was `med.oxygen && med.oxygen !== o2`, an
    inference from the defect, and it went silently false the moment
    54_oxygen_regime_absent_when_unstated nulled `oxygen`: every one of the 11,926
    sheets kept the "the regime is unknown" caution and lost the sentence saying
    which way the exported medium was written. A reader would have been told to
    decide EX_o2_e themselves with no indication that the block below already had.

    The sheet reads oxygen_default_for_simulation off the record now, so the
    convention is stated because it is recorded, not inferred from a defect.
    """
    mid = _a_defaulted_record()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto("%s/index.html?medium=%s" % (server, mid), wait_until="load")
        page.wait_for_selector(".sheet", timeout=20000)
        sheet = page.inner_text(".sheet")
    finally:
        page.close()
    assert "still opens EX_o2_e" in sheet, (
        "%s has no stated regime and its exported medium opens EX_o2_e by "
        "convention; the sheet must say so beside the caution telling the reader "
        "to decide it themselves: %r" % (mid, sheet[:800]))
    assert "not a finding about this medium" in sheet, (
        "the convention must be labelled as a convention: %r" % sheet[:800])
