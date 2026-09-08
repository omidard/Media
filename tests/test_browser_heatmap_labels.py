"""The clustergram's column labels stay inside their own frame.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
heatmap() sized the SVG as `hx + C*cellW + 10` and set the viewBox to match,
while every column label is anchored at the CENTRE of its column and, rotated
-45 degrees, projects len*cos(45) further right than its anchor. The last anchor
sits cellW/2 + 10 from the right edge, so the rightmost labels always ran past
the viewBox and were clipped by the SVG's own overflow.

"DSMZ MediaDive (n=3,148)" rendered as "DSMZ MediaDive (n=3,14" and "Classic and
standard fo... (n=297)" as "Classic an". The half that got amputated is the
count, so a reader could not tell how many media the last column holds -- a
denominator missing from the page's flagship figure. It happened in all three
groupings of the first heatmap (Food group lost "Dairy and Egg Product", "Baked
Produc", "Snack"; Category lost "biospecim") and on the co-occurrence matrix
("Dodecanoa", "Cob(I)a", "Ch" -- the last ambiguous against "Choline C5H14NO" on
the same axis).

Nothing about it depended on the viewport: `.viz svg` has no width:100%, so the
SVG renders at its natural width and the clip was identical at 390 and at 1440.
One of the three groupings drew a 510px frame inside an 1100px card, which is
what proves this is a layout bug and not a shortage of space.

The tooltip on each cell does spell out the full label, so a desktop reader has
a recovery path; a touch reader, a printout and a screenshot do not.
"""
import functools
import http.server
import os
import socket
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUSTER = os.path.join(REPO, "data", "cluster")

# Each label's own end position, transformed into screen space, against the SVG's
# client rect. Both edges matter: sizing the band above the grid to the label's
# LENGTH alone left the longest label's ascenders 3px above the frame.
CLIPPED = """() => {
  const out = [];
  for (const id of ['cg-svg', 'co-svg']) {
    const svg = document.getElementById(id);
    if (!svg) continue;
    const frame = svg.getBoundingClientRect();
    svg.querySelectorAll('text').forEach((t) => {
      if (!/rotate/.test(t.getAttribute('transform') || '')) return;
      const box = t.getBoundingClientRect();
      if (box.right > frame.right + 0.5 || box.top < frame.top - 0.5) {
        out.push(id + ': ' + t.textContent);
      }
    });
  }
  return out;
}"""


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


@pytest.mark.parametrize("width", [390, 768, 1024, 1280, 1440])
def test_no_column_label_is_clipped_by_its_own_frame(server, browser, width):
    for name in ("clustergram.json", "cooccurrence.json"):
        if not os.path.exists(os.path.join(CLUSTER, name)):
            pytest.skip("the precomputed clustering is not built in this tree")
    page = browser.new_page()
    bad = []
    try:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto("%s/patterns.html" % server, wait_until="load")
        page.wait_for_function(
            "document.querySelectorAll('#cg-svg text').length > 0", timeout=30000)
        page.wait_for_timeout(700)
        options = page.eval_on_selector_all(
            "#cg-group option", "os => os.map((o) => o.value)")
        # Every grouping, not only the default: the Food group and Category views
        # each lost their own rightmost labels, and one of them draws a frame far
        # narrower than the card it sits in.
        assert options, "the grouping control offers nothing to switch between"
        for opt in options:
            page.select_option("#cg-group", opt)
            page.wait_for_timeout(450)
            bad += ["view %s -> %s" % (opt, x) for x in page.evaluate(CLIPPED)]
    finally:
        page.close()
    assert not bad, (
        "%d column label(s) render outside the frame that is supposed to hold "
        "them, at %dpx: %r" % (len(bad), width, bad[:10]))
