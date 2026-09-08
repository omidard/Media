#!/usr/bin/env python3
"""The record publishes the regime a source stated, and the convention separately.

FINDINGS: OXY-01

THE DEFECT
----------
11,926 of 13,515 records carry `oxygen: "facultative"` while their own
`oxygen_note` says no source stated anything about oxygen. tools/curate_oxygen.py
ends in two catch-all branches that return "facultative" when the source is silent
and record WHY in the note, so 88% of the library was handed a curated-looking
regime nobody asserted, in the field the site itself calls the single most
consequential bound in an FBA medium.

The browser payloads were corrected first: tools/web_payload.oxygen_recorded()
applies the note vocabulary, so data/web/catalog.json, data/index.json and every
page have published `oxygen: null` and a separate
`oxygen_default_for_simulation` since that fix. The RECORD FILE did not follow,
and the record file is a documented public route: API.md points a reader at
`data/media/<id>.json`, pymediadb.iter_full_records() walks it, and the bulk JSONL
export is byte-for-byte that schema. API.md carried the gap as an admission
("the per-record files still carry the facultative default in `oxygen`"), which is
honest and is not a fix: a consumer reading the record still gets a confident label
where the answer is unknown.

WHAT THIS STAGE DOES
--------------------
It writes, onto every record, exactly the pair the payload builders already
compute from it:

    oxygen                          the regime a source or curator STATED, or null
    oxygen_default_for_simulation   the regime EX_o2_e was written from

For the 11,926 that is (null, "facultative"). For every other record it is
(regime, regime), which is what oxygen_recorded() has always returned for them, so
no published tally moves: by_oxygen stays {None: 12,365, anaerobic: 749,
facultative: 210, aerobic: 191} and oxygen_basis stays
{n_regime_recorded: 1,150, n_no_source_statement: 11,926,
n_absent_for_another_reason: 439}. The correction is to the record, and the
payloads that already told the truth keep telling the same truth.

`oxygen_note` is left exactly as it is. It is the evidence for the decision and
the vocabulary the whole rule is keyed on; deleting it would remove the reader's
ability to see why the field is null and would leave the rule unable to run twice.

WHY IT RUNS AFTER 52_web_payload
--------------------------------
Same reason 53_house_voice_dashes does: the payload 52 projects inside the chain
is a check on the corrected corpus, and the shipping payload is built by
`make derived` over the promoted corpus. The two must agree, and here they
provably do, because oxygen_recorded() reads the pair off a corrected record and
derives the identical pair from the note vocabulary on an uncorrected one.
test_the_two_branches_of_oxygen_recorded_agree_on_every_record asserts that over
the whole corpus rather than leaving it as a claim in this docstring.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not touch `aerobic`, the legacy boolean. On these records it is true,
which is the simulation default this stage is naming, so it does not contradict
the null regime. `aerobic` being a two-state field for a three-state fact is a
separate defect, on the ledger as unknown_oxygen_asserted_as_a_boolean.

It does not touch the 71 records whose regime is `aerobic` while carrying one of
the same two notes. Those were set by a curator and kept a note from a run that
predates the verification guard: the regime is a real curation and the note is the
leftover. Sweeping them into the unknown bucket would erase it. That is on the
ledger as oxygen_note_stale_on_curated_records.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

from stagelib import main_guard, stamp                            # noqa: E402
from web_payload import oxygen_recorded                           # noqa: E402

STAGE, VERSION = "54_oxygen_regime_absent_when_unstated", "1.0.0"

FIELD = "oxygen_default_for_simulation"


def _place_after_oxygen(rec: dict, value) -> None:
    """Keep the pair adjacent in the file a reader opens.

    A bare `rec[FIELD] = value` appends it after `components`, hundreds of lines
    below the field it qualifies, where nobody scrolling a record would meet the
    two together.
    """
    if FIELD in rec:
        rec[FIELD] = value
        return
    rebuilt = {}
    for k, v in rec.items():
        rebuilt[k] = v
        if k == "oxygen":
            rebuilt[FIELD] = value
    if FIELD not in rebuilt:                     # no `oxygen` key at all
        rebuilt[FIELD] = value
    rec.clear()
    rec.update(rebuilt)


def transform(rec: dict, rep) -> bool:
    """The pair, taken from the one function that defines it.

    web_payload.oxygen_recorded() is called rather than the note rule being
    written out a second time here. Two reasons, and the first was measured: it
    reads the pair back off a record this stage has already corrected, so a
    re-run is a fixed point. Re-deriving from the note instead found `oxygen`
    null, concluded nothing was defaulted, and rewrote
    oxygen_default_for_simulation from "facultative" to null on 85 of the 165
    sample records, which the chain's idempotence check caught. The second reason
    is the point of the stage: the record and the catalogue must carry the same
    pair, and one definition cannot drift from itself.
    """
    regime, default = oxygen_recorded(rec)

    if regime is None and default is not None:
        rep.count("regime_no_source_stated_published_as_null")
    elif regime is None:
        rep.count("regime_absent_for_another_reason")
    else:
        rep.count("regime_a_source_or_curator_stated")

    if rec.get("oxygen") == regime and FIELD in rec and rec[FIELD] == default:
        return False                             # already separated
    rec["oxygen"] = regime
    _place_after_oxygen(rec, default)
    stamp(rec, STAGE, VERSION, ["oxygen", FIELD])
    return True


def finalize(rep):
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.count("records_seen", 0, rep.n_in)
    rep.assert_eq(
        "every_record_is_in_exactly_one_of_the_three_states",
        got("regime_no_source_stated_published_as_null")
        + got("regime_absent_for_another_reason")
        + got("regime_a_source_or_curator_stated"),
        rep.n_in)
    rep.unresolved(
        "aerobic_is_still_a_two_state_field_for_a_three_state_fact", rep.n_in, rep.n_in,
        "`aerobic` is true on 11,918 of the records this stage nulls, which is the "
        "simulation default it names rather than a contradiction of it, and null on "
        "the 439 that were already absent. It cannot express 'unknown' for the rest "
        "without a separate decision, which is on the ledger as "
        "unknown_oxygen_asserted_as_a_boolean.")
    rep.unresolved(
        "seventy_one_curated_aerobic_records_keep_a_no_statement_note", 71, rep.n_in,
        "those regimes were set by a curator and the note is a leftover from a run "
        "predating the verification guard. Nulling them would erase a real "
        "curation; the note is the defect and it is on the ledger as "
        "oxygen_note_stale_on_curated_records.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize, inputs=[])
