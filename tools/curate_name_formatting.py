#!/usr/bin/env python3
"""
Normalise media *display names* — remove non-standard formatting artifacts.

Some names carry parsing junk: a leading ". " (e.g. ". Pirellula Medium ..."),
leading/trailing whitespace, double spaces, a space before a comma, or a
lowercase first letter from a mid-sentence extraction. This tidies those
WITHOUT touching legitimate scientific spelling:

  - leading junk (dots/commas/semicolons/whitespace) stripped; leading digits kept (2xYT, 9K)
  - leading/trailing whitespace stripped; internal whitespace runs collapsed to one space
  - " ," / " ;" -> "," / ";" (space-before-punctuation)
  - first letter capitalised ONLY when unambiguous — skipped for:
      * tokens with an internal capital (mCDM, mZMB, mPGM, pH, m-FC, r-RSM, gamma-PGA)
      * Guillard media "f/2", "f/10"
      * surname particle "de" (de Bont medium)
      * single-character first tokens (m TGE ...)

Legitimate non-ASCII (German Ö, chemical middot FeSO4·7H2O, µM, em dash) is left
alone. Short all-caps acronyms (S/W, BG11, MDA) and DSMZ's "Medium (ABBR Medium)"
double-Medium style are left alone (handled/accepted elsewhere).

The pre-curation name is preserved in `name_original` (only set if not already
present, so the earliest original survives repeated curation). Idempotent.

Run:  python3 tools/curate_name_formatting.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

# first tokens whose case must be preserved verbatim
_KEEP_LOWER = {"de", "cis", "trans", "sec", "tert", "ortho", "meta", "para",
               "alpha", "beta", "gamma", "delta", "epsilon", "omega", "pH"}


def _preserve_first_word(name):
    """True if the first whitespace-delimited token must NOT be capitalised."""
    tok = name.split()[0] if name.split() else name
    if len(tok) <= 1:
        return True                                  # single char (m TGE ...)
    if tok.startswith(("f/", "f-")):
        return True                                  # Guillard f/2, f/10
    if any(c.isupper() for c in tok[1:]):
        return True                                  # mCDM, mZMB, pH, m-FC, gamma-PGA
    if tok in _KEEP_LOWER:
        return True                                  # de Bont, cis-, gamma-
    return False


def clean(name):
    if not name:
        return name
    s = name
    # 1) strip leading junk: whitespace and leading . , ; : - (keep letters/digits/parens)
    s = re.sub(r"^[\s.,;:\-]+", "", s)
    # 2) trim + collapse internal whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # 3) remove space before comma/semicolon
    s = re.sub(r"\s+([,;])", r"\1", s)
    # 4) capitalise first letter when unambiguous
    if s and s[0].islower() and not _preserve_first_word(s):
        s = s[0].upper() + s[1:]
    return s


def main():
    dry = "--dry" in sys.argv
    changed = 0
    samples = []
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        old = d.get("name")
        new = clean(old)
        if new != old:
            changed += 1
            if len(samples) < 25:
                samples.append((d["id"], repr(old), repr(new)))
            d.setdefault("name_original", old)       # keep earliest original only
            d["name"] = new
            if not dry:
                with open(f, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
    print(f"names changed: {changed}{'  (dry run — nothing written)' if dry else ''}")
    for i, o, n in samples:
        print(f"  {i}\n     {o}\n  -> {n}")


if __name__ == "__main__":
    main()
