"""The published claims must be the measured ones.

BLOCKERS (a) (b) (g) (h) of the pre-push verification. Every failure this file
catches is the same defect wearing a different hat: a shipped artifact saying
more than its data supports.

  (a) the site's opening sentence said "every one mapped to a BiGG exchange"
      while 1,582 of 665,582 components are not, and the README said every
      component carries cross-references while 8,957 carry none;
  (b) README called 471 all-rights-reserved records "redistributed by
      permission" while LICENSE, NOTICE and tools/licenses.tsv all say
      permission has NOT been obtained;
  (g) pct_covered_observed read as coverage and was 100.0 on 95.2% of records;
  (h) half the library is degenerate as a model input and only 1,497 records
      said anything about it.

These are text-and-payload checks. They are deliberately cheap: they read the
shipped payload and the shipped documents, not the 1.4 GB corpus, so they run
in CI on every push rather than only when someone remembers.
"""
import json
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "data", "web")


def _read(name):
    path = os.path.join(REPO, name)
    if not os.path.exists(path):
        pytest.skip("%s is not present in this tree" % name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def summary():
    path = os.path.join(WEB, "summary.json")
    if not os.path.exists(path):
        pytest.skip("data/web/summary.json not built")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- (a) mapping
def test_exchange_resolution_partitions_the_components(summary):
    """The FOUR states must account for every component.

    A fourth, unnamed state is how "every component is mapped" survived: the
    exceptions had nowhere to be counted. This test used to assert a three-way
    partition, and the fourth state it warned about was real and unnamed the whole
    time — 11,380 components carrying an id of the EX_<met>_e shape that names no
    BiGG reaction, counted as successes because the bucket was decided by the
    string's shape. It is now counted; see tests/test_bigg_exchange_partition.py
    for the claim itself, checked against BiGG's own namespace.
    """
    xr = summary["exchange_resolution"]
    assert (xr["n_bigg_exchange"] + xr["n_bigg_shaped_no_such_exchange"]
            + xr["n_nonbigg_fallback"] + xr["n_no_exchange"]
            == xr["of"] == summary["component_totals"]["n_components"])


def test_the_payload_admits_the_components_that_are_not_bigg_mapped(summary):
    xr = summary["exchange_resolution"]
    assert xr["n_nonbigg_fallback"] > 0 and xr["n_no_exchange"] > 0, (
        "if these are ever genuinely zero, delete this test and the hedged "
        "wording with it — do not weaken the wording while they are not")
    assert xr["n_bigg_shaped_no_such_exchange"] > 0, (
        "the state that was counted as a success must stay visible while it is "
        "non-empty")
    assert xr["n_bigg_exchange"] < xr["of"]


def test_cross_reference_coverage_is_stated_not_assumed(summary):
    cr = summary["cross_references"]
    assert (cr["n_components_with_a_cross_reference"] + cr["n_components_with_none"]
            == cr["of"])
    assert cr["n_components_with_none"] > 0


#: Every document a reader can reach, not the four that were remembered. DESIGN.md:97
#: still said "Every component *also* carries cross-references" after index.html,
#: methods.html, README.md and openapi.yaml had all been corrected, because the sweep
#: was done by hand and this copy was missed. NOTICE, PROVENANCE.md, the deploy-surface
#: manifest, the browser's own JS and tools/licenses.tsv are in the list for the same
#: reason: whichever file is left out is the one that keeps the claim.
CLAIM_DOCS = ["README.md", "DESIGN.md", "openapi.yaml", "index.html", "methods.html",
              "API.md", "NOTICE", "LICENSE", "PROVENANCE.md", "compare.html",
              "families.html", "patterns.html", "assets/media.js",
              "tools/licenses.tsv", "docs/DEPLOY_SURFACE.tsv",
              "client/README.md", "client/pymediadb/__init__.py"]


@pytest.mark.parametrize("doc", CLAIM_DOCS)
def test_no_document_claims_every_component_is_bigg_mapped(doc):
    """The exact sentence, and its close paraphrases, must not come back."""
    text = _read(doc)
    banned = [
        r"every component (?:is )?mapped to a (?:standard )?BiGG",
        r"every one mapped to a BiGG",
        r"components,? every one mapped",
        r"every component (?:is )?mapped to a standard BiGG exchange",
        r"(?<!not )every component is mapped into",
        r"(?<!not )all components (?:are )?mapped to",
    ]
    for pattern in banned:
        for m in re.finditer(pattern, text, re.I):
            line = text[:m.start()].count("\n") + 1
            # A sentence that reports the old claim in order to correct it is
            # allowed; one that makes it is not. The corrections all sit next to
            # the word "said", "used to", "was true of" or "claimed".
            window = text[max(0, m.start() - 200):m.end() + 200].lower()
            if any(k in window for k in ("said", "used to", "was true of",
                                         "claimed", "earlier release", "banned",
                                         "must not", "until 2026", "sentence read")):
                continue
            raise AssertionError(
                "%s:%d makes the claim the data does not support: %r"
                % (doc, line, m.group(0)))


#: The claim's other half. It was corrected in index.html, methods.html, README.md and
#: openapi.yaml on 2026-09-06 and survived in DESIGN.md:97 — plus, in the arithmetic
#: form "N distinct blocks stood in for 665,582 copies", in openapi.yaml, assets/media.js,
#: the client library and the API manifest's generator. 8,957 of 665,582 carry none.
#: `(?<!not )` matters: the corrected wording is "Not every component carries a
#: cross-reference", and a sweep that flags its own fix teaches people to delete the
#: sweep.
_XREF_CLAIMS = [
    r"(?<!not )every component (?:\*?also\*? )?carries cross-references",
    r"(?<!not )every component (?:\*?also\*? )?carries a cross-reference",
    r"(?<!not )each component (?:\*?also\*? )?carries cross-references",
    r"(?<!not )all components carry cross-references",
    r"(?<!not )every component (?:has|carries) (?:an? )?(?:xref|cross-ref)",
    # the arithmetic form: a per-component count asserted over the whole corpus
    r"stood in for 665,582 copies",
    r"(?:written|repeated) (?:into|across) 665,582 components",
    r"written out 665,582 times",
]


@pytest.mark.parametrize("doc", CLAIM_DOCS)
def test_no_document_claims_every_component_carries_cross_references(doc, summary):
    """8,957 of 665,582 components carry none, and the documents must say so.

    The measured denominator comes from the payload, so this test cannot pass by
    agreeing with a number that is itself stale.
    """
    cr = summary["cross_references"]
    assert cr["n_components_with_none"] > 0, (
        "if every component genuinely carries one, delete this test with the hedged "
        "wording — do not weaken the wording while 8,957 do not")
    text = _read(doc)
    for pattern in _XREF_CLAIMS:
        for m in re.finditer(pattern, text, re.I):
            line = text[:m.start()].count("\n") + 1
            window = text[max(0, m.start() - 240):m.end() + 240].lower()
            if any(k in window for k in ("said", "used to", "was true of", "claimed",
                                         "earlier release", "banned", "must not",
                                         "until 2026")):
                continue
            raise AssertionError(
                "%s:%d claims every component carries a cross-reference; %s of %s "
                "carry none" % (doc, line, "{:,}".format(cr["n_components_with_none"]),
                                "{:,}".format(cr["of"])))


@pytest.mark.parametrize("doc", CLAIM_DOCS)
def test_a_document_stating_the_xref_share_states_the_measured_one(doc, summary):
    """Any document that gives the share must give the payload's number.

    DESIGN.md was corrected by hand once; this is what makes the correction stick.
    """
    cr = summary["cross_references"]
    text = _read(doc)
    n_with = "{:,}".format(cr["n_components_with_a_cross_reference"])
    n_none = "{:,}".format(cr["n_components_with_none"])
    if "cross-reference" not in text.lower() and "xref" not in text.lower():
        pytest.skip("%s says nothing about cross-references" % doc)
    if n_with not in text and n_none not in text:
        pytest.skip("%s states no cross-reference share" % doc)
    assert n_none in text, (
        "%s gives the cross-reference share without the exceptions: %s of %s carry "
        "none, and that is the half a reader needs" % (doc, n_none, "{:,}".format(cr["of"])))


# -------------------------------------------------------------- (b) licences
def test_readme_does_not_claim_permission_it_does_not_have():
    """LICENSE:73 and NOTICE both say permission has NOT been obtained."""
    readme = _read("README.md")
    assert "redistributed by permission" not in readme
    assert "redistribution permission has not been obtained" in readme.lower(), (
        "the README must state the MediaDB/ISB position in the same words as "
        "LICENSE and NOTICE, in the one place a reader looks first")


def test_every_document_names_the_same_data_licence():
    """One licence, stated identically wherever it is stated.

    The defect this replaces: README said "Data: CC-BY-4.0" while LICENSE and
    NOTICE said the MediaDB/ISB records carry no reuse grant at all. Four
    documents, three positions. The data now carries ONE licence, set at the most
    restrictive upstream input, so agreement is checkable by a string.
    """
    for name in ("LICENSE", "README.md", "API.md", "index.html", "methods.html",
                 "client/README.md", "openapi.yaml"):
        text = _read(name)
        assert re.search(r"CC[ -]BY[ -]NC[ -]?4\.0", text), (
            "%s does not name the data licence (CC BY-NC 4.0)" % name)
    for name in ("README.md", "LICENSE", "API.md"):
        text = _read(name)
        assert not re.search(r"no blanket data licence|not under a single licence",
                             text, re.I), (
            "%s still describes a per-source schedule" % name)


def test_the_upstream_position_on_mediadb_isb_is_still_stated():
    """One dataset licence does not erase an obligation.

    MediaDB (ISB) grants no reuse right upstream. The compilation licence is set
    at that constraint rather than papering over it, and the documents that owe
    the attribution must still say so.
    """
    for name in ("LICENSE", "NOTICE", "README.md"):
        text = _read(name)
        assert re.search(r"permission (has|had) not been obtained", text, re.I) \
            or re.search(r"NOT been obtained", text) \
            or re.search(r"grants no reuse right", text, re.I), (
                "%s no longer states the MediaDB/ISB position" % name)


# ------------------------------------------------------------- (g) the rename
def test_the_renamed_field_is_gone_from_every_export_builder():
    """Locked at the generator, not at the built file.

    A test that reads data/index.json passes or fails on whether someone
    remembered to run `make derived`; a test that reads the builder fails the
    moment the old name comes back, whatever the build state.
    """
    for builder in ("build_index.py", "tools/build_coverage_index.py",
                    "tools/build_api_exports.py", "tools/stages/remap_components.py"):
        src = _read(builder)
        assert "pct_sourced_components_with_bigg_id" in src, (
            "%s does not emit the renamed field" % builder)
        # The old name may only appear as a read-side fallback or in prose that
        # explains the rename — never as a key this builder writes.
        for m in re.finditer(r'"pct_covered_observed"\s*:', src):
            line = src[:m.start()].count("\n") + 1
            raise AssertionError(
                "%s:%d still writes the old key. It is a coverage claim its value "
                "does not support and must not ship beside the new one."
                % (builder, line))


def test_the_built_catalog_carries_the_rename_when_it_has_been_rebuilt():
    index_path = os.path.join(REPO, "data", "index.json")
    if not os.path.exists(index_path):
        pytest.skip("data/index.json not built")
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    if "field_renames" not in index:
        pytest.skip("data/index.json predates the rename; run `make derived`")
    row = index["media"][0]
    assert "pct_sourced_components_with_bigg_id" in row
    assert "pct_covered_observed" not in row


def test_the_rename_is_declared_to_consumers(summary):
    renames = {r["old"]: r for r in summary["field_renames"]}
    assert "pct_covered_observed" in renames
    entry = renames["pct_covered_observed"]
    assert entry["new"] == "pct_sourced_components_with_bigg_id"
    measured = entry["measured"]
    # The reason for the rename is itself a measurement, not an adjective.
    assert measured["n_records_where_the_value_is_100.0"] > 0.9 * measured["of"]


def test_methods_page_documents_the_rename():
    methods = _read("methods.html")
    assert "pct_sourced_components_with_bigg_id" in methods
    assert "pct_covered_observed" in methods, (
        "a consumer looking for the old name must find it, with what happened")


# -------------------------------------------------- (h) model-input degeneracy
def test_model_input_degeneracy_is_published(summary):
    dg = summary["model_input_degeneracy"]
    assert dg["n_media_sharing_a_model_input"] + dg["n_media_with_a_unique_model_input"] \
        == dg["of"]
    assert dg["n_media_sharing_a_model_input"] > 0
    assert dg["largest_group"] >= 2


def test_the_twin_groups_ship_and_match_the_aggregate():
    path = os.path.join(WEB, "twins.json")
    if not os.path.exists(path):
        pytest.skip("data/web/twins.json not built")
    with open(path, encoding="utf-8") as fh:
        twins = json.load(fh)
    members = [m for g in twins["groups"] for m in g]
    assert len(members) == len(set(members)), "a medium is in two groups at once"
    assert len(members) == twins["n_media_sharing_a_model_input"]
    assert all(len(g) >= 2 for g in twins["groups"])
    assert max(len(g) for g in twins["groups"]) == twins["largest_group"]


def test_the_catalog_carries_the_per_record_twin_count():
    path = os.path.join(WEB, "catalog.json")
    if not os.path.exists(path):
        pytest.skip("data/web/catalog.json not built")
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    i = cat["columns"].index("model_input_twins")
    values = [r[i] for r in cat["rows"]]
    assert all(v is not None for v in values), "a null twin count is not an answer"
    shared = sum(1 for v in values if v > 0)
    assert shared == cat["model_input_degeneracy"]["n_media_sharing_a_model_input"]


def test_methods_page_explains_the_degeneracy_once():
    methods = _read("methods.html")
    assert 'id="degeneracy"' in methods
    assert "model input" in methods.lower()


# ----------------------------------------------- the general class: adjectives
def test_the_limits_list_carries_measurements_not_adjectives():
    """Every limit on the methods page must be filled from the payload.

    The static text is a placeholder; the JS replaces it with a count and a
    denominator. A limit that ships only the adjective is the defect.
    """
    methods = _read("methods.html")
    for lid in ("limit-name", "limit-derived", "limit-bounds", "limit-oxygen",
                "limit-degeneracy", "limit-exchange", "limit-xref"):
        assert 'id="%s"' % lid in methods, "%s is missing from the limits list" % lid
        assert "$('%s')" % lid in methods, (
            "%s ships its placeholder adjective and is never given a "
            "measurement" % lid)


def test_share_never_rounds_a_partial_share_up_to_one_hundred():
    """664,000 of 665,582 is 99.76%; toFixed(0) printed it as '100%'."""
    js = _read("assets/media.js")
    assert "if (p >= 100) return '100%';" in js
    assert "while (d < 4 && Number(p.toFixed(d)) >= 100) d++;" in js


# ------------------------------- the release that was documented before it existed
# The size fix moved 172.8 MiB of bulk exports out of the published site and pointed
# every reader at a `data-v1` GitHub Release. The release was never created: the tag
# URL, both asset URLs and the releases API answered 404 or []. That is the same
# defect as (a) and (b) — a shipped document asserting something the world does not
# support — and it was published at a live API endpoint. The repository now declares
# the status in one place, and these tests keep every document, the payload and the
# client agreeing with it.

RELEASE_DOC_FILES = ["README.md", "API.md", "openapi.yaml", "Makefile",
                     "client/pymediadb/__init__.py"]
_NOT_YET_PUBLISHED = ("not been created", "not created", "not yet",
                      "planned, not", "does not exist", "planned")


def _release_status():
    src = _read("tools/build_api_exports.py")
    m = re.search(r'^RELEASE_STATUS\s*=\s*"(\w+)"', src, re.M)
    assert m, "tools/build_api_exports.py must declare RELEASE_STATUS"
    assert m.group(1) in ("planned", "published")
    return m.group(1)


@pytest.mark.parametrize("doc", RELEASE_DOC_FILES)
def test_no_document_sends_a_reader_to_a_release_that_does_not_exist(doc):
    """While the release is `planned`, naming it obliges you to say so and to give
    the command that works instead."""
    if _release_status() == "published":
        pytest.skip("the release is published; the 404 this guards against is gone")
    text = _read(doc)
    if "data-v1" not in text:
        return
    low = text.lower()
    assert any(p in low for p in _NOT_YET_PUBLISHED), (
        "%s names the data-v1 release but never says it has not been created — a "
        "reader following it gets a 404" % doc)
    assert "release-assets" in text, (
        "%s names the data-v1 release but not `make release-assets`, which is the "
        "only way to get those files today" % doc)


def test_the_published_manifest_declares_the_release_status():
    """The machine-readable half: a client must be able to ask, not assume."""
    path = os.path.join(REPO, "data", "api", "manifest.json")
    if not os.path.exists(path):
        pytest.skip("data/api/manifest.json not built")
    with open(path, encoding="utf-8") as fh:
        bulk = json.load(fh).get("bulk_download") or {}
    assert bulk.get("status") == _release_status(), (
        "data/api/manifest.json advertises bulk_download.status=%r while "
        "tools/build_api_exports.py declares %r — run `make derived`"
        % (bulk.get("status"), _release_status()))
    if bulk["status"] != "published":
        assert "make release-assets" in json.dumps(bulk), (
            "the manifest tells a client the download is unavailable without "
            "telling it how to build the files")


def test_the_client_reads_the_status_instead_of_assuming_the_release_exists():
    src = _read("client/pymediadb/__init__.py")
    assert "bulk_download_status" in src
    assert re.search(r'if\s+str\(bulk\.get\("status"\).*!=\s*"published"', src), (
        "_release_shards must return nothing while the release is unpublished")
    body = src[src.index("def iter_full_records"):src.index("def bulk_download_status")]
    assert "except Exception" in body and "self.catalog()" in body, (
        "iter_full_records must catch a failing shard download and finish from the "
        "per-medium endpoint — a documented fallback that raises is worse than none")


# ------------------------------------------------- the register of the payload
# The shipped payloads are read by strangers, and a JSON string is page copy the
# moment a page renders it. The subject of every string in them is the DATA: what
# a record is, what a field means, what it cannot support. Not the pipeline, not
# a build, not a verification pass, not a correction. These assertions are the
# regression guard for that rule.

PAYLOADS = [os.path.join("data", "web", n) for n in
            ("catalog.json", "summary.json", "compounds.json", "families.json",
             "tombstones.json", "twins.json")] + \
           [os.path.join("data", "index.json"), os.path.join("data", "stats.json")]

# Keys whose subject was the build system or our own record-keeping.
RETIRED_KEYS = ("stamp_policy", "count_authority", "why_no_denominator",
                "assessed_denominator")

# Phrases from the self-reporting register.
RETIRED_PHRASES = ("verification pass", "cannot honestly", "was corrected from",
                   "counted by tools/", "counted by build_index",
                   "rather than rounding", "instead of returning",
                   "rather than hides", "for form")


@pytest.mark.parametrize("rel", PAYLOADS)
def test_no_payload_reports_on_the_project(rel):
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        pytest.skip("%s is not built in this tree" % rel)
    with open(path, encoding="utf-8") as fh:
        blob = fh.read()
    for key in RETIRED_KEYS:
        assert '"%s"' % key not in blob, (
            "%s ships %r. Build provenance and self-assessment are not user "
            "documentation; remove it at the generator." % (rel, key))
    for phrase in RETIRED_PHRASES:
        assert phrase not in blob, (
            "%s ships the phrase %r. Every string in a payload describes the "
            "data, never the project." % (rel, phrase))


def test_the_rename_resolves_without_explaining_itself():
    """A client holding the old key needs the mapping, not the reasoning."""
    path = os.path.join(REPO, "data", "index.json")
    if not os.path.exists(path):
        pytest.skip("data/index.json not built")
    with open(path, encoding="utf-8") as fh:
        renames = json.load(fh).get("field_renames") or []
    assert renames, "the rename map must ship so the old key resolves"
    for r in renames:
        assert r.get("old") and r.get("new") and r.get("measures")
        assert "why" not in r, (
            "field_renames[].why explained our own naming mistake to the reader")


def test_a_withdrawn_identifier_resolves_to_a_code_not_to_a_case_report():
    path = os.path.join(REPO, "data", "web", "tombstones.json")
    if not os.path.exists(path):
        pytest.skip("data/web/tombstones.json not built")
    with open(path, encoding="utf-8") as fh:
        tomb = json.load(fh)
    codes = {c["code"] for c in tomb["reason_codes"]}
    assert codes, "the vocabulary must ship with the codes that reference it"
    assert sum(c["n"] for c in tomb["reason_codes"]) == tomb["n_withdrawn"]
    for c in tomb["reason_codes"]:
        assert c["of"] == tomb["n_withdrawn"], "a count without its denominator"
        assert c["label"] and c["definition"]
    for mid, rec in tomb["records"].items():
        assert set(rec) == {"name", "reason_code"}, (
            "%s carries %s; a tombstone is a state and a class-level reason"
            % (mid, sorted(set(rec) - {"name", "reason_code"})))
        assert rec["reason_code"] in codes
    blob = json.dumps(tomb)
    for banned in ("REJECTED", "auto-extraction artifact", "workflow:",
                   "This paper does NOT", "was fetched and read"):
        assert banned not in blob, (
            "the per-record review prose (%r) is back in the shipped payload; it "
            "belongs in tools/curation/tombstone_reason_codes.tsv" % banned)
