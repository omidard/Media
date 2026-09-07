"""An oxygen regime nobody stated is not a regime.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
tools/curate_oxygen.py ends in two catch-all branches that return "facultative"
when the source says nothing about oxygen at all, and record why in
`oxygen_note`:

    "food substrate; O2 availability is a simulation condition, not a property
     of the food"                                                       8,124
    "no oxygen requirement specified; O2 available but not asserted"    3,802

11,926 of the 12,136 facultative records carry one of those two, which is 88% of
the library, in the field the site itself calls the single most consequential
bound in an FBA medium. All 8,125 food records, all 471 MediaDB (ISB) records and
all 701 FooDB records were in that state.

It was not merely unlabelled, it was actively misleading in the one place a
modeller would look:

* index.html offers "Facultative" and "Unknown (not recorded)" as separate filter
  states and gates the second on `oxygen !== null`. A modeller filtering for the
  records where they must decide EX_o2_e themselves got 439 and silently missed
  11,926 that need exactly the same decision.
* methods.html rendered "The oxygen regime is not recorded for 439 of 13,515
  media", understating the unknown set by a factor of 28.
* the record sheet's "The oxygen regime is unknown" caution fired for 439 records
  and not for the 11,926.
* the chip rendered "facultative" with the fixed title "Recorded as facultative",
  on the browse table, the families table, the compare grid and the record sheet,
  while the record's own `oxygen_note` explaining that nothing was recorded was
  rendered nowhere at all.

WHAT IS AND IS NOT ASSERTED HERE
--------------------------------
The published regime is now the RECORDED one, which is what the payload's own
column note has always said the field means. What the exported medium does with
EX_o2_e is a separate published fact, so the curated regime and the simulation
convention can never again be the same number.

The per-record files in data/media still carry the pipeline's `facultative`
there. Correcting the corpus needs a transform stage and a promotion, which is
tracked in tests/test_defects.py; until it lands, the browser applies the rule to
a per-record file using the vocabulary the payload publishes, and
`test_the_record_sheet_and_the_browse_table_agree` is the test that keeps those
two surfaces from disagreeing.

The 71 records whose regime is `aerobic` while carrying one of these notes are
deliberately untouched: those were set by a curator and kept a note from a run
predating the verification guard. Erasing them would destroy a real curation.
That stale note is its own defect and is in the ledger.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Measured on the shipped corpus.
N_DEFAULTED = 11926          # facultative, with a note saying nothing was stated
N_ABSENT_ALREADY = 439       # oxygen already null before this correction
N_STALE_NOTE_AEROBIC = 71    # aerobic with the same note: a curator set these


@pytest.fixture(scope="module")
def payload():
    path = os.path.join(REPO, "data", "web", "summary.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_unstated_vocabulary_matches_the_curation_script(payload):
    """The two note strings are the whole rule; they must not drift apart.

    The browser applies this rule to a per-record file and the builder applies it
    to the catalogue. If the vocabulary the payload publishes ever stops matching
    the strings curate_oxygen.py writes, the two surfaces disagree silently.
    """
    import web_payload

    notes = payload["oxygen_basis"]["unstated_notes"]
    assert set(notes) == set(web_payload.OXYGEN_NOT_STATED_NOTES)
    src = open(os.path.join(REPO, "tools", "curate_oxygen.py"), encoding="utf-8").read()
    for note in notes:
        assert note in src, (
            "the payload publishes %r as meaning 'no source stated a regime', and "
            "tools/curate_oxygen.py no longer writes it. One of the two moved."
            % note)


def test_a_defaulted_regime_is_published_as_unknown(payload, stream, is_full_corpus):
    """The corpus rule, and the published tally that must match it."""
    import web_payload

    defaulted = 0
    stale_aerobic = 0
    for _mid, rec in stream():
        note = (rec.get("oxygen_note") or "").strip()
        if note not in web_payload.OXYGEN_NOT_STATED_NOTES:
            continue
        if rec.get("oxygen") == "facultative":
            defaulted += 1
        elif rec.get("oxygen") == "aerobic":
            stale_aerobic += 1
    if is_full_corpus:
        assert defaulted == N_DEFAULTED
        assert stale_aerobic == N_STALE_NOTE_AEROBIC, (
            "the stale-note records moved; they are curator-set and must not be "
            "swept into the unknown bucket")
    assert payload["oxygen_basis"]["n_no_source_statement"] == defaulted


def test_the_published_unknown_count_is_the_whole_unknown_set(payload, is_full_corpus):
    """The number methods.html renders. It said 439; it is 12,365."""
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload against the shipped corpus")
    by_oxygen = payload["by_oxygen"]
    unknown = by_oxygen.get("None")
    assert unknown == N_DEFAULTED + N_ABSENT_ALREADY, (
        "the library-wide unknown tally is %r; a modeller filtering for the media "
        "whose EX_o2_e they must decide themselves has to be given all %d, not the "
        "%d that happened to be null already"
        % (unknown, N_DEFAULTED + N_ABSENT_ALREADY, N_ABSENT_ALREADY))
    assert by_oxygen.get("facultative") == 12136 - N_DEFAULTED, (
        "facultative must now mean a stated facultative regime")


def test_the_catalogue_publishes_the_simulation_default_separately(is_full_corpus):
    """The regime and the convention must never be the same number again."""
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload")
    path = os.path.join(REPO, "data", "web", "catalog.json")
    if not os.path.exists(path):
        pytest.skip("the browser payload is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    assert "oxygen_default_for_simulation" in cat["columns"], (
        "the exported medium opens EX_o2_e for these records and the catalogue "
        "does not say so anywhere, so the only way to see the convention is to "
        "read a component list")
    i_ox = cat["columns"].index("oxygen")
    i_df = cat["columns"].index("oxygen_default_for_simulation")
    dicts = cat["dicts"]
    dec = lambda col, v: None if v is None else dicts[col][v]      # noqa: E731
    both = [(dec("oxygen", r[i_ox]), dec("oxygen_default_for_simulation", r[i_df]))
            for r in cat["rows"]]
    split = [p for p in both if p[0] is None and p[1] == "facultative"]
    assert len(split) == N_DEFAULTED, (
        "expected %d records with no recorded regime and a facultative simulation "
        "default; found %d" % (N_DEFAULTED, len(split)))
    # And nothing may claim a recorded regime the record does not have.
    assert not [p for p in both if p[0] is not None and p[0] != p[1]]


def test_the_api_catalogue_agrees_with_the_browser_payload(is_full_corpus):
    """data/index.json is the documented endpoint; it must tell the same story."""
    if not is_full_corpus:
        pytest.skip("this asserts the shipped payload")
    path = os.path.join(REPO, "data", "index.json")
    if not os.path.exists(path):
        pytest.skip("data/index.json is not built in this tree")
    with open(path, encoding="utf-8") as fh:
        idx = json.load(fh)
    unknown = sum(1 for m in idx["media"] if m.get("oxygen") is None)
    defaulted = sum(1 for m in idx["media"]
                    if m.get("oxygen") is None
                    and m.get("oxygen_default_for_simulation") == "facultative")
    assert unknown == N_DEFAULTED + N_ABSENT_ALREADY
    assert defaulted == N_DEFAULTED
