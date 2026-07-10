#!/usr/bin/env python3
"""
Tidy fully-uppercase medium names (mostly DSMZ) into readable title case.

Conservative and reversible: only names whose alphabetic content (ignoring any
parenthetical like "(DSMZ 1031)") is entirely uppercase are touched, and the
original is preserved in `name_original`. Acronyms (<=3 letters), tokens with
digits, and parenthetical suffixes are kept as-is.

Run:  python3 tools/curate_names.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

SMALL = {"of", "and", "with", "the", "for", "in", "on", "no", "to", "a", "an", "or", "per"}


def case_token(tok, first):
    # keep tokens with digits, acronyms (<=3 upper), or non-alpha as-is
    if any(c.isdigit() for c in tok):
        return tok
    parts = tok.split("-")
    out = []
    for p in parts:
        if not p:
            out.append(p); continue
        if p.isupper() and len(p) <= 3:      # acronym: YMA, CV, TSB, LB
            out.append(p)
        elif p.lower() in SMALL and not first:
            out.append(p.lower())
        else:
            out.append(p[0].upper() + p[1:].lower())
        first = False
    return "-".join(out)


def titlecase(text):
    toks = text.split(" ")
    return " ".join(case_token(t, i == 0) for i, t in enumerate(toks))


def curate(name):
    # split off a trailing parenthetical block e.g. " (DSMZ 1031)"
    m = re.match(r"^(.*?)(\s*\([^)]*\)\s*)$", name)
    head, tail = (m.group(1), m.group(2)) if m else (name, "")
    letters = re.sub(r"[^A-Za-z]", "", head)
    if not letters or not letters.isupper() or len(letters) <= 4:
        return None
    return titlecase(head) + tail


def main():
    dry = "--dry" in sys.argv
    changed = 0
    samples = []
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        nm = d.get("name") or ""
        new = curate(nm)
        if new and new != nm:
            if len(samples) < 10:
                samples.append((nm, new))
            d["name_original"] = nm
            d["name"] = new
            changed += 1
            if not dry:
                with open(f, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
    print("names curated:", changed)
    for a, b in samples:
        print("  %-42s -> %s" % (a[:42], b[:48]))


if __name__ == "__main__":
    main()
