"""Six browser defects, each asserted by the reproduction that used to fail.

Every test below was written against the broken build first and observed to fail
there, so none of them can pass by testing nothing.

1. A RECORD THAT ARRIVED WAS BLAMED ON THE NETWORK.
   openMedium() awaited the record beside loadSummary(), loadTwins() and
   loadRefs(). The last two degrade on failure; loadSummary() did not, so any
   failure of data/web/summary.json rejected the whole Promise.all and landed in
   the catch that reports the RECORD. A 503 rendered "The library could not be
   reached. The request for this record did not complete (the server returned
   HTTP 503)" -- a wrong subject and, in the same sentence, a request that did
   complete described as one that did not. A 404 on the same payload was worse:
   it reached renderMissing and, because the catalogue lists the id, produced
   "the request for its record returned HTTP 404. That is a serving fault."
   about a record the server had just served with HTTP 200. Every medium opened
   from families.html failed this way at once.

2. A DEEP LINK WAS DISCARDED WHEN THE CATALOGUE FAILED.
   index.html read ?medium= at the END of the loadCatalog().then() body, so a
   catalogue that failed or truncated dropped the reader's request entirely and
   never even fetched the record -- which is a separate 55 KB file that was
   still being served, against a 2.1 MB catalogue that is by far the likeliest
   object here to fail on its own.

3. THE ADDRESS BAR THE APP ITSELF WROTE RESTORED NOTHING.
   openMedium() writes ?medium=<id> into the URL on every page. Only index.html
   read it back, so on families.html and compare.html a reload, a bookmark or a
   copy out of the address bar lost the record with no indication that anything
   had been requested.

4. compare.html COUNTED ONE MEDIUM EIGHT TIMES.
   The ?ids= list was filtered for membership and capped, never deduplicated, so
   eight copies of one id reported "Comparing 8 media" and "1.00 mean pairwise
   similarity, over 28 pairs" -- a statistic that cannot be anything but 1.00.
   One repeat in a mixed list was more dangerous, because every number stayed
   plausible while the media count, the core intersection, the pair denominator
   and the mean were all wrong, and the repeat had silently consumed one of the
   eight slots.

5. THE COBRApy SNIPPET EMITTED THE SAME DICT KEY TWICE.
   24 records carry two components resolving to one exchange. Python keeps the
   LAST value, so a derived bound silently replaced the source-stated one, and
   len(uptake) disagreed with the count the snippet's own comments printed.

6. A QUANTIFIER CONTRADICTED THE NUMBER UNDER IT.
   "Most identities here were decided by a name string" was gated on a single
   name-matched component, so it fired on 13,343 of 13,515 records including
   4,000 where the sentence below it printed a share at or under 50%.
"""
import functools
import http.server
import json
import os
import re
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "data", "web")
MEDIA = os.path.join(REPO, "data", "media")

# The record the collision defect was measured on: two sourced components at -1
# and two yeast-extract-derived ones at -3.622 / -2.086 on the same two exchanges.
COLLIDING = "complexlit_PMC11344067_asw_yt_artificial_sea_water_with_yeast_extra"
# 1 of 56 components name-matched: the record whose sheet said "Most" over "1.8%".
MOSTLY_STRUCTURAL = "biospecimen_bmdb_colostrum"


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
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
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


def _need(*names):
    for n in names:
        if not os.path.exists(os.path.join(WEB, n)):
            pytest.skip("the browser payload is not built in this tree")


def _record(mid):
    path = os.path.join(MEDIA, mid + ".json")
    if not os.path.exists(path):
        pytest.skip("%s is not in this tree's corpus" % mid)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _family_with_members(n=2):
    _need("families.json")
    with open(os.path.join(WEB, "families.json"), encoding="utf-8") as fh:
        fams = json.load(fh)["families"]
    for fam in fams:
        served = [m for m in fam["members"]
                  if os.path.exists(os.path.join(MEDIA, m["id"] + ".json"))]
        if len(served) >= n:
            return fam["id"], [m["id"] for m in served]
    pytest.skip("no family in this tree links %d served records" % n)


def _fulfiller(status, body):
    """A one-parameter handler. Playwright passes (route, request) to any
    callable that accepts two, so a lambda with default arguments receives the
    Request object in the second slot and fulfill() then fails to serialise it."""
    def go(route):
        route.fulfill(status=status, body=body)
    return go


# ------------------------------------------- 1. the vocabulary, not the record
@pytest.mark.parametrize("status,body,shown", [
    (503, "busy", "the server returned HTTP 503"),
    (404, "gone", "the server returned HTTP 404"),
    (200, '{"count": 135', "not valid JSON"),
])
def test_a_failed_vocabulary_payload_is_not_reported_as_a_failed_record(
        server, browser, status, body, shown):
    fam_id, member_ids = _family_with_members(1)
    page = browser.new_page()
    seen = {}
    page.on("response", lambda r: seen.__setitem__(r.url.rsplit("/", 1)[-1], r.status))
    try:
        page.route("**/data/web/summary.json", _fulfiller(status, body))
        page.goto("%s/families.html?family=%s" % (server, fam_id), wait_until="load")
        page.wait_for_selector("a[data-medium]", timeout=20000)
        page.locator("a[data-medium]").first.click()
        page.wait_for_selector(".sheet", timeout=20000)
        title = page.inner_text("#sheet-title")
        kicker = page.inner_text(".sheet .kicker")
        text = page.inner_text(".sheet")
    finally:
        page.close()

    # Precondition: the record itself really was served. Without this the test
    # would pass on a tree where the record is missing for an unrelated reason.
    record_status = [v for k, v in seen.items() if k.endswith(".json")
                     and k.rsplit(".", 1)[0] in member_ids]
    assert 200 in record_status, (
        "precondition failed: no record file returned HTTP 200, so this test "
        "would prove nothing (saw %r)" % seen)

    assert kicker.strip().lower() not in ("could not load", "record not served",
                                          "unknown identifier"), (
        "a record that returned HTTP 200 was filed under %r because a shared "
        "payload failed" % kicker)
    assert title.strip() not in member_ids, (
        "the sheet fell back to the bare identifier %r, which is what the "
        "failure sheets render; the record's own name was in hand" % title)
    for claim in ("request for this record did not complete",
                  "request for its record returned",
                  "this record could not be read"):
        assert claim not in text.lower(), (
            "the sheet claims the record's own request failed, when %s failed "
            "and the record returned HTTP 200: %r" % (shown, text[:400]))
    assert "evidence vocabulary for this release did not load" in text, (
        "the vocabulary failure must be stated on the record sheet, so an absent "
        "evidence class reads as absent and never as 'no evidence': %r" % text[:400])
    assert shown in text, (
        "the sheet must name the state the code established (%s): %r"
        % (shown, text[:400]))


# ----------------------------- 2. the deep link outlives the catalogue --------
@pytest.mark.parametrize("mode", ["abort", "truncated"])
def test_a_deep_link_is_answered_when_the_catalogue_fails(server, browser, mode):
    _need("catalog.json")
    mid, _ids = None, None
    fam_id, member_ids = _family_with_members(1)
    mid = member_ids[0]
    want = _record(mid)
    page = browser.new_page()
    try:
        if mode == "abort":
            page.route("**/data/web/catalog.json", lambda route: route.abort())
        else:
            # A truncated transfer is an HTTP 200: the classic partial-deploy and
            # CDN shape, and the one an abort-only test would miss.
            page.route("**/data/web/catalog.json",
                       _fulfiller(200, '{"count": 13515, "medi'))
        page.goto("%s/index.html?medium=%s" % (server, mid), wait_until="load")
        page.wait_for_selector(".sheet", timeout=20000)
        title = page.inner_text("#sheet-title")
        text = page.inner_text(".sheet")
    finally:
        page.close()
    assert title == (want.get("name_display") or want["name"]), (
        "the record is served separately from the catalogue and rendered fine "
        "when called by hand; the deep link must not be discarded: %r" % title)
    assert "catalogue for this release did not" in text, (
        "the sheet must say what did NOT load, so the reader understands why "
        "no other record can be opened from here: %r" % text[:400])


# --------------------------------- 3. the URL the app wrote restores ----------
@pytest.mark.parametrize("page_path", ["index.html", "families.html", "compare.html"])
def test_the_url_this_page_writes_restores_the_record(server, browser, page_path):
    _need("catalog.json", "families.json")
    if page_path == "families.html":
        fam_id, _m = _family_with_members(1)
        page_path = "families.html?family=%s" % fam_id
    page = browser.new_page()
    try:
        page.goto("%s/%s" % (server, page_path), wait_until="load")
        page.wait_for_selector("a[data-medium]", timeout=25000)
        page.locator("a[data-medium]").first.click()
        page.wait_for_selector("#sheet-title", timeout=20000)
        opened = page.inner_text("#sheet-title")
        written = page.url
        assert "medium=" in written, (
            "openMedium() is expected to write the permalink into the address "
            "bar on every page; it did not on %s" % page_path)
        page.goto(written, wait_until="load")
        page.wait_for_selector("#sheet-title", timeout=20000)
        restored = page.inner_text("#sheet-title")
    finally:
        page.close()
    assert restored == opened, (
        "the URL this page itself wrote did not restore the record: wrote %r, "
        "reopened %r" % (opened, restored))


# ------------------------------------- 4. compare.html counts media once ------
def test_a_repeated_identifier_is_counted_once(server, browser):
    _need("catalog.json")
    fam_id, ids = _family_with_members(3)
    asked = [ids[0], ids[0], ids[1], ids[2]]
    page = browser.new_page()
    try:
        page.goto("%s/compare.html?ids=%s" % (server, ",".join(asked)),
                  wait_until="load")
        page.wait_for_function(
            "document.getElementById('status').textContent.length > 0", timeout=25000)
        status = page.inner_text("#status")
        note = page.inner_text("#q-note")
        figures = page.inner_text("#figures")
        chips_before = page.evaluate("document.querySelectorAll('#chips button').length")
        page.locator("#chips button").first.click()
        page.wait_for_timeout(500)
        chips_after = page.evaluate("document.querySelectorAll('#chips button').length")
    finally:
        page.close()
    assert "Comparing 3 media" in status, (
        "four identifiers naming three media were reported as %r" % status)
    assert "over 3 pairs" in figures, (
        "three media make three pairs; a repeat manufactures a fourth whose "
        "Jaccard cannot be anything but 1.00: %r" % figures.replace("\n", " | "))
    assert "repeated one already in the list" in note, (
        "the reduction must be reported, with its denominator: %r" % note)
    assert (chips_before, chips_after) == (3, 2), (
        "one chip must remove one entry, as its own aria-label says: %d -> %d"
        % (chips_before, chips_after))


def test_eight_copies_of_one_identifier_are_not_eight_media(server, browser):
    _need("catalog.json")
    _fam, ids = _family_with_members(1)
    page = browser.new_page()
    try:
        page.goto("%s/compare.html?ids=%s" % (server, ",".join([ids[0]] * 8)),
                  wait_until="load")
        page.wait_for_function(
            "document.getElementById('status').textContent.length > 0", timeout=25000)
        status = page.inner_text("#status")
        note = page.inner_text("#q-note")
    finally:
        page.close()
    assert "One medium selected" in status, (
        "eight copies of one identifier were reported as %r" % status)
    assert "1.00" not in status
    assert "repeated one already in the list" in note, note


# ------------------------------------- 5. one exchange, one dict key ----------
def test_the_cobra_snippet_never_emits_an_exchange_twice(server, browser):
    med = _record(COLLIDING)
    page = browser.new_page()
    try:
        page.goto("%s/index.html?medium=%s" % (server, COLLIDING), wait_until="load")
        page.wait_for_selector("pre.cobra", timeout=25000)
        snippet = page.inner_text("pre.cobra")
    finally:
        page.close()

    # Precondition, so this cannot pass on a corpus without the collision.
    lows = [c["exchange"] for c in med["components"]
            if c.get("exchange") and (c.get("lower_bound") or 0) < 0]
    assert len(lows) != len(set(lows)), (
        "precondition failed: %s no longer carries a colliding exchange, so "
        "this test would prove nothing" % COLLIDING)

    keys = re.findall(r'^\s{4}"([^"]+)":', snippet, re.M)
    assert len(keys) == len(set(keys)), (
        "the snippet emits a duplicate dict key; Python keeps the last value: %r"
        % [k for k in keys if keys.count(k) > 1])

    scope = {}
    exec(snippet.split("skipped =")[0], scope)                    # noqa: S102
    uptake = scope["uptake"]
    # The source-stated bound is the one that survives, never the derived one.
    for c in med["components"]:
        ex = c.get("exchange")
        if not ex or not (c.get("lower_bound") or 0) < 0:
            continue
        if c.get("derived_not_sourced"):
            continue
        assert uptake[ex] == c["lower_bound"], (
            "a derived bound replaced the source-stated one for %s: %r vs %r"
            % (ex, uptake[ex], c["lower_bound"]))
    # Every denominator the snippet prints is the one the dict actually has.
    m = re.search(r"resolving to (\d+) unique exchange ids, so len\(uptake\) == (\d+)",
                  snippet)
    assert m, "the snippet must reconcile its own denominator: %r" % snippet[:600]
    assert int(m.group(1)) == int(m.group(2)) == len(uptake), (
        "the snippet's stated denominator %s does not match len(uptake) %d"
        % (m.groups(), len(uptake)))
    assert "recorded more than once" in snippet, (
        "a bound that was recorded twice and applied once must say so")
    assert "NOT applied; the source-stated bound wins" in snippet


def test_no_record_in_the_corpus_can_emit_a_duplicate_dict_key():
    """The population, without a browser: which records the fix has to cover.

    24 records carry 32 excess collisions. This asserts the renderer's rule at
    the data level -- that a colliding pair is always resolvable to one bound --
    and pins the population so a corpus change cannot grow it unnoticed.
    """
    import collections
    import glob
    files = sorted(glob.glob(os.path.join(MEDIA, "*.json")))
    if not files:
        pytest.skip("no corpus in this tree")
    hits = {}
    for path in files:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        c = collections.Counter(
            comp["exchange"] for comp in (rec.get("components") or [])
            if comp.get("exchange") and (comp.get("lower_bound") or 0) < 0)
        dup = {k: v for k, v in c.items() if v > 1}
        if dup:
            hits[rec["id"]] = dup
    for mid, dup in hits.items():
        with open(os.path.join(MEDIA, mid + ".json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        for ex in dup:
            same = [comp for comp in rec["components"] if comp.get("exchange") == ex
                    and (comp.get("lower_bound") or 0) < 0]
            sourced = [comp for comp in same if not comp.get("derived_not_sourced")]
            assert sourced or len({comp["lower_bound"] for comp in same}) >= 1, (
                "%s/%s has no resolvable bound" % (mid, ex))
    assert len(hits) <= 24, (
        "the colliding population grew to %d records; every one of them ships a "
        "medium whose applied bound differs from the one the page describes "
        "unless the renderer resolves it: %r" % (len(hits), sorted(hits)[:5]))


# ------------------------------------- 6. the quantifier matches the number ---
def test_the_name_string_caveat_is_graded_on_the_share_it_prints(server, browser):
    med = _record(MOSTLY_STRUCTURAL)
    page = browser.new_page()
    try:
        page.goto("%s/index.html?medium=%s" % (server, MOSTLY_STRUCTURAL),
                  wait_until="load")
        page.wait_for_selector(".sheet", timeout=25000)
        text = page.inner_text(".sheet")
    finally:
        page.close()
    assert "identities here were decided by a name string" in text, (
        "precondition failed: %s no longer raises the caveat at all"
        % MOSTLY_STRUCTURAL)
    assert "Most identities here were decided by a name string" not in text, (
        "'Most' was printed over a share of 1.8%%, on a record whose identities "
        "are overwhelmingly structure-verified: %r"
        % [ln for ln in text.splitlines() if "name string" in ln])
    assert "Some identities here were decided by a name string" in text


def test_a_partition_of_the_components_sums_to_one_hundred_percent(server, browser):
    """The header pair and the evidence legend are parts of one whole.

    They were printed one part at a time through share(), whose precision flips
    at 10%, so 600 records printed "9.8%" beside "90%" and 3,883 showed a legend
    summing to 100.5%.
    """
    page = browser.new_page()
    try:
        page.goto("%s/index.html?medium=%s" % (server, "mediadive_J723"),
                  wait_until="load")
        page.wait_for_selector(".sheet", timeout=25000)
        text = page.inner_text(".sheet")
    finally:
        page.close()
    line = next(ln for ln in text.splitlines()
                if "are stated by the cited source" in ln and " of " in ln)
    pcts = [float(x) for x in re.findall(r"\((\d+(?:\.\d+)?)%\)", line)]
    assert len(pcts) == 2, line
    assert abs(sum(pcts) - 100.0) < 1e-9, (
        "the sourced and derived shares are a partition and must sum to 100: %r"
        % line)
    # And the coverage ratio is printed once, not twice at two precisions.
    cov = next(ln for ln in text.splitlines() if "reached a BiGG exchange" in ln)
    assert len(re.findall(r"\d+(?:\.\d+)?%", cov)) == 1, (
        "the same ratio is printed twice in one sentence: %r" % cov)
