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
    """BiGG + non-BiGG fallback + none must account for every component.

    A fourth, unnamed state is how "every component is mapped" survived: the
    exceptions had nowhere to be counted.
    """
    xr = summary["exchange_resolution"]
    assert (xr["n_bigg_exchange"] + xr["n_nonbigg_fallback"] + xr["n_no_exchange"]
            == xr["of"] == summary["component_totals"]["n_components"])


def test_the_payload_admits_the_components_that_are_not_bigg_mapped(summary):
    xr = summary["exchange_resolution"]
    assert xr["n_nonbigg_fallback"] > 0 and xr["n_no_exchange"] > 0, (
        "if these are ever genuinely zero, delete this test and the hedged "
        "wording with it — do not weaken the wording while they are not")
    assert xr["n_bigg_exchange"] < xr["of"]


def test_cross_reference_coverage_is_stated_not_assumed(summary):
    cr = summary["cross_references"]
    assert (cr["n_components_with_a_cross_reference"] + cr["n_components_with_none"]
            == cr["of"])
    assert cr["n_components_with_none"] > 0


@pytest.mark.parametrize("doc", ["README.md", "DESIGN.md", "openapi.yaml",
                                 "index.html", "methods.html", "API.md",
                                 "client/README.md",
                                 "client/pymediadb/__init__.py"])
def test_no_document_claims_every_component_is_bigg_mapped(doc):
    """The exact sentence, and its close paraphrases, must not come back."""
    text = _read(doc)
    banned = [
        r"every component (?:is )?mapped to a (?:standard )?BiGG",
        r"every one mapped to a BiGG",
        r"components,? every one mapped",
        r"every component (?:is )?mapped to a standard BiGG exchange",
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
                                         "must not")):
                continue
            raise AssertionError(
                "%s:%d makes the claim the data does not support: %r"
                % (doc, line, m.group(0)))


# -------------------------------------------------------------- (b) licences
def test_readme_does_not_claim_permission_it_does_not_have():
    """LICENSE:73 and NOTICE both say permission has NOT been obtained."""
    readme = _read("README.md")
    assert "redistributed by permission" not in readme
    assert "redistribution permission has not been obtained" in readme.lower(), (
        "the README must state the MediaDB/ISB position in the same words as "
        "LICENSE and NOTICE, in the one place a reader looks first")


def test_the_licence_documents_agree_with_each_other():
    lic, notice, readme = _read("LICENSE"), _read("NOTICE"), _read("README.md")
    tsv = _read("tools/licenses.tsv")
    for text, name in ((lic, "LICENSE"), (notice, "NOTICE"), (readme, "README.md"),
                       (tsv, "tools/licenses.tsv")):
        assert re.search(r"permission (has|had) not been obtained", text, re.I) \
            or re.search(r"NOT been obtained", text), (
                "%s does not state that MediaDB/ISB redistribution permission is "
                "absent; the four documents must not disagree about a licence" % name)


def test_readme_asserts_no_blanket_data_licence():
    readme = _read("README.md")
    assert "no blanket data licence" in readme.lower(), (
        "README once said 'Data: CC-BY-4.0', which grants commercial use over "
        "1,189 records whose upstream sources grant no such right")


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
                "limit-licence", "limit-degeneracy", "limit-exchange",
                "limit-xref"):
        assert 'id="%s"' % lid in methods, "%s is missing from the limits list" % lid
        assert "$('%s')" % lid in methods, (
            "%s ships its placeholder adjective and is never given a "
            "measurement" % lid)


def test_share_never_rounds_a_partial_share_up_to_one_hundred():
    """664,000 of 665,582 is 99.76%; toFixed(0) printed it as '100%'."""
    js = _read("assets/media.js")
    assert "if (p >= 100) return '100%';" in js
    assert "while (d < 4 && Number(p.toFixed(d)) >= 100) d++;" in js
