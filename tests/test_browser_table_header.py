"""The results table header: one baseline, aligned with its columns, fully clickable.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
`th.sortable{padding:0}` (specificity 0-1-1) never applied, because
`table.grid th,table.grid td{...padding:var(--s2) var(--s3)...}` (0-1-2) outranks
it regardless of source order. The reset looked present and did nothing, which is
why this survived: the sortable cell kept its own 8px/12px padding AND the button
inside it added another 8px/12px.

Three consequences, in rising order of seriousness, and all three are asserted
here because a fix for the first alone would leave the other two:

1. Six header labels on two baselines. The four sortable columns sat 8px below
   the two bare-text ones, in the most-looked-at table in the library.

2. Four of six header labels sat 12px to the right of their own column's data.
   A data table whose column headings do not line up with their columns.

3. The button covered only 56 to 65 per cent of the header cell it fills, so
   roughly a third of each sorting control was a dead ring that silently did
   nothing. Measured by behaviour, not geometry: a click 4px inside the cell left
   the sort order unchanged while a click at the centre re-sorted the table.

Assertion 3 is the one that matters and the one a geometry-only fix passes
without earning, so it is written as a real click at a real coordinate.
"""
import functools
import http.server
import os
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The label box of a cell, measured over its first non-empty TEXT NODE. Measuring
# the element box instead reports the padded cell and hides exactly the offsets
# this file is about.
LABEL_BOXES = """
() => {
  const box = (host) => {
    const w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      if (w.currentNode.textContent.trim()) {
        const r = document.createRange();
        r.selectNodeContents(w.currentNode);
        const b = r.getBoundingClientRect();
        if (b.width || b.height) {
          return { top: Math.round(b.top * 100) / 100,
                   left: Math.round(b.left * 100) / 100 };
        }
      }
    }
    return null;
  };
  // The column's content origin, not the first glyph inside it: a body cell may
  // hold a chip with padding of its own, which is a different question.
  const contentLeft = (cell) => {
    const r = cell.getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(cell).paddingLeft) || 0;
    return Math.round((r.left + pad) * 100) / 100;
  };
  const ths = [...document.querySelectorAll('table.grid thead th')];
  const firstRow = document.querySelector('table.grid tbody tr');
  return ths.map((th, i) => {
    const cell = firstRow ? firstRow.children[i] : null;
    return {
      text: th.textContent.trim(),
      sortable: !!th.querySelector('button'),
      head: box(th),
      body: cell ? { left: contentLeft(cell) } : null
    };
  });
}
"""


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


def _results_page(browser, server, width):
    if not os.path.exists(os.path.join(REPO, "data", "web", "catalog.json")):
        pytest.skip("the browser payload is not built in this tree")
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto("%s/index.html" % server, wait_until="load")
    page.wait_for_selector("table.grid tbody tr", timeout=20000)
    return page


@pytest.mark.parametrize("width", [1280, 1440])
def test_every_results_header_label_shares_one_baseline(browser, server, width):
    page = _results_page(browser, server, width)
    try:
        cells = page.evaluate(LABEL_BOXES)
    finally:
        page.close()
    assert len(cells) >= 4, "the results table did not render its header"
    tops = sorted({c["head"]["top"] for c in cells if c["head"]})
    assert len(tops) == 1, (
        "the header row renders its labels on %d baselines at %dpx: %s"
        % (len(tops), width,
           [(c["text"], c["sortable"], c["head"]["top"]) for c in cells if c["head"]]))


@pytest.mark.parametrize("width", [1280, 1440])
def test_every_header_label_is_aligned_with_its_own_column(browser, server, width):
    page = _results_page(browser, server, width)
    try:
        cells = page.evaluate(LABEL_BOXES)
    finally:
        page.close()
    offsets = [(c["text"], round(c["head"]["left"] - c["body"]["left"], 2))
               for c in cells if c["head"] and c["body"]]
    assert offsets, "no column had both a header label and a body value to compare"
    bad = [o for o in offsets if abs(o[1]) > 0.5]
    assert not bad, (
        "a column heading does not sit above its own column at %dpx (header left "
        "minus body left, in px): %s" % (width, bad))


def test_the_whole_sortable_header_cell_sorts(browser, server):
    """The corner of a sorting control must sort.

    A click 4px inside the top-left of the header cell is an ordinary way to hit
    a column heading. It landed on the TH, not on the button inside it, and did
    nothing at all, with no cue that the control had a dead margin.
    """
    page = _results_page(browser, server, 1280)
    try:
        target = page.evaluate("""
        () => {
          const th = [...document.querySelectorAll('table.grid thead th')]
                       .find((t) => t.querySelector('button'));
          if (!th) return null;
          th.scrollIntoView({ block: 'center' });
          const r = th.getBoundingClientRect();
          return { x: r.left, y: r.top, w: r.width, h: r.height };
        }""")
        assert target, "no sortable column header on the results table"
        before = page.eval_on_selector_all(
            "table.grid tbody tr td:first-child",
            "ns => ns.slice(0, 3).map(n => n.innerText.trim())")
        # What the cell reports under its own top-left corner. A control that
        # looks like one target must not be two.
        at_corner = page.evaluate(
            "([x, y]) => (document.elementFromPoint(x, y) || {}).tagName",
            [target["x"] + 4, target["y"] + 4])
        page.mouse.click(target["x"] + 4, target["y"] + 4)
        page.wait_for_timeout(700)
        after = page.eval_on_selector_all(
            "table.grid tbody tr td:first-child",
            "ns => ns.slice(0, 3).map(n => n.innerText.trim())")
    finally:
        page.close()
    assert before, "the results table rendered no rows to sort"
    assert after != before, (
        "clicking 4px inside a sortable column header did not sort the table; the "
        "point reports %s, so roughly a third of the control is a dead ring that "
        "silently does nothing. rows before=%s after=%s"
        % (at_corner, before, after))


def test_a_sortable_button_fills_its_header_cell(browser, server):
    """Geometry behind the click test, so a regression names its own cause."""
    page = _results_page(browser, server, 1280)
    try:
        shares = page.evaluate("""
        () => [...document.querySelectorAll('table.grid thead th')]
          .filter((th) => th.querySelector('button'))
          .map((th) => {
            const a = th.getBoundingClientRect();
            const b = th.querySelector('button').getBoundingClientRect();
            return { text: th.textContent.trim(),
                     share: Math.round((b.width * b.height) /
                                       (a.width * a.height) * 1000) / 1000 };
          })
        """)
    finally:
        page.close()
    assert shares, "no sortable header cells were measured"
    thin = [s for s in shares if s["share"] < 0.95]
    assert not thin, (
        "a sorting control does not fill the header cell it appears to be: %s"
        % thin)
