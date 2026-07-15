#!/usr/bin/env python3
"""Resolve real DOIs (via Crossref) for expert-curated std_/seed media whose reference
is plain text with no DOI. Strict acceptance: returned item's year must match the
reference year and the first-author surname must appear in the item's authors.
Writes resolved_dois.json {id: {doi, url, title}}."""
import os, re, sys, json, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.join(HERE, "..", "repo")
import glob
MAIL = "omidard@biosustain.dtu.dk"
DOI = re.compile(r'10\.\d{4,9}/[^\s;,)]+')

def ref_text(p):
    return p.get("wellknown_reference") or p.get("citation") or ""

def clean_query(ref):
    # drop the "Medium name — " prefix; keep the citation (author. journal year;vol:page)
    q = ref.split("—", 1)[1] if "—" in ref else ref
    q = re.sub(r"\s+", " ", q).strip()
    return q[:300]

def first_author(q):
    m = re.match(r"\s*([A-Z][a-zA-Z\-']+)", q)
    return m.group(1).lower() if m else None

def year_of(q):
    m = re.search(r"\b(18|19|20)\d{2}\b", q)
    return int(m.group(0)) if m else None

def crossref(q):
    url = ("https://api.crossref.org/works?rows=3&mailto=" + MAIL +
           "&query.bibliographic=" + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": f"MediaCuration/1.0 (mailto:{MAIL})"})
    for k in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())["message"]["items"]
        except Exception:
            if k == 2: return []
            time.sleep(1.5*(k+1))

def resolve(mid, ref):
    # 1) DOI already in text
    m = DOI.search(ref)
    if m:
        d = m.group(0).rstrip(".")
        return mid, {"doi": d, "url": f"https://doi.org/{d}", "title": None, "how": "in_text"}
    q = clean_query(ref)
    yr, au = year_of(q), first_author(q)
    # org-only references (no author/year) -> not resolvable to a paper
    if not yr or not au or re.search(r"\b(standard|ATCC/DSMZ|BD/|Oxoid|Difco|CLSI|APHA|USP|ISO)\b", q) and not re.search(r"\b[A-Z][a-z]+ [A-Z]{1,3}\b", q):
        if not yr or not au:
            return mid, None
    items = crossref(q)
    for it in items:
        iy = None
        for key in ("published-print", "published-online", "issued"):
            dp = (it.get(key) or {}).get("date-parts") or [[None]]
            if dp and dp[0] and dp[0][0]: iy = dp[0][0]; break
        authors = " ".join((a.get("family", "") + " " + a.get("given", "")) for a in it.get("author", [])).lower()
        title = " ".join(it.get("title") or [])
        if iy and abs(iy - yr) <= 1 and au in authors:
            d = it.get("DOI", "").rstrip(".")
            if d:
                return mid, {"doi": d, "url": f"https://doi.org/{d}", "title": title[:120], "how": "crossref"}
    return mid, None

def main():
    media = {}
    for f in glob.glob(os.path.join(REPO, "data/media/std_*.json")) + \
             glob.glob(os.path.join(REPO, "data/media/m9_*.json")) + \
             glob.glob(os.path.join(REPO, "data/media/m63_*.json")) + \
             glob.glob(os.path.join(REPO, "data/media/davis*.json")) + \
             glob.glob(os.path.join(REPO, "data/media/mops_*.json")):
        d = json.load(open(f)); media[d["id"]] = ref_text(d.get("provenance") or {})
    out = {}; n = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(resolve, mid, ref) for mid, ref in media.items() if ref]
        for fu in as_completed(futs):
            mid, res = fu.result(); n += 1
            if res: out[mid] = res
            if n % 50 == 0: print("  resolved:", n)
    json.dump(out, open(os.path.join(HERE, "resolved_dois.json"), "w"), ensure_ascii=False, indent=0)
    intext = sum(1 for v in out.values() if v["how"] == "in_text")
    cr = sum(1 for v in out.values() if v["how"] == "crossref")
    print(f"media checked: {len(media)} | resolved: {len(out)} (in-text {intext}, crossref {cr}) | unresolved: {len(media)-len(out)}")
    print("samples:", {k: out[k]["doi"] for k in list(out)[:8]})

if __name__ == "__main__":
    main()
