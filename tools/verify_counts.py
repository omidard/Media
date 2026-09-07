#!/usr/bin/env python3
"""tools/verify_counts.py — one catalogue, one total. Fails when any shipped number disagrees.

Four different totals ship at once today (findings COV-02, PROV-11, COV-06, NM-20):

    13,515   data/media/*.json on disk, and data/index.json `count`, and the live site hero
    13,073   data/stats.json `count`                     — an orphan: nothing generates it
    12,387   data/media_stats.json `total`               — stale since 2026-07-16
    12,387   data/presence_matrix.json `n_media`         — stale, and a documented API endpoint
    11,367   README.md:13 and README.md:113              — never matched the repo at any commit

The site therefore renders a 13,515 headline above a category doughnut summing to 12,387,
and its README says 11,367. There is no number a reader can cite.

This test defines the corpus on disk as the authority — it is the only total that is
computed rather than typed — and asserts every other shipped artifact against it, including
key-for-key equality of the category breakdown. A total-only check would not have caught the
missing `growth_medium` slice (443 media invisible on the site), so the breakdowns are
checked too.

It is expected to FAIL until the rebuild stage regenerates the derived artifacts. That is the
point: a failing test with real output is the honest state, and it becomes the gate that
stops the four totals from diverging again.

Not a stage: it reads the shipped derived artifacts, not a corpus, and writes nothing. It
lives in tools/ so the stage registry check does not see it as an unregistered stage.
tests/test_counts_reconcile.py wraps it for pytest.

USAGE
    python3 tools/verify_counts.py                     # against data/
    python3 tools/verify_counts.py --data-dir X        # against a rebuild
    python3 tools/verify_counts.py --counts counts.json  # against a stage-39 counts artifact

Exit 0 = every shipped total agrees. Exit 1 = at least one disagrees; each is printed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _by_category_from_index(data_dir):
    idx = _load(os.path.join(data_dir, "index.json")) or {}
    return idx.get("by_category")


# =========================================================================================
# STATED STATISTICS — the same defect as COV-02, one scale down.
#
# COV-02 was four totals for one catalogue. The corners held the same defect for smaller
# numbers: 14,341 was the concentration denominator until 296 concentrations that were an
# absence encoded as 0.0 were nulled, and the corrected 14,055 reached data/index.json while
# a typed 14,341 stayed in LICENSE, NOTICE, README.md, PROVENANCE.md, tools/licenses.tsv and
# the shipped methods.html. "The literature records" named five different populations whose
# sizes are 1,371 / 1,456 / 1,457 / 1,459 / 1,460, and one document stated 1,456 where the
# measurement is 1,371.
#
# The cure is the same in both cases and it is not proof-reading: every number below is
# computed by build_index.py into data/index.json, and every document that states one is
# checked against it here. A statistic with no generator has to sit next to the predicate
# that defines it, or this file fails and says which document.
# =========================================================================================

#: Every document whose prose states a number the corpus can answer.
STATED_DOCS = [
    "README.md", "LICENSE", "NOTICE", "PROVENANCE.md", "DESIGN.md", "API.md",
    "openapi.yaml", "index.html", "methods.html", "compare.html", "families.html",
    "patterns.html", "client/README.md",
    "client/pymediadb/__init__.py", "assets/media.js",
    # The deploy-surface manifest is read by /gate4 and states the denominators the
    # headline claims are checked against; it is a claim surface like any other.
    "docs/DEPLOY_SURFACE.tsv", "docs/PUSH_CHECKLIST.md",
]

#: "<n> of <m> [non-null] concentration[_mM] values". m is the denominator that went stale.
_CONCENTRATION = re.compile(
    r"([\d,]+)\s+of\s+(?:the\s+)?([\d,]+)\s+(?:non-null\s+)?concentration(?:_mM)?\s+values"
    r"(?:[^.()]{0,40}?\(\s*([\d.]+)\s*%\s*\))?",
    re.I)

#: A bare denominator with no numerator: "the resource's <m> concentration values".
_CONCENTRATION_BARE = re.compile(
    r"(?:resource's|library's|corpus's)\s+([\d,]+)\s+(?:non-null\s+)?concentration", re.I)

#: "<n> of <m> component(s)" — m is the component denominator.
_OF_COMPONENTS = re.compile(r"([\d,]{5,})\s+of\s+([\d,]{5,})\s+components?\b", re.I)

#: A count in the range the five literature populations live in.
_LIT_NUMBER = re.compile(r"\b1,?[34]\d\d\b")

#: A number in that range is only read as a literature claim when its neighbourhood
#: says so; 1,497 base-medium records and 1,364 non-BiGG fallbacks are not claims
#: about literature and must not be dragged into this check.
_LIT_CONTEXT = re.compile(
    r"literature|publication|primary[ _]paper|GrowthDB|extraction|unreproducible"
    r"|PMC|\bdoi\b|citation_type", re.I)

#: population key in index.json -> the words that must sit next to its number.
#: A count whose window matches none of these is a literature statistic with no
#: stated population, which is the defect itself.
_LIT_POPULATIONS = [
    ("media_from_the_lost_extraction_batches",
     r"unreproducible|extraction|LLM|lit_|growthlit_|complexlit_|regenerable"),
    ("media_attributed_to_primary_literature",
     r"primary publication|primary literature|source attribution|attributed|mined from"),
    ("media_via_growthdb", r"GrowthDB|growthdb_literature"),
    ("media_whose_source_type_is_literature", r"source_type"),
    ("media_whose_citation_type_is_primary_paper", r"citation_type|primary[ _]paper"),
    ("media_with_no_doi_carrying_a_pmc_id", r"\bdoi\b|PMC"),
]

_LIT_WINDOW = 130


def _n(text):
    return int(text.replace(",", ""))


def _read(repo, rel):
    path = os.path.join(repo, rel)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _line_of(text, pos):
    return text[:pos].count("\n") + 1


def check_stated_statistics(repo, data_dir, add):
    """Every prose statistic must equal what build_index.py measured.

    `add` is the row collector from check(); this contributes rows in the same shape,
    so the CLI, `make preflight` and tests/test_counts_reconcile.py all see them.
    """
    idx = _load(os.path.join(data_dir, "index.json"))
    if idx is None:
        add("stated statistics: data/index.json present", False, "present", "missing",
            "nothing to check the documents against")
        return

    # ---- concentration values ------------------------------------------------------
    cp = idx.get("concentration_provenance") or {}
    totals = idx.get("component_totals") or {}
    n_conc = cp.get("n_with_concentration_mM", totals.get("n_with_concentration_mM"))
    n_components = (idx.get("exchange_resolution") or {}).get("of")
    # Every numerator a document may legitimately state beside that denominator.
    legitimate = {n_conc}
    legitimate |= set((cp.get("by_source_db") or {}).values())
    legitimate.discard(None)

    bad_den, bad_num, bad_pct, bare = [], [], [], []
    for rel in STATED_DOCS:
        text = _read(repo, rel)
        if text is None:
            continue
        for m in _CONCENTRATION.finditer(text):
            num, den, pct = _n(m.group(1)), _n(m.group(2)), m.group(3)
            where = "%s:%d" % (rel, _line_of(text, m.start()))
            if den != n_conc:
                bad_den.append("%s states a denominator of %s" % (where, den))
            if num not in legitimate:
                bad_num.append("%s states %s, which no measurement in "
                               "concentration_provenance produces" % (where, num))
            if pct is not None and den:
                want = round(100.0 * num / den, 1)
                if abs(float(pct) - want) > 0.05:
                    bad_pct.append("%s says %s%%, measured %s%%" % (where, pct, want))
        for m in _CONCENTRATION_BARE.finditer(text):
            if _n(m.group(1)) != n_conc:
                bare.append("%s:%d states %s"
                            % (rel, _line_of(text, m.start()), _n(m.group(1))))

    add("every stated concentration denominator is the measured one",
        not (bad_den or bare), n_conc, "; ".join(bad_den + bare) or "all agree",
        "the corrected 14,055 reached data/index.json while a typed 14,341 stayed in "
        "six documents")
    add("every stated concentration numerator is a measured one",
        not bad_num, "a value in concentration_provenance",
        "; ".join(bad_num) or "all measured")
    add("every stated concentration percentage is the measured one",
        not bad_pct, "numerator/denominator", "; ".join(bad_pct) or "all agree")

    # ---- component denominators ----------------------------------------------------
    bad_comp = []
    for rel in STATED_DOCS:
        text = _read(repo, rel)
        if text is None:
            continue
        for m in _OF_COMPONENTS.finditer(text):
            if _n(m.group(2)) != n_components:
                bad_comp.append("%s:%d states a denominator of %s"
                                % (rel, _line_of(text, m.start()), _n(m.group(2))))
    add("every stated component denominator is the measured one",
        not bad_comp, n_components, "; ".join(bad_comp) or "all agree",
        "'N of M components' is how 'every component carries a cross-reference' "
        "survived: the exceptions had no denominator to be counted against")

    # ---- the five literature populations -------------------------------------------
    pops = idx.get("literature_populations") or {}
    measured = {}
    for key, keywords in _LIT_POPULATIONS:
        entry = pops.get(key) or {}
        if entry.get("n") is not None:
            measured[key] = (entry["n"], re.compile(keywords, re.I))
    if not measured:
        add("data/index.json publishes the literature populations", False,
            "literature_populations", "absent",
            "run `make derived`; the documents cannot be checked without it")
        return

    unstated, mismatched = [], []
    for rel in STATED_DOCS:
        text = _read(repo, rel)
        if text is None:
            continue
        for m in _LIT_NUMBER.finditer(text):
            lo = max(0, m.start() - _LIT_WINDOW)
            window = text[lo:m.end() + _LIT_WINDOW]
            if not _LIT_CONTEXT.search(window):
                continue                       # not a claim about the literature media
            where = "%s:%d" % (rel, _line_of(text, m.start()))
            # The population is the one whose keyword sits closest to the number.
            n_lo, n_hi = m.start() - lo, m.end() - lo
            best, best_d = None, None
            for key, (n, pattern) in measured.items():
                for k in pattern.finditer(window):
                    # characters BETWEEN the number and the keyword, either side
                    d = max(0, k.start() - n_hi, n_lo - k.end())
                    if best_d is None or d < best_d:
                        best, best_d = key, d
            if best is None:
                unstated.append("%s states %s as a literature count with no population"
                                % (where, m.group(0)))
            elif measured[best][0] != _n(m.group(0)):
                mismatched.append("%s states %s where %s is %d"
                                  % (where, m.group(0), best, measured[best][0]))

    add("every stated literature count names the population it counts",
        not unstated, "a population keyword beside each",
        "; ".join(unstated) or "all stated",
        "'literature records' named five populations sized 1,371 / 1,456 / 1,457 / "
        "1,459 / 1,460")
    add("every stated literature count equals its population's measurement",
        not mismatched, {k: v[0] for k, v in measured.items()},
        "; ".join(mismatched) or "all agree")

    # ---- schema fields that must not ship null -------------------------------------
    for label, obj in (("data/index.json", idx),
                       ("data/api/manifest.json",
                        _load(os.path.join(data_dir, "api", "manifest.json")))):
        if obj is None:
            continue
        renames = obj.get("field_renames")
        if renames is None:
            continue
        nulls = [r.get("old") for r in renames if r.get("measured") is None]
        add("%s field_renames[].measured is populated" % label,
            not nulls, "a measurement for every rename",
            "null for %s" % nulls if nulls else "all populated",
            "a schema field that ships null tells a consumer nothing and invites the "
            "inference that the rename had no measurable reason")

    # ---- the artifact manifest's own literature count -------------------------------
    man = _load(os.path.join(data_dir, "MANIFEST.json"))
    if man:
        m = ((man.get("provenance") or {}).get("measured_2026_09_06") or {})
        want = (pops.get("media_from_the_lost_extraction_batches") or {}).get("n")
        if want is not None and "media_permanently_unreproducible" in m:
            add("data/MANIFEST.json permanently-unreproducible count",
                m["media_permanently_unreproducible"] == want, want,
                m["media_permanently_unreproducible"],
                "read from data/index.json by tools/build_manifest.py, never typed")


def check(data_dir, readme_path, counts_path=None):
    results = []

    def add(name, ok, expected, actual, note=""):
        results.append(
            {"check": name, "ok": bool(ok), "expected": expected, "actual": actual, "note": note}
        )

    media_dir = os.path.join(data_dir, "media")
    on_disk = len(glob.glob(os.path.join(media_dir, "*.json")))

    authoritative = on_disk
    auth_by_category = None
    if counts_path:
        c = _load(counts_path)
        if c:
            authoritative = c["authoritative_count"]
            auth_by_category = c.get("by_category")
            add(
                "authoritative counts artifact agrees with the corpus on disk",
                authoritative == on_disk,
                on_disk,
                authoritative,
                counts_path,
            )

    if auth_by_category is None:
        auth_by_category = {}
        for f in glob.glob(os.path.join(media_dir, "*.json")):
            with open(f, encoding="utf-8") as fh:
                cat = json.load(fh).get("category")
            auth_by_category[cat] = auth_by_category.get(cat, 0) + 1

    # --- index.json ----------------------------------------------------------------------
    idx = _load(os.path.join(data_dir, "index.json"))
    if idx is None:
        add("data/index.json exists", False, "present", "missing")
    else:
        add("data/index.json count", idx.get("count") == authoritative, authoritative, idx.get("count"))
        add(
            "data/index.json media rows",
            len(idx.get("media", [])) == authoritative,
            authoritative,
            len(idx.get("media", [])),
        )
        add(
            "data/index.json by_category keys",
            set(idx.get("by_category", {})) == set(auth_by_category),
            sorted(auth_by_category),
            sorted(idx.get("by_category", {})),
            "a total-only check misses a whole missing category",
        )
        add(
            "data/index.json by_category values",
            idx.get("by_category") == auth_by_category,
            auth_by_category,
            idx.get("by_category"),
        )

    # --- media_stats.json ------------------------------------------------------------------
    ms = _load(os.path.join(data_dir, "media_stats.json"))
    if ms is None:
        add("data/media_stats.json exists", False, "present", "missing")
    else:
        add("data/media_stats.json total", ms.get("total") == authoritative, authoritative, ms.get("total"))
        add(
            "data/media_stats.json by_category keys",
            set(ms.get("by_category", {})) == set(auth_by_category),
            sorted(auth_by_category),
            sorted(ms.get("by_category", {})),
            "the site's category doughnut reads this file",
        )

    # --- presence_matrix.json ---------------------------------------------------------------
    pm = _load(os.path.join(data_dir, "presence_matrix.json"))
    if pm is None:
        add("data/presence_matrix.json exists", False, "present", "missing")
    else:
        add(
            "data/presence_matrix.json n_media",
            pm.get("n_media") == authoritative,
            authoritative,
            pm.get("n_media"),
            "a documented public API endpoint (API.md:66)",
        )

    # --- stats.json: no longer an orphan -----------------------------------------------------
    # It had no generator anywhere in tools/, which is why it shipped 442 media stale.
    # SCHEMA-05's corrected fix says to give it one rather than delete it ("write the
    # generator - build_index.py should emit data/stats.json in the same pass"), and
    # build_index.py now does, so it cannot drift from index.json again. It is kept
    # rather than removed because it is a file on a live GitHub Pages site that
    # advertises itself as an endpoint; the check is now that it AGREES.
    stats_path = os.path.join(data_dir, "stats.json")
    if os.path.exists(stats_path):
        st = _load(stats_path) or {}
        add(
            "data/stats.json count",
            st.get("count") == authoritative,
            authoritative,
            st.get("count"),
            "written by build_index.py in the same pass as index.json",
        )
        add(
            "data/stats.json by_category",
            st.get("by_category") == _by_category_from_index(data_dir),
            "identical to index.json by_category",
            st.get("by_category"),
            "the two are emitted together, so a disagreement means one was hand-edited",
        )

    # --- README ------------------------------------------------------------------------------
    if os.path.exists(readme_path):
        txt = open(readme_path, encoding="utf-8").read()
        nums = {int(n.replace(",", "")) for n in re.findall(r"\b(\d{1,3},\d{3})\b\s*media", txt)}
        bad = sorted(n for n in nums if n != authoritative)
        add(
            "README media totals",
            not bad,
            authoritative,
            sorted(nums) or "none found",
            "every '<n> media' figure in the README must be the authoritative count",
        )
        if bad:
            results[-1]["note"] += "; disagreeing: %s" % bad

    # --- the smaller numbers, same defect ------------------------------------------------
    check_stated_statistics(os.path.dirname(os.path.abspath(readme_path)) or REPO,
                            data_dir, add)

    return authoritative, results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=os.path.join(REPO, "data"))
    ap.add_argument("--readme", default=os.path.join(REPO, "README.md"))
    ap.add_argument("--counts", default=None)
    ap.add_argument("--json", default=None, help="write the result as JSON")
    ap.add_argument("--write-counts", default=None,
                    help="write the authoritative counts artifact (count + by_category, "
                         "computed from the corpus, never typed) to this path")
    a = ap.parse_args(argv)

    authoritative, results = check(a.data_dir, a.readme, a.counts)

    if a.write_counts:
        by_cat = {}
        for f in glob.glob(os.path.join(a.data_dir, "media", "*.json")):
            with open(f, encoding="utf-8") as fh:
                cat = json.load(fh).get("category")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        payload = {
            "authoritative_count": authoritative,
            "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "corpus_dir": os.path.join(a.data_dir, "media"),
            "note": ("Computed from the corpus, never typed. Every shipped total — "
                     "index.json count, media_stats.json total, presence_matrix.json n_media, "
                     "the README headline and its per-source table, the site hero — must equal "
                     "these numbers, and tools/verify_counts.py fails when one does not."),
        }
        os.makedirs(os.path.dirname(os.path.abspath(a.write_counts)), exist_ok=True)
        with open(a.write_counts, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
    n_fail = sum(1 for r in results if not r["ok"])

    print("AUTHORITATIVE COUNT: %d media (%s/media/*.json)" % (authoritative, a.data_dir))
    print("-" * 78)
    for r in results:
        print(
            "%s %s\n      expected: %s\n      actual:   %s%s"
            % (
                "PASS" if r["ok"] else "FAIL",
                r["check"],
                r["expected"],
                r["actual"],
                ("\n      note:     " + r["note"]) if r["note"] else "",
            )
        )
    print("-" * 78)
    print("%d checks, %d failing" % (len(results), n_fail))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(
                {"authoritative_count": authoritative, "n_failing": n_fail, "checks": results},
                fh,
                indent=1,
            )
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
