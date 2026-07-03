#!/usr/bin/env python3
"""Stream HMDB metabolites XML -> one biospecimen medium per biofluid, from NORMAL
concentrations. Maps each metabolite to BiGG (own bigg_id -> InChIKey -> KEGG -> name),
converts concentrations to mM where possible, keeps PubMed citations."""
import zipfile, xml.etree.ElementTree as ET, json, os, re, sys, statistics
sys.path.insert(0, "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo/tools")
from map_metabolite import Mapper

REPO = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/repo"
OUT = os.path.join(REPO, "data", "media")
DICT = json.load(open(os.path.join(REPO, "tools", "bigg_metabolite_dict.json")))
mp = Mapper()
lt = lambda t: t.split('}')[-1]
def txt(el, tag):
    x = el.find('{*}'+tag); return x.text if x is not None else None

BAD = re.compile(r"(coa$|_coa|trna|\[protein|acp\b|ferredoxin|flavodoxin|thioredoxin)", re.I)
def first_num(s):
    if not s: return None
    m = re.search(r"[-+]?\d*\.?\d+", s.replace(",", ""))
    return float(m.group(0)) if m else None
def to_mM(val, units, mw):
    if val is None or not units: return None
    u = units.strip().lower()
    if u in ("um","umol/l","µm","micromolar"): return val/1000.0
    if u in ("nm","nmol/l"): return val/1e6
    if u in ("mm","mmol/l"): return val
    if u in ("m","mol/l"): return val*1000.0
    if u in ("pm","pmol/l"): return val/1e9
    if mw and mw>0:
        if u in ("mg/l","ug/ml","µg/ml"): return (val/mw)          # mg/L / (g/mol) = mmol/L
        if u in ("ug/l","µg/l","ng/ml"): return (val/1000.0/mw)
        if u in ("mg/dl",): return (val*10.0/mw)
        if u in ("mg/ml","g/l"): return (val*1000.0/mw)
    return None

def map_met(name, ik, kegg, chebi, hmdb_acc, bigg_id):
    # prefer the metabolite's own bigg_id if it exists in our reactome
    if bigg_id:
        b = bigg_id.strip()
        if b in DICT and DICT[b]["in_biggr"]:
            return {"bigg_metabolite": b, "exchange": f"EX_{b}_e", "name": DICT[b]["name"],
                    "in_biggr": True, "xref": DICT[b]["xrefs"], "mapping_method": "hmdb_bigg_id", "mapping_confidence": "exact"}
    hit = mp.map(name=name, inchikey=ik, kegg=kegg, chebi=chebi, hmdb=hmdb_acc)
    return hit if (hit and hit["in_biggr"]) else None

MINERALS = {"EX_pi_e":-1000,"EX_so4_e":-1000,"EX_nh4_e":-1000,"EX_k_e":-1000,"EX_na1_e":-1000,
  "EX_cl_e":-1000,"EX_mg2_e":-1000,"EX_ca2_e":-1000,"EX_fe2_e":-1000,"EX_fe3_e":-1000,
  "EX_mn2_e":-1000,"EX_zn2_e":-1000,"EX_cu2_e":-1000,"EX_cobalt2_e":-1000,"EX_h2o_e":-1000,"EX_h_e":-1000,"EX_o2_e":-10}

# biospecimen -> exchange -> {concs:[mM], name, xref, method, conf, orig:[(val,units)], pmids:set}
bio = {}
z = zipfile.ZipFile('/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work/bmdb/bmdb_metabolites.zip')
xmlname = [i.filename for i in z.infolist() if i.filename.endswith('.xml')][0]
ctx = ET.iterparse(z.open(xmlname), events=('end',))
n=0; nmapped=0
for ev, el in ctx:
    if lt(el.tag) != 'metabolite':
        continue
    n += 1
    nc = None
    for c in el:
        if lt(c.tag) == 'normal_concentrations': nc = c
    if nc is not None and len(list(nc)):
        name=txt(el,'name'); ik=txt(el,'inchikey'); kegg=txt(el,'kegg_id'); chebi=txt(el,'chebi_id')
        acc=txt(el,'accession'); bigg=txt(el,'bigg_id')
        try: mw=float(txt(el,'average_molecular_weight') or 0)
        except: mw=0
        hit = map_met(name, ik, kegg, chebi, acc, bigg)
        if hit and not BAD.search(hit["name"]) and not BAD.search(hit["bigg_metabolite"]):
            nmapped += 1
            ex = hit["exchange"]
            for conc in nc:
                if txt(conc,'subject_condition') not in ('Normal', None): continue
                val = first_num(txt(conc,'concentration_value'))
                units = txt(conc,'concentration_units')
                bs = (txt(conc,'biospecimen') or '').strip()
                if not bs: continue
                mM = to_mM(val, units, mw)
                pmids=set()
                refs = conc.find('{*}references')
                if refs is not None:
                    for r in refs:
                        pm = txt(r,'pubmed_id')
                        if pm: pmids.add(pm.strip())
                d = bio.setdefault(bs, {}).setdefault(ex, {"concs":[], "name":hit["name"], "xref":hit["xref"],
                       "method":hit["mapping_method"], "conf":hit["mapping_confidence"], "orig":[], "pmids":set()})
                if mM is not None: d["concs"].append(mM)
                if val is not None: d["orig"].append((val, units))
                d["pmids"].update(pmids)
    el.clear()

print(f"metabolites scanned: {n} | mapped w/ normal concentrations: {nmapped}")
print("biospecimens found:", sorted((k, len(v)) for k,v in bio.items()))

def slug(s): return re.sub(r"[^a-z0-9]+","_", s.lower()).strip("_")
BS_META = {
 "Rumen":("rumen microbiota", False), "Milk":("dairy / mastitis", True), "Colostrum":("neonatal gut", False),
 "Blood":("bovine bloodstream", True), "Urine":("bovine urinary", True), "Feces":("bovine gut", False),
}
FLUIDS={"Rumen","Milk","Colostrum","Blood","Urine","Feces"}
written=[]
for bs, comps in bio.items():
    if bs not in FLUIDS or len(comps) < 8: continue
    scope, aer = BS_META.get(bs, ("host-associated", True))
    components=[]
    allpm=set()
    for ex in sorted(set(list(comps.keys())+list(MINERALS.keys()))):
        b = re.match(r"EX_(.+)_e$", ex); bid = b.group(1) if b else ex
        d = comps.get(ex)
        if d:
            mM = round(statistics.median(d["concs"]),4) if d["concs"] else None
            allpm.update(list(d["pmids"])[:3])
            components.append({"name": d["name"], "bigg_metabolite": bid, "exchange": ex,
                "lower_bound": -1.0, "upper_bound": 1000.0, "concentration_mM": mM,
                "hmdb_orig": (str(d["orig"][0][0])+" "+str(d["orig"][0][1]) if d["orig"] else None),
                "xref": d["xref"], "in_biggr": True,
                "mapping_method": d["method"], "mapping_confidence": d["conf"]})
        else:
            dd = DICT.get(bid, {})
            components.append({"name": dd.get("name",bid), "bigg_metabolite": bid, "exchange": ex,
                "lower_bound": MINERALS[ex], "upper_bound":1000.0, "concentration_mM":None,
                "xref": dd.get("xrefs",{}), "in_biggr": dd.get("in_biggr",False),
                "mapping_method":"mineral_base","mapping_confidence":"convention"})
    norg = sum(1 for c in components if c["mapping_method"] not in ("mineral_base",))
    pmlist = sorted(allpm)[:10]
    rec={"id":"biospecimen_bmdb_"+slug(bs),
         "name":f"Bovine {bs} (BMDB normal metabolome)","category":"biospecimen",
         "organism_scope":scope,"aerobic":aer,
         "description":f"Bovine {bs} medium from the Bovine Metabolome Database (BMDB) normal (healthy-subject) metabolite concentrations, mapped to BiGG exchanges, with a mineral base. Concentrations are medians of reported normal values (concentration_mM); original HMDB values retained per component.",
         "namespace":"bigg",
         "provenance":{"source_type":"database",
            "citation":f"Bovine Metabolome Database (BMDB; Foroutan A et al., 2020, bovinedb.ca), normal bovine {bs} concentrations."+(f" Primary refs PMID: {', '.join(pmlist)}." if pmlist else ""),
            "doi":"10.3390/metabo10060233","url":"https://bovinedb.ca","notes":"Normal-condition concentrations only; medians across reports; units converted to mM where MW/units allowed. Presence-based uptake bounds; concentration_mM + hmdb_orig retained. Mineral base added."},
         "components":components,"unmapped":[],
         "n_components":len(components),"n_mapped":len(components),
         "n_in_biggr":sum(1 for c in components if c["in_biggr"]),
         "n_bio_components":norg,"version":"1.0"}
    json.dump(rec, open(os.path.join(OUT, rec["id"]+".json"),"w"))
    written.append((rec["id"], norg))
print("BMDB bovine biospecimen media written:")
for i,c in sorted(written, key=lambda x:-x[1]): print(f"  {i:36s} {c} components")
