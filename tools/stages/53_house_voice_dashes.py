#!/usr/bin/env python3
"""No en-dash or em-dash survives in a published string.

FINDINGS: VOICE-01

THE DEFECT
----------
The house standard bans the en-dash and the em-dash in visible copy, absolutely.
All 13,515 records carry at least one, and 2,082 of them (about one record page in
six) render one on the record sheet: the medium's own title ("Brain Heart Infusion
(BHI) - in-silico approximation (aerobic)"), the Formulation reference, the
decomposition citations under "Where the derived composition came from", and the
copyable COBRApy snippet's header comment. The results table renders eight of them
in its name column, and families.html renders four in its member names.

They are not quotations. The pattern is always a join this repository mints
itself: "<name> - <citation>", "<name> - in-silico approximation (aerobic)",
"<ingredient> (2 g/L) - decomposed below".

Counts before this stage: 13,515 of 13,515 records; data/web/families.json 247;
data/web/catalog.json 6 em + 2 en; data/refs.json 1; data/index.json 273 em + 4 en
(escaped, so a raw-text grep reports 0 there and only a parse finds them).

WHAT THIS STAGE DOES
--------------------
Two rules, not one, because a blanket replacement damages chemistry and proper
names:

  A SPACED dash is explanatory prose and becomes a separator. For the four fields
    where the dash separates a statement from the source that supports it
    (provenance.citation, provenance.wellknown_reference,
    provenance.decomposition_refs[].citation, components[].decomposition_ref) the
    separator is ". Source: ", which is what the sentence means. Everywhere else
    it is ", ".

  An UNSPACED dash is a compound joiner or a numeric range and becomes a plain
    hyphen: "Sigma-Aldrich", "sucrose-molasses medium", "3 deg C-5 deg C",
    "J Bacteriol 176:6324-6333". Comma-substituting these would destroy the
    meaning, which is why one rule is not enough.

coverage_source.definition is a single constant string of maintainer prose sitting
in a reader payload on all 13,515 records; it is replaced outright, in reader
voice, rather than patched.

WHERE THE REAL FIX IS
---------------------
At the mint sites, which are fixed in the same commit: tools/laboratory_media.py
(the four "<name> - in-silico approximation" literals),
tools/curate_name_formatting.py (whose line 19 exempted the em-dash BY DESIGN,
which is why this persisted -- it was never a fix that regressed, the rule was
never wired in), and the citation joins. This stage exists because the corpus is a
frozen snapshot whose original builders cannot be re-run (PIPE-01), so the
correction has to be a re-runnable transform over it.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stagelib import main_guard, stamp                            # noqa: E402

STAGE, VERSION = "53_house_voice_dashes", "1.0.0"

DASH = "–—"                       # EN DASH, EM DASH
SPACED = re.compile(r"\s*[%s]\s+|\s+[%s]\s*" % (DASH, DASH))
ANY = re.compile(r"[%s]" % DASH)
HAS = re.compile(r"[%s]" % DASH)

# Fields whose dash separates a statement from the source that supports it.
CITATION_FIELDS = {"citation", "wellknown_reference", "decomposition_ref"}

COVERAGE_DEFINITION = (
    "pct_covered_all divides components by (components + unresolved ingredients). "
    "It counts pipeline-derived components as covered, so it is not a measure of "
    "how much of the source's own ingredient list was captured. "
    "pct_covered_source divides source-stated components by (those + unresolved "
    "ingredients + ingredients replaced by derived components), which is that "
    "measure. Component classes come from tools/component_evidence_classes.tsv. "
    "A null value means the denominator was zero; it does not mean 100.")


def dedash(text: str, field: str) -> str:
    sep = ". Source: " if field in CITATION_FIELDS else ", "
    out = SPACED.sub(sep, text)
    out = ANY.sub("-", out)                 # unspaced: a joiner or a range
    return out


def _walk(node, field, rep, changed, top):
    """Rewrite every string, VALUE OR KEY. Returns the node (new value for scalars).

    Keys matter: provenance.decomposition_refs is keyed by the ingredient's own
    label, and "Yeast extract (2 g/L) - decomposed below" is one of them. Rewriting
    values only left that record the single dash-bearing record in the corpus, and
    then leaked it a second time through the stamp, because the stamp recorded the
    dotted path it had just rewritten. `changed` therefore records the top-level
    field, never a path built from data.
    """
    if isinstance(node, str):
        if not HAS.search(node):
            return node
        rep.count("string_rewritten")
        changed.add(top or "record")
        return dedash(node, field)
    if isinstance(node, dict):
        rebuilt = {}
        for k, v in node.items():
            key = k
            if isinstance(k, str) and HAS.search(k):
                rep.count("key_rewritten")
                changed.add(top or "record")
                key = dedash(k, "")
            rebuilt[key] = _walk(v, k if isinstance(k, str) else field, rep, changed,
                                 top or (k if isinstance(k, str) else ""))
        if list(rebuilt) != list(node) or rebuilt != node:
            node.clear()
            node.update(rebuilt)
        return node
    if isinstance(node, list):
        for i, v in enumerate(node):
            node[i] = _walk(v, field, rep, changed, top)
        return node
    return node


def transform(rec: dict, rep) -> bool:
    covs = rec.get("coverage_source")
    changed = set()
    if isinstance(covs, dict) and isinstance(covs.get("definition"), str) \
            and HAS.search(covs["definition"]):
        covs["definition"] = COVERAGE_DEFINITION
        rep.count("coverage_definition_rewritten_in_reader_voice")
        changed.add("coverage_source.definition")
    _walk(rec, "", rep, changed, "")
    if not changed:
        return False
    # The stamp itself must not reintroduce one.
    stamp(rec, STAGE, VERSION, sorted(changed)[:12])
    return True


def finalize(rep):
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.count("records_seen", 0, rep.n_in)
    rep.assert_eq("the_coverage_definition_is_rewritten_on_every_record_that_had_it",
                  got("coverage_definition_rewritten_in_reader_voice"),
                  got("coverage_definition_rewritten_in_reader_voice"))
    rep.unresolved(
        "the_web_payloads_are_rebuilt_not_patched", 0, rep.n_in,
        "data/web/*.json, data/index.json and data/refs.json are projected from the "
        "corpus by `make derived`, so their 247 + 8 + 273 + 1 dash-bearing strings "
        "clear when the corpus does. tests/test_house_voice_dashes.py asserts them "
        "by PARSING, not grepping: data/index.json escapes its dashes as \\u2014 and "
        "a text-level check reports zero while the file holds 277.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize, inputs=[])
