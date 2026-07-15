#!/usr/bin/env python3
"""Fetch all MediaDB (ISB) defined media: name, compounds(+bigg/kegg/chebi/pubchem/seed, mM),
is_minimal, and source citations (+PubMed). Saves mediadb_raw.json."""
import re, json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://mediadb.systemsbiology.net/defined_media"
HDR = {"User-Agent": "Mozilla/5.0 (research; media curation)"}

def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception as e:
            if k == tries-1: raise
            time.sleep(1.5*(k+1))

# 1) listing -> [(id, name)]
media = []
for pg in range(1, 6):
    h = get(f"{BASE}/media/page/{pg}")
    for mid, nm in re.findall(r'<a href="/defined_media/media/(\d+)/">\s*([^<]+)</a>', h):
        media.append((int(mid), nm.strip()))
media = sorted(set(media))
print("listing media:", len(media))

# 2) per-media detail (source ids + is_minimal) and media_text (compounds)
def fetch_media(mid):
    d = get(f"{BASE}/media/{mid}/")
    is_min = "Is minimal: Yes" in d
    src_ids = [int(x) for x in re.findall(r"/defined_media/sources/(\d+)/", d)]
    t = get(f"{BASE}/media_text/{mid}/")
    comps = []
    for line in t.splitlines():
        if not line or line.startswith("#"): continue
        p = line.split("\t")
        if len(p) < 2: continue
        name = p[0].strip(); 
        try: amt = float(p[1])
        except: amt = None
        def cell(i): 
            v = p[i].strip() if len(p) > i else ""
            return None if v in ("", "None") else v
        comps.append({"name": name, "mM": amt, "kegg": cell(2), "bigg": cell(3),
                      "seed": cell(4), "pubchem": cell(5), "chebi": cell(6)})
    return mid, {"is_minimal": is_min, "source_ids": src_ids, "compounds": comps}

data = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(fetch_media, mid): (mid, nm) for mid, nm in media}
    done = 0
    for f in as_completed(futs):
        mid, nm = futs[f]
        try:
            _, rec = f.result(); rec["name"] = nm; data[mid] = rec
        except Exception as e:
            print("ERR media", mid, e)
        done += 1
        if done % 100 == 0: print("  media fetched:", done)

# 3) sources -> {id: {citation, pubmed}}
src_ids = sorted({s for r in data.values() for s in r["source_ids"]})
print("unique sources:", len(src_ids))
def fetch_source(sid):
    h = get(f"{BASE}/sources/{sid}/")
    m = re.search(r"<h2>\s*(?:Source:\s*)?([^<]+)</h2>", h)
    cite = (m.group(1).strip() if m else f"MediaDB source {sid}")
    pm = re.search(r"pubmed/(\d+)", h)
    return sid, {"citation": cite, "pubmed": pm.group(1) if pm else None}
sources = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    for f in as_completed([ex.submit(fetch_source, s) for s in src_ids]):
        sid, rec = f.result(); sources[sid] = rec

out = {"media": data, "sources": sources}
json.dump(out, open("mediadb_raw.json", "w"), ensure_ascii=False)
print("saved mediadb_raw.json | media:", len(data), "sources:", len(sources))
# quick coverage stats
nb = sum(1 for r in data.values() for c in r["compounds"] if c["bigg"])
nt = sum(len(r["compounds"]) for r in data.values())
print(f"compounds total {nt} | with bigg_id {nb} ({100*nb//max(nt,1)}%)")
