"""The reference tables lose nothing, and the corpus and the table stay in step.

FINDINGS: SIZE-01

Stage 60_dedupe_references took 631 MiB out of the published site by holding each
repeated cross-reference block and each repeated sentence ONCE in data/refs.json
instead of writing them into every one of 665,582 components. That is only a
saving if it is not a loss, and the difference between the two is a join that
still resolves. These tests are the standing proof:

  * every key the corpus references exists in the table, and every table entry is
    referenced (an orphan means the table was built from a different corpus);
  * no component carries both the key and the inline value it replaced;
  * resolving a record reproduces the pre-deduplication shape, field for field;
  * the site's own reader contract holds: an absent xref_id means "no
    cross-references", and is never confused with "the table did not load".
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import refs as R                                            # noqa: E402
import verify_reference_tables as V                         # noqa: E402

MEDIA = os.path.join(REPO, "data", "media")
REFS = os.path.join(REPO, "data", R.REFS_FILENAME)


@pytest.fixture(scope="module")
def tables():
    if not os.path.exists(REFS):
        pytest.skip("data/refs.json is not present in this checkout")
    return R.load_refs(REFS)


@pytest.fixture(scope="module")
def verdict():
    if not os.path.exists(REFS) or not os.path.isdir(MEDIA):
        pytest.skip("corpus or reference table absent")
    return V.verify(MEDIA, REFS)


def test_the_table_declares_its_schema_and_its_join(tables):
    assert tables["schema"] == R.SCHEMA
    assert set(tables["joins"]) == {
        "components[].xref_id",
        "components[].xref_note_id",
        "components[].mapping_note_id",
    }
    assert tables["n_xrefs"] == len(tables["xrefs"])
    assert tables["n_notes"] == len(tables["notes"])


def test_every_key_the_corpus_references_resolves(verdict):
    assert verdict["unresolved_xref_ids"] == []
    assert verdict["unresolved_note_ids"] == []


def test_no_table_entry_is_unreferenced(verdict):
    """An orphan means data/refs.json and data/media came from different runs."""
    assert verdict["n_orphan_xref_keys"] == 0
    assert verdict["n_orphan_note_keys"] == 0


def test_no_component_is_half_migrated(verdict):
    """A component holding both the key and the inline value it replaced is the
    state in which the two can silently disagree."""
    assert verdict["components_still_inline"] == []


def test_the_table_is_not_empty(verdict):
    assert verdict["tables_non_trivial"]
    assert verdict["n_xref_keys"] > 1000
    assert verdict["n_note_keys"] > 10


def test_note_ids_are_content_addressed(tables):
    """The key IS the hash of the sentence, so a rebuild cannot renumber them."""
    for key, text in tables["notes"].items():
        assert R.note_id(text) == key, key


def test_resolving_reproduces_the_flat_record(tables):
    """The claim the whole stage rests on, on a real slice of the corpus.

    resolve_component must put back `xref`, `target_xref`, the two notes and the
    quantity copies, and must add nothing else.
    """
    ids = sorted(f for f in os.listdir(MEDIA) if f.endswith(".json"))[:60]
    n = 0
    for fn in ids:
        with open(os.path.join(MEDIA, fn), encoding="utf-8") as fh:
            rec = json.load(fh)
        for c in rec.get("components") or []:
            n += 1
            back = R.resolve_component(c, tables, flat=True)
            assert "xref" in back and "target_xref" in back
            assert back["xref"] == back["target_xref"]
            if c.get("xref_id") is None:
                assert back["xref"] == {}
            else:
                assert back["xref"] == tables["xrefs"][c["xref_id"]]
            if c.get("mapping_note_id"):
                assert back["mapping_note"] == tables["notes"][c["mapping_note_id"]]
            else:
                assert "mapping_note" not in back
            if c.get("xref_note_id"):
                assert back["target_xref_note"] == tables["notes"][c["xref_note_id"]]
            else:
                assert "target_xref_note" not in back
            q = c.get("quantity") or {}
            if "quantity" in c:
                assert back["quantity_basis"] == q.get("basis")
    assert n > 1000, "the slice must be big enough to mean something"


def test_a_missing_key_is_fatal_not_blank(tables):
    """A builder that substituted {} for an unresolvable key would ship a
    components table with every cross-reference column empty and no error."""
    with pytest.raises(KeyError):
        R.component_xref({"name": "x", "xref_id": "not-a-real-key"}, tables)
    with pytest.raises(KeyError):
        R.component_note({"name": "x", "mapping_note_id": "nZZZZZZ"}, tables)


def test_an_absent_key_means_none_not_missing(tables):
    """Absent is its own state and resolves to empty, never to an error."""
    assert R.component_xref({"name": "x"}, tables) == {}
    assert R.component_note({"name": "x"}, tables) is None


def test_dedupe_refuses_a_quantity_copy_that_is_not_a_copy():
    """The stage drops quantity_basis only where it IS quantity.basis. A record
    where they disagree carries information and must stop the build."""
    c = {"name": "x", "quantity": {"basis": "per_litre_medium"},
         "quantity_basis": "per_100g_food"}
    with pytest.raises(ValueError):
        R.dedupe_component(c, {})


def test_amount_basis_is_never_dropped():
    """It labels amount_mmol_per_100g, not quantity.value. Its agreement with
    quantity.basis is a property of this corpus, not of the schema."""
    assert "amount_basis" not in R.DERIVED_FROM_QUANTITY
    c = {"name": "x", "quantity": {"basis": "per_100g_food"},
         "amount_basis": "per_100g_food", "amount_mmol_per_100g": 1.0}
    R.dedupe_component(c, {})
    assert c["amount_basis"] == "per_100g_food"
