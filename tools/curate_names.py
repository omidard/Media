#!/usr/bin/env python3
"""
Tidy SHOUTING (all-uppercase) words in laboratory medium names into title case.

DSMZ/literature lab media sometimes arrive fully or partly uppercase
("MARINE AGAR 2216 WITH 8.0% NaCl", "M2-MEDIUM", "DESULFOVIBRIO Medium"). This
title-cases the real English/genus WORDS while leaving everything else exactly
as written:

  - a token keeps its case if it already contains a lowercase letter (NaCl, pH,
    mCDM, an already-tidied "Medium") or a digit (M2, K2HPO4, BG11, 2216, XLT4)
  - a fully-uppercase token is title-cased ONLY if it is a known word/genus in
    WORDS (AGAR->Agar, MARINE->Marine, DESULFOVIBRIO->Desulfovibrio); "with" and
    other small words go lowercase mid-name
  - every other uppercase token is kept verbatim as an acronym/code (MOPS, IPTG,
    HEPES, RPMI, YCFA, CCDA, VRBA, TCBS, PALCAM, ...) — never guessed at

Only `category == "laboratory"` names are touched (USDA food brand names like
"MEAD JOHNSON ENFAMIL" are legitimate trademark casing and are left alone). The
trailing "(DSMZ ...)" / "(standard)" / "(PMC...)" parenthetical is never recased.
The pre-curation name is kept in `name_original` (earliest original preserved).
Idempotent.

Run:  python3 tools/curate_names.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

SMALL = {"of", "and", "with", "the", "for", "in", "on", "to", "a", "an", "or", "per"}

# fully-uppercase tokens that ARE English words / genus / family / brand names
# worth title-casing (everything not here stays verbatim as an acronym/code)
WORDS = {
    "agar", "alifodinibius", "alkaliphiles", "anaerobic", "anoxic", "artificial",
    "bacto", "blood", "brain", "brewer", "briggs", "broth", "caldicellulosiruptor",
    "cherry", "chloroflexus", "columbia", "cytophaga", "delft", "desulfotomaculum",
    "desulfovibrio", "enrichment", "extract", "frankia", "freshwater", "gibco",
    "glucose", "half", "halobacteria", "heart", "heliobacillus", "hyphomicrobium",
    "infusion", "inorganic", "juice", "lactate", "liver", "malt", "marine", "medium",
    "methanococcus", "methanofollis", "methanohalophilus", "methanosalsum",
    "methanosarcina", "methyloceanibacter", "milk", "mineral", "mobilis", "modified",
    "negative", "nutrient", "pirellula", "rhodospirillaceae", "saline", "salt",
    "schaedler", "seawater", "soil", "solution", "spiribacter", "starch", "strain",
    "strength", "sucrose", "sulfide", "synthetic", "syntrophomonas",
    "thermoanaerobacter", "thermococcus", "thermus", "thiobacillus", "thioparus",
    "thiosulfate", "tomato", "trypticase", "yeast",
}


def case_core(c, first):
    if len(c) <= 1:
        return c                                        # single-letter designation (Medium A, part B)
    if any(ch.islower() for ch in c) or any(ch.isdigit() for ch in c):
        return c                                       # NaCl / pH / M2 / already-tidied
    low = c.lower()
    if low in SMALL and not first:
        return low
    if low in WORDS:
        return c[0].upper() + c[1:].lower()            # AGAR -> Agar
    return c                                            # acronym/code kept verbatim


def case_part(p, first):
    if not p:
        return p
    # peel surrounding punctuation so "(NEGATIVE" / "MEDIUM," match on the core
    i, j = 0, len(p)
    while i < j and not p[i].isalnum():
        i += 1
    while j > i and not p[j - 1].isalnum():
        j -= 1
    return p[:i] + case_core(p[i:j], first and i == 0) + p[j:]


def case_token(tok, first):
    # split on - and / (preserving the delimiters) so "THIOSULFATE/2" -> "Thiosulfate/2"
    parts = re.split(r"([-/])", tok)
    out = []
    seen_word = False
    for p in parts:
        if p in ("-", "/"):
            out.append(p); continue
        out.append(case_part(p, first and not seen_word))
        if p:
            seen_word = True
    return "".join(out)


def titlecase(text):
    toks = text.split(" ")
    return " ".join(case_token(t, i == 0) for i, t in enumerate(toks))


def curate(name):
    # protect a trailing parenthetical block e.g. " (DSMZ 1031)" / " (standard)"
    m = re.match(r"^(.*?)(\s*\([^)]*\)\s*)$", name)
    head, tail = (m.group(1), m.group(2)) if m else (name, "")
    new = titlecase(head) + tail
    return new if new != name else None


def main():
    dry = "--dry" in sys.argv
    changed = 0
    samples = []
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        if d.get("category") != "laboratory":
            continue
        nm = d.get("name") or ""
        new = curate(nm)
        if new and new != nm:
            if len(samples) < 20:
                samples.append((nm, new))
            d.setdefault("name_original", nm)
            d["name"] = new
            changed += 1
            if not dry:
                with open(f, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
    print("names curated:", changed)
    for a, b in samples:
        print("  %-46s -> %s" % (a[:46], b[:52]))


if __name__ == "__main__":
    main()
