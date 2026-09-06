#!/usr/bin/env python3
"""
STAGE: normalize_names
======================

Base-medium + modifier taxonomy for the media corpus, keyed on VERIFIED SOURCE
IDENTITY AND COMPOSITION -- never on a filename, an id prefix, or a description.

ORDER MATTERS: run tools/stages/load_concentrations.py FIRST.
--------------------------------------------------------------
Grouping the corpus before the quantitative layer lands would merge records that
are already indistinguishable. 23 of the 44 LB-family records are byte-identical
in exchange set AND bounds AND concentration -- plain LB, one-third LB, alkaline
LB, LB+5% NaCl, LB+1 mM DTT, LB+BSA, LB+Tween-80, LB+kanamycin+rifampicin, LB
agar and LB broth are all the same 51 exchanges (finding NM-02). Collapsing them
under one LB parent while that is still true destroys the last surviving evidence
that they were ever different media: the name (NM-02 risk 2). So this stage
consumes the quantitative signature the concentration stage writes, and where a
modifier still cannot be represented it SAYS SO on the record rather than
implying a difference that is not there.


CONTRACT
--------
READS
  --in    DIR   corpus written by load_concentrations (or data/media as a fallback)
  --vocab DIR   data/vocab, holding two versioned inputs:
                  media_families.tsv         naming registry (269 families)
                  mediadive_collections.tsv  MediaDive's OWN `source` field per
                                             accession, fetched from
                                             https://mediadive.dsmz.de/rest/media
                                             and checked in, so the collection
                                             attribution is reproducible without
                                             a live fetch and is never guessed
                                             from a URL host.

WRITES
  <out>/media/<id>.json                   corrected corpus
  <out>/reports/naming_report.json        machine-readable summary + denominators
  <out>/reports/families.tsv              one row per family with its members
  <out>/reports/name_collisions.tsv       same name, different composition
  <out>/reports/composition_duplicates.tsv different name, identical composition
  <out>/reports/unnormalizable.tsv        every record this stage refused to file

WHAT IT ADDS TO EACH RECORD (never removes, never renames, never deletes)
  name_display        cleaned for rendering: HTML entities unescaped, <sub> tags
                      resolved, NFKC-normalised, whitespace collapsed. 19 shipped
                      names carry raw markup that renders literally on the live
                      site, e.g. "LB Agar with MnSO<sub>4</sub>" (NM-17).
  name_verbatim       the source's own string, preserved as provenance.
  name_provenance_tail  the "(DSMZ J1273)" / "(PMC4019345)" / "(USDA food medium)"
                      suffix this pipeline itself appended, split out of the name
                      so identity stops living inside a display string (NM-13).
  collection          DSMZ | JCM | CCAP | public, from MediaDive's own field.
  collection_accession, aggregator
  family              {id, label, method, evidence, candidates, denominator,
                       composition_corroborated, parent}
                      method is one of
                        name_and_composition  name matched AND the record's own
                                              non-injected chemistry agrees with
                                              the family's reference composition
                        name_only             name matched, no chemical
                                              corroboration was possible
                        null                  no match, or ambiguous, or vetoed
                      An unassigned family is null. Never "", never a guess.
  modifiers           typed list, each {kind, agent, amount, unit, verbatim,
                      declared_in_name, reflected_in_composition}
  preparation         agar | broth | slant | plate | null
  strength            {factor, verbatim} for 1/3, half-concentrated, 0.01%, 2x
  ph                  numeric or a qualitative token, when the name states one
  composition_identical_to   ids of records with the same quantitative signature
  composition_distinguishes_modifiers  TRUE only when this record's chemistry
                      actually differs from its identical-composition siblings.
                      When FALSE the record states its own limitation instead of
                      silently implying a difference (NM-02 fix step 4).


ASSERTIONS (the stage exits non-zero if any fails)
  N1  category == 'food'  =>  family is null. 701 food descriptions say "plus a
      standard M9 mineral base" and 0 food NAMES say M9, so any family assignment
      on the food side is a description artifact (NM-01 verification (6)).
  N2  the `description` field is never read for family detection.
  N3  a name matching >1 family after alias/parent resolution gets family null
      plus the candidate list. "Luria Broth (LB) ...; tryptic soy agar (TSA) for
      plating" must not be filed under TSB because TSB sorts first (NM-13).
  N4  a negation-scoped token never produces a modifier asserting presence.
      "Sulfate-Free Metako Medium", "Modified CGM, no formate" (NM-16).
  N5  record `id` is never changed -- the ids are the browser's deep-link key
      and MediaDive's real namespace (NM-03 risk 2).
  N6  the `name` field is never overwritten. It is the verbatim upstream join key
      (60/60 sampled MediaDB ISB names are byte-identical to their upstream page
      titles); overwriting it in place is what froze 11 DSMZ mis-casings beyond
      the reach of the tool's own idempotency check (NM-14 risk).
  N7  no record is deleted and no record is merged. Grouping is a label, never an
      os.remove -- tools/merge_duplicates.py has already destroyed 57 records
      that way and 14 more are one command away (NM-06).
  N8  "1/4 LB" and friends never resolve to the LB family.
  N9  every family count published carries its denominator.
"""
import argparse, json, os, re, sys, glob, html, unicodedata, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools"))

INJECTED_METHODS = {
    "hydrolysate_approximation", "complex_decomposition", "mineral_base",
    "base", "base_medium_expansion", "usda_mineral", "wellknown_curation",
}

# ---------------------------------------------------------------------------
# name cleaning
_TAG = re.compile(r"<\s*sub\s*>(.*?)<\s*/\s*sub\s*>", re.I)
_ANYTAG = re.compile(r"<[^>]+>")


def clean_name(n):
    s = html.unescape(n or "")
    s = _TAG.sub(r"\1", s)          # MnSO<sub>4</sub> -> MnSO4
    s = _ANYTAG.sub("", s)
    s = html.unescape(s)            # entities can survive one pass
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


# the provenance suffixes THIS pipeline appended, at seven generator lines
_TAIL = re.compile(
    r"\s*\((?:DSMZ|JCM|CCAP|ATCC|MediaDive)\s+[A-Za-z0-9.\-]+\)\s*$"
    r"|\s*\(PMC\d+\)\s*$"
    r"|\s*\(USDA food medium\)\s*$"
    r"|\s*\(food medium\)\s*$"
    r"|\s*\(standard\)\s*$", re.I)


def split_tail(name):
    tails = []
    s = name
    while True:
        m = _TAIL.search(s)
        if not m:
            break
        tails.insert(0, m.group(0).strip())
        s = s[:m.start()].rstrip()
    return s, (" ".join(tails) or None)


# ---------------------------------------------------------------------------
# LB is also the abbreviation for POUND.
#
# The veto must separate two genuinely different strings that both read
# "<fraction> LB":
#   "WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single"  -> a quarter POUND of beef
#   "1/3 LB Agar (DSMZ J842)"                      -> one-third-strength LB medium
# so it fires only when the LB token is NOT followed by a medium-context word.
# IMPORTED, not re-declared: one rule, one regex. Two uncoordinated copies of the
# same rule is the defect that let tools/base_media.py:113 and
# tools/curate_wellknown_media.py:1618 both govern all 13,515 media.
import base_media as _bm
_LB_QUANTITY = _bm.LB_QUANTITY_VETO

# negation scoping: a token inside one of these spans is ABSENT, not present
_NEGATION = re.compile(
    r"\b(?:no|without|lacking|minus|free\s+of|devoid\s+of|omitting)\b[^,;+()]*"
    r"|\b[\w-]+[- ]free\b"
    r"|\b[\w-]+[- ](?:deprived|starved|starvation|limited|limitation|depleted)\b",
    re.I)

_PREPARATION = [
    (re.compile(r"\bagar\b|\bplate count\b", re.I), "agar"),
    (re.compile(r"\bbroth\b|\bliquid\b", re.I), "broth"),
    (re.compile(r"\bslant\b|\bslope\b", re.I), "slant"),
    (re.compile(r"\bplates?\b", re.I), "plate"),
]

_STRENGTH = [
    (re.compile(r"\b(\d+)\s*/\s*(\d+)\s*(?=[A-Za-z])", re.I),
     lambda m: float(m.group(1)) / float(m.group(2))),
    (re.compile(r"\bhalf[- ]?(?:concentrated|strength)\b", re.I), lambda m: 0.5),
    (re.compile(r"\bdouble[- ]?(?:concentrated|strength)\b", re.I), lambda m: 2.0),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(?:concentrat|strength)", re.I),
     lambda m: float(m.group(1))),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*%\s*(?=[A-Z])"), lambda m: float(m.group(1)) / 100.0),
    (re.compile(r"[¼]"), lambda m: 0.25),
    (re.compile(r"[½]"), lambda m: 0.5),
]

_UNIT = (r"%|mM|µM|uM|nM|pM|M\b|g/L|g/l|g L-1|mg/mL|mg/ml|mg/L|mg/l|"
         r"µg/ml|ug/ml|µg/mL|g/100 ?mL|IU|U/mL|v/v|w/v|x|×")
_DOSE = re.compile(r"(\d+(?:[.,]\d+)?(?:\s*[eE][-+]?\d+)?)\s*(" + _UNIT + r")", re.I)
_PH = re.compile(r"\bpH\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I)
_PH_QUAL = re.compile(r"\b(alkaline|acidic|neutral|acidified|alkalin\w*)\b", re.I)

# modifier classes. `agent` is the literal token from the name; nothing is
# resolved to chemistry here -- that is the mapping layer's job and doing it
# here would be a name-to-chemistry inference of exactly the kind under audit.
_MOD_CLASS = [
    (re.compile(r"\b(kanamycin|rifampicin|ampicillin|chloramphenicol|tetracyclin\w*|"
                r"streptomycin|erythromycin|vancomycin|gentamic\w+|spectinomycin|"
                r"nalidixic|polymyx\w+|cycloheximide|nystatin|amphotericin|"
                r"colistin|fosfomycin|cefsulodin|novobiocin|bacitracin)\b", re.I), "antibiotic"),
    (re.compile(r"\b(NaCl|KCl|MgCl2|CaCl2|MgSO4|MnSO4|FeSO4|K2HPO4|KH2PO4|"
                r"Na2CO3|NaHCO3|carbonates?|sea ?salt)\b", re.I), "salt_supplement"),
    (re.compile(r"\b(DTT|BSA|Tween[- ]?\d*|Triton|cysteine|dithiothreitol|"
                r"resazurin|sodium sulfide|Na2S|reducing agent)\b", re.I), "additive"),
    (re.compile(r"\b(glucose|dextrose|sucrose|fructose|galactose|lactose|maltose|"
                r"xylose|arabinose|glycerol|acetate|pyruvate|succinate|citrate|"
                r"lactate|formate|methanol|ethanol|starch|cellulose|mannitol|"
                r"sorbitol|trehalose|ribose|rhamnose|fucose|gluconate)\b", re.I), "carbon_source"),
    (re.compile(r"\b(yeast extract|tryptone|peptone|casamino|beef extract|"
                r"casitone|proteose|malt extract|meat extract|serum|blood|"
                r"rumen fluid|soytone)\b", re.I), "complex_supplement"),
    (re.compile(r"\b(thiamine|biotin|vitamin \w+|riboflavin|B12|cobalamin|"
                r"pantothenate|pyridoxine|folate|nicotinate|hemin|menadione|"
                r"vitamins?)\b", re.I), "vitamin"),
    (re.compile(r"\b(nitrate|nitrite|ammoniu?m?|NH4Cl|urea|glutamate|glutamine|"
                r"asparagine|nitrogen source|N source)\b", re.I), "nitrogen_source"),
    (re.compile(r"\b(trace element\w*|trace metal\w*|micronutrient\w*|SL-?\d+|"
                r"Wolfe'?s? mineral)\b", re.I), "trace_elements"),
    (re.compile(r"\b(sea ?water|artificial sea ?water|ASW|freshwater|brackish)\b", re.I), "matrix"),
]

_MODIFIED = re.compile(r"\b(modified|derived|adapted|variant|amended)\b", re.I)


def parse_ph(core):
    m = _PH.search(core)
    if m:
        try:
            return {"value": float(m.group(1)), "verbatim": m.group(0), "kind": "numeric"}
        except ValueError:
            pass
    m = _PH_QUAL.search(core)
    if m:
        return {"value": None, "verbatim": m.group(0), "kind": "qualitative"}
    return None


def negation_spans(core):
    return [m.span() for m in _NEGATION.finditer(core)]


def in_negation(pos, spans):
    return any(a <= pos < b for a, b in spans)


def parse_modifiers(core, consumed_spans=()):
    """Return (modifiers, unparsed_fragments). Nothing is forced.

    `consumed_spans` are character ranges already claimed by another parser
    (the strength parser). Without this, "0.01% LB Seawater Medium" attaches the
    0.01% strength to Seawater as if seawater were dosed at 0.01%.
    """
    spans = negation_spans(core)
    mods = []
    seen = set()
    for rx, kind in _MOD_CLASS:
        for m in rx.finditer(core):
            if in_negation(m.start(), spans):
                mods.append({"kind": kind, "agent": m.group(0), "amount": None,
                             "unit": None, "verbatim": m.group(0),
                             "declared_in_name": True, "polarity": "absent",
                             "reflected_in_composition": None})
                continue
            key = (kind, m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            # nearest dose to the LEFT of the agent, within 24 chars
            lo = max(0, m.start() - 24)
            dose = None
            for dm in _DOSE.finditer(core, lo, m.start()):
                if any(a <= dm.start() < b for a, b in consumed_spans):
                    continue
                dose = dm
            amount = unit = None
            verb = m.group(0)
            if dose:
                try:
                    amount = float(dose.group(1).replace(",", "."))
                except ValueError:
                    amount = None
                unit = dose.group(2)
                verb = core[dose.start():m.end()]
            mods.append({"kind": kind, "agent": m.group(0), "amount": amount,
                         "unit": unit, "verbatim": verb, "declared_in_name": True,
                         "polarity": "present", "reflected_in_composition": None})
    if _MODIFIED.search(core):
        mods.append({"kind": "modified", "agent": _MODIFIED.search(core).group(0),
                     "amount": None, "unit": None,
                     "verbatim": _MODIFIED.search(core).group(0),
                     "declared_in_name": True, "polarity": "present",
                     "reflected_in_composition": None})
    # doses in the name that no modifier class claimed
    claimed = set()
    for md in mods:
        claimed.add(md["verbatim"])
    unparsed = [d.group(0) for d in _DOSE.finditer(core)
                if not any(d.group(0) in c for c in claimed)]
    return mods, unparsed


def parse_strength(core, family_start=None):
    """Strength qualifies the BASE, so it can only appear BEFORE the family token.

    Searching the whole name reads a supplement's dose as a dilution: "LB broth
    (Miller, Difco) + 0.2% Tween-80" is not one-fifth-percent LB, and "LB Agar
    with 5% NaCl" is not 5%-strength LB.
    """
    # search the WHOLE name but only accept a match that STARTS before the
    # family token, so the lookaheads can still see the family word itself
    # ("1/3 LB Agar" -> the fraction rule needs the "L" of LB to be visible)
    limit = family_start if family_start is not None else 24
    for rx, fn in _STRENGTH:
        m = None
        for cand in rx.finditer(core):
            if cand.start() < limit:
                m = cand
                break
        if m:
            try:
                return ({"factor": round(fn(m), 6), "verbatim": m.group(0).strip()},
                        m.span())
            except (ValueError, ZeroDivisionError):
                return ({"factor": None, "verbatim": m.group(0).strip()}, m.span())
    return None, None


def parse_preparation(core):
    for rx, kind in _PREPARATION:
        if rx.search(core):
            return kind
    return None


# ---------------------------------------------------------------------------
class Vocab:
    def __init__(self, vocab_dir):
        self.families = []
        self.alias = {}
        self.parent = {}
        p = os.path.join(vocab_dir, "media_families.tsv")
        hdr = None
        for ln in open(p):
            if ln.startswith("#") or not ln.strip():
                continue
            f = ln.rstrip("\n").split("\t")
            if hdr is None:
                hdr = f
                continue
            r = dict(zip(hdr, f))
            try:
                rx = re.compile(r["name_regex"], re.I)
            except re.error:
                continue
            self.families.append((r["family_id"], r["display_label"], rx,
                                  r.get("reference_id") or ""))
            if r.get("alias_of"):
                self.alias[r["family_id"]] = r["alias_of"]
            if r.get("parent_family"):
                self.parent[r["family_id"]] = r["parent_family"]
        self.collections = {}
        cp = os.path.join(vocab_dir, "mediadive_collections.tsv")
        if os.path.exists(cp):
            hdr = None
            for ln in open(cp):
                if ln.startswith("#") or not ln.strip():
                    continue
                f = ln.rstrip("\n").split("\t")
                if hdr is None:
                    hdr = f
                    continue
                r = dict(zip(hdr, f))
                self.collections[r["mediadive_id"]] = r

    def match(self, core):
        """Return (resolved_ids, all_candidate_ids, winning_match_start).

        Never reads a description: 701 food descriptions name an M9 mineral base
        the food does not derive from, and 0 food NAMES say M9.
        """
        hits = []
        for fid, label, rx, ref in self.families:
            m = rx.search(core)
            if m:
                hits.append((fid, m.span()))
        if _LB_QUANTITY.search(core):
            hits = [h for h in hits if h[0] != "lb"]
        cands = [h[0] for h in hits]
        # collapse declared synonyms
        hits = [(self.alias.get(f, f), sp) for f, sp in hits]
        # drop a match whose span is strictly contained in another's -- the longer
        # match is the more specific family (LBv2 contains LB, BG-11_0 contains BG-11)
        keep = []
        for a in hits:
            inside = any(b is not a and b[1][0] <= a[1][0] and a[1][1] <= b[1][1]
                         and (b[1][1] - b[1][0]) > (a[1][1] - a[1][0]) for b in hits)
            if not inside:
                keep.append(a)
        # a declared refinement beats its declared parent
        ids = {f for f, _ in keep}
        for child, par in self.parent.items():
            if child in ids and par in ids:
                ids.discard(par)
        start = min((sp[0] for f, sp in keep if f in ids), default=None)
        return sorted(ids), sorted(set(cands)), start

    def label(self, fid):
        for f, lab, _rx, _ref in self.families:
            if f == fid:
                return lab
        return fid

    def reference(self, fid):
        for f, _lab, _rx, ref in self.families:
            if f == fid:
                return ref or None
        return None


def sourced_exchanges(rec):
    """The record's own chemistry, excluding everything the pipeline injected.

    Clustering on the full component set would rediscover the injected scaffold
    rather than observe the published recipe -- a proxy presented as the
    observation (MEDIA-WEB-07 risk). `wellknown_curation` counts as injected
    here because it is a canonical TEMPLATE that was written over the record's
    real recipe: 33 database-sourced records (18 LB, 15 MRS) carry it despite
    ids the writing script explicitly skips, and their published DSMZ recipes
    are gone (NM-02 verification 5, 11).
    """
    return {c["exchange"] for c in (rec.get("components") or [])
            if c.get("mapping_method") not in INJECTED_METHODS}


def all_exchanges(rec):
    """Full component set. Used ONLY for a family's canonical reference record,
    whose entire purpose IS to be the template."""
    return {c["exchange"] for c in (rec.get("components") or [])}


def jaccard(a, b):
    if not a or not b:
        return None
    return len(a & b) / float(len(a | b))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=os.path.join(REPO, "data", "media"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--vocab", default=os.path.join(REPO, "data", "vocab"))
    ap.add_argument("--corroborate-min", type=float, default=0.30,
                    help="minimum Jaccard against the family reference composition "
                         "before a name match is promoted to name_and_composition")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--ids", default=None)
    a = ap.parse_args()

    voc = Vocab(a.vocab)
    files = sorted(glob.glob(os.path.join(a.inp, "*.json")))
    if a.ids:
        want = set(a.ids.split(","))
        files = [f for f in files if os.path.basename(f)[:-5] in want]
    if a.sample:
        files = files[:a.sample]

    recs = [json.load(open(f)) for f in files]
    by_id = {r["id"]: r for r in recs}
    ref_comp = {}          # family_id -> sourced exchange set of its reference record
    for fid, _lab, _rx, ref in voc.families:
        if ref and ref in by_id:
            ref_comp[fid] = all_exchanges(by_id[ref])

    # quantitative signature, from the concentration stage when present
    def qsig(r):
        q = r.get("quantitation") or {}
        if q.get("quantitative_signature"):
            return q["quantitative_signature"]
        import hashlib
        key = sorted((c.get("exchange"), c.get("lower_bound"), c.get("upper_bound"),
                      c.get("concentration_mM"), c.get("recipe_g_l"),
                      c.get("usda_amount"), c.get("usda_unit"), c.get("foodb_content"))
                     for c in (r.get("components") or []))
        return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:16]

    sig_groups = collections.defaultdict(list)
    for r in recs:
        sig_groups[qsig(r)].append(r["id"])

    stats = collections.Counter()
    fails = []
    fam_members = collections.defaultdict(list)
    name_matched = collections.Counter()   # denominator: records whose NAME matches
    unnorm = []

    for r in recs:
        original_id = r["id"]
        original_name = r.get("name")
        cat = r.get("category")

        disp = clean_name(original_name)
        if disp != (original_name or ""):
            stats["name_display_differs_from_name"] += 1
        core, tail = split_tail(disp)
        r["name_display"] = disp
        r.setdefault("name_verbatim", r.get("name_original") or original_name)
        r["name_core"] = core
        r["name_provenance_tail"] = tail

        # --- collection, from MediaDive's own field, never from the URL host ---
        if original_id.startswith("mediadive_"):
            acc = original_id[len("mediadive_"):]
            row = voc.collections.get(acc)
            if row:
                r["collection"] = row["collection"]
                r["collection_accession"] = acc
                r["aggregator"] = "MediaDive"
                r["collection_source"] = ("MediaDive REST /rest/media `source` field, "
                                          "checked in at data/vocab/mediadive_collections.tsv")
                if row["collection"] != "DSMZ":
                    stats["collection_corrected_from_DSMZ"] += 1
                    stats["collection_" + row["collection"]] += 1
            else:
                r["collection"] = None
                r["collection_accession"] = acc
                r["aggregator"] = "MediaDive"
                stats["collection_unknown"] += 1

        # --- family -------------------------------------------------------
        ids, cands, fam_start = ([], [], None) if cat == "food" else voc.match(core)
        if cands:
            for c in cands:
                name_matched[voc.alias.get(c, c)] += 1
        fam = {"id": None, "label": None, "method": None, "evidence": None,
               "candidates": cands or None, "composition_corroborated": None,
               "corroboration_blocked_reason": None, "parent": None}
        if cat == "food":
            fam["method"] = None
            fam["refused_reason"] = "category_food_family_not_assigned"
        elif len(ids) == 1:
            fid = ids[0]
            fam["id"] = fid
            fam["label"] = voc.label(fid)
            fam["parent"] = voc.parent.get(fid) or None
            fam_members[fid].append(r["id"])
            if voc.reference(fid) == r["id"]:
                # this record IS the family's canonical reference formulation
                fam["evidence"] = "canonical_reference_record"
                fam["method"] = "canonical_reference"
                fam["composition_corroborated"] = 1.0
                stats["family_canonical_reference"] += 1
            else:
                fam["evidence"] = "name_regex:" + fid
                ref = ref_comp.get(fid)
                own = sourced_exchanges(r)
                j = None
                if not ref:
                    fam["corroboration_blocked_reason"] = "no_reference_composition_for_family"
                elif not own:
                    # every component of this record was written by the pipeline,
                    # so there is no observed chemistry left to corroborate with
                    fam["corroboration_blocked_reason"] = "record_has_no_sourced_components"
                    stats["corroboration_blocked_no_sourced_components"] += 1
                else:
                    j = jaccard(own, ref)
                if j is not None and j >= a.corroborate_min:
                    fam["method"] = "name_and_composition"
                    fam["composition_corroborated"] = round(j, 3)
                    stats["family_name_and_composition"] += 1
                else:
                    fam["method"] = "name_only"
                    fam["composition_corroborated"] = (round(j, 3) if j is not None else None)
                    if j is not None:
                        fam["corroboration_blocked_reason"] = "below_corroboration_threshold"
                    stats["family_name_only"] += 1
        elif len(ids) > 1:
            fam["method"] = None
            fam["refused_reason"] = "ambiguous_multiple_families"
            fam["candidates"] = ids
            stats["family_refused_ambiguous"] += 1
            unnorm.append((r["id"], core, "ambiguous_multiple_families", "|".join(ids)))
        else:
            fam["method"] = None
            fam["refused_reason"] = "no_family_match"
            stats["family_none"] += 1
        r["family"] = fam

        # --- modifiers ----------------------------------------------------
        # The modifier taxonomy is a LABORATORY-MEDIUM grammar (base + carbon
        # source + supplements + agar/broth + strength + pH + "modified"). Food
        # names are a different facet problem entirely -- 7,424 USDA names carry
        # a median of 3 comma-separated preparation facets over 830 food heads
        # (NM-12) -- and running this grammar over them manufactures nonsense
        # (a quarter-pound burger reading as quarter-strength medium).
        if cat == "food":
            r["modifiers"] = []
            r["modifiers_unparsed"] = None
            r["preparation"] = None
            r["strength"] = None
            r["ph_declared"] = None
            r["modifier_parse"] = "not_applicable_food_facets"
            mods = []
        else:
            strength, s_span = parse_strength(core, fam_start)
            mods, unparsed = parse_modifiers(core, [s_span] if s_span else [])
            r["modifier_parse"] = "laboratory_grammar_v1"
            r["strength"] = strength
            r["modifiers_unparsed"] = unparsed or None
            r["preparation"] = parse_preparation(core)
            r["ph_declared"] = parse_ph(core)
        sourced = sourced_exchanges(r)
        names_lower = {(c.get("name") or "").lower() for c in (r.get("components") or [])}
        bigg_ids = {c.get("bigg_metabolite") for c in (r.get("components") or [])}
        has_amount = any((c.get("quantity") or {}).get("value") is not None
                         or c.get("concentration_mM") is not None
                         for c in (r.get("components") or []))
        for md in mods:
            if md["polarity"] == "absent":
                md["reflected_in_composition"] = None
                continue
            ag = md["agent"].lower()
            present = any(ag in n for n in names_lower) or ag in bigg_ids
            # A modifier is only "reflected" if the chemistry is there AND the
            # record can express a quantity. Otherwise the composition cannot
            # distinguish "LB" from "LB + 5% NaCl" no matter what it contains.
            if not present:
                md["reflected_in_composition"] = False
            elif md.get("amount") is not None and not has_amount:
                md["reflected_in_composition"] = False
            else:
                md["reflected_in_composition"] = True
        if cat != "food":
            r["modifiers"] = mods or []

        # --- composition degeneracy ---------------------------------------
        s = qsig(r)
        sibs = [i for i in sig_groups[s] if i != r["id"]]
        r["composition_signature"] = s
        r["composition_identical_to"] = sibs or None
        declared = [m for m in mods if m["polarity"] == "present"]
        if sibs and declared:
            r["composition_distinguishes_modifiers"] = False
            r["composition_limitation"] = (
                "This record's composition, bounds and quantities are identical to "
                "%d other record(s). The modifier(s) its name declares are not "
                "represented in the chemistry and must not be read as a "
                "compositional difference." % len(sibs))
            stats["modifiers_declared_but_not_representable"] += 1
        elif sibs:
            r["composition_distinguishes_modifiers"] = False
            r["composition_limitation"] = (
                "Composition, bounds and quantities are identical to %d other "
                "record(s)." % len(sibs))
        else:
            r["composition_distinguishes_modifiers"] = True
            r["composition_limitation"] = None

        r["naming_stage"] = {"stage": "normalize_names", "stage_version": "1.0"}

        # --- assertions ----------------------------------------------------
        if r["id"] != original_id:
            fails.append(("N5", original_id, "id changed"))
        if r.get("name") != original_name:
            fails.append(("N6", original_id, "name overwritten"))
        if cat == "food" and r["family"]["id"] is not None:
            fails.append(("N1", original_id, "food record assigned a family"))
        if _LB_QUANTITY.search(core) and r["family"]["id"] == "lb":
            fails.append(("N8", original_id, "quantity-context LB resolved to LB family"))
        for md in r["modifiers"]:
            if md["polarity"] == "absent" and md["reflected_in_composition"]:
                fails.append(("N4", original_id, "negated modifier asserted present"))

    if len(recs) != len(files):
        fails.append(("N7", "-", "record count changed"))

    # ---- outputs ---------------------------------------------------------
    os.makedirs(os.path.join(a.out, "media"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "reports"), exist_ok=True)
    for r in recs:
        json.dump(r, open(os.path.join(a.out, "media", r["id"] + ".json"), "w"))

    # families.tsv, always with the denominator (N9)
    with open(os.path.join(a.out, "reports", "families.tsv"), "w") as fh:
        fh.write("family_id\tdisplay_label\tn_assigned\tn_name_matching\t"
                 "n_surface_spellings\tn_exchange_set_compositions\t"
                 "n_quantitative_compositions\tlargest_identical_block\tmember_ids\n")
        for fid, ids in sorted(fam_members.items(), key=lambda x: -len(x[1])):
            ms = [by_id[i] for i in ids]
            surf = {(m.get("name_core") or "").lower() for m in ms}
            exs = {tuple(sorted({c["exchange"] for c in (m.get("components") or [])})) for m in ms}
            qs = collections.Counter(qsig(m) for m in ms)
            fh.write("%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%s\n" % (
                fid, voc.label(fid), len(ids), name_matched.get(fid, len(ids)),
                len(surf), len(exs), len(qs),
                max(qs.values()) if qs else 0, ",".join(sorted(ids))))

    # name collisions: byte-identical core name, differing chemistry
    by_core = collections.defaultdict(list)
    for r in recs:
        by_core[(r.get("category"), (r.get("name_core") or "").strip().lower())].append(r)
    ncol = 0
    with open(os.path.join(a.out, "reports", "name_collisions.tsv"), "w") as fh:
        fh.write("category\tname_core\tn_records\tmin_pairwise_jaccard\tids\tn_components\n")
        for (cat, core), rs in sorted(by_core.items()):
            if len(rs) < 2:
                continue
            sets = [sourced_exchanges(x) for x in rs]
            js = [jaccard(sets[i], sets[j]) or 0.0
                  for i in range(len(sets)) for j in range(i + 1, len(sets))]
            if js and min(js) < 0.999:
                ncol += 1
                fh.write("%s\t%s\t%d\t%.3f\t%s\t%s\n" % (
                    cat, core, len(rs), min(js), ",".join(x["id"] for x in rs),
                    ",".join(str(len(x.get("components") or [])) for x in rs)))

    # composition duplicates: different core name, identical quantitative signature
    ndup = 0
    with open(os.path.join(a.out, "reports", "composition_duplicates.tsv"), "w") as fh:
        fh.write("quantitative_signature\tn_records\tn_distinct_core_names\tids\tnames\n")
        for s, ids in sorted(sig_groups.items(), key=lambda x: -len(x[1])):
            if len(ids) < 2:
                continue
            cores = {(by_id[i].get("name_core") or "").lower() for i in ids if i in by_id}
            if len(cores) < 2:
                continue
            ndup += 1
            fh.write("%s\t%d\t%d\t%s\t%s\n" % (
                s, len(ids), len(cores), ",".join(ids),
                " | ".join(sorted(cores)[:8])))

    with open(os.path.join(a.out, "reports", "unnormalizable.tsv"), "w") as fh:
        fh.write("record_id\tname_core\treason\tdetail\n")
        for row in unnorm:
            fh.write("\t".join(row) + "\n")

    assigned = sum(len(v) for v in fam_members.values())
    rep = {
        "stage": "normalize_names", "stage_version": "1.0",
        "records_in": len(files), "records_out": len(recs),
        "denominator": len(recs),
        "families_in_vocabulary": len(voc.families),
        "families_used": len(fam_members),
        "records_with_family": assigned,
        "records_with_family_pct_of_all": round(100.0 * assigned / len(recs), 2) if recs else None,
        "records_food_family_never_assigned": sum(1 for r in recs if r.get("category") == "food"),
        "counters": dict(stats),
        "name_collision_groups": ncol,
        "composition_duplicate_groups": ndup,
        "largest_families": [
            {"family_id": f, "label": voc.label(f), "n_assigned": len(ids),
             "n_name_matching": name_matched.get(f, len(ids))}
            for f, ids in sorted(fam_members.items(), key=lambda x: -len(x[1]))[:20]],
        "assertion_failures": [{"assertion": x[0], "record": x[1], "detail": x[2]} for x in fails],
        "assertions_passed": not fails,
    }
    json.dump(rep, open(os.path.join(a.out, "reports", "naming_report.json"), "w"), indent=1)
    print(json.dumps({k: rep[k] for k in
                      ("records_out", "families_used", "records_with_family",
                       "records_with_family_pct_of_all", "counters",
                       "name_collision_groups", "composition_duplicate_groups",
                       "largest_families", "assertions_passed")}, indent=1))
    if fails:
        print("\nASSERTION FAILURES (%d):" % len(fails), file=sys.stderr)
        for x in fails[:25]:
            print("  %s %s %s" % x, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
