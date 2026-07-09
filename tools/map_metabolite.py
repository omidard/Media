#!/usr/bin/env python3
"""Metabolite -> BiGG exchange mapper for the Media repo.

Maps an external medium component (given a name and/or any cross-reference) to a
standard BiGG universal metabolite and its extracellular exchange reaction
(EX_<id>_e). Every result carries the method used and a confidence level, so all
mappings are auditable. Prefers metabolites present in the local BiGGr reactome.

Usage:
    from map_metabolite import Mapper
    m = Mapper()  # loads tools/bigg_metabolite_dict.json + bigg_reverse_index.json
    hit = m.map(name="D-Glucose", inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N")
    # -> {"bigg_metabolite":"glc__D","exchange":"EX_glc__D_e","name":"D-Glucose",
    #     "in_biggr":True,"mapping_method":"inchikey","mapping_confidence":"exact","xref":{...}}
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))

def norm(s):
    s = (s or "").lower().strip()
    s = re.sub(r"^(l|d|dl)-", "", s)
    return re.sub(r"[^a-z0-9]", "", s)

_FORMULA = re.compile(r"^(?:[A-Z][a-z]?\d*){2,}$")
def strip_formula(name):
    """Drop a trailing molecular-formula token: 'Lactose C12H22O11' -> 'Lactose'."""
    parts = (name or "").rsplit(" ", 1)
    if len(parts) == 2 and any(c.isdigit() for c in parts[1]) and _FORMULA.match(parts[1]):
        return parts[0]
    return name

# common-name -> BiGG id aliases (keyed by norm()). Fixes trivial misses like
# "acetic acid" (->ac), "O2", amino-acid full names, gases, organic acids.
_AA = {"alanine":"ala__L","arginine":"arg__L","asparagine":"asn__L","aspartate":"asp__L","asparticacid":"asp__L",
       "cysteine":"cys__L","glutamate":"glu__L","glutamicacid":"glu__L","glutamine":"gln__L","glycine":"gly",
       "histidine":"his__L","isoleucine":"ile__L","leucine":"leu__L","lysine":"lys__L","methionine":"met__L",
       "phenylalanine":"phe__L","proline":"pro__L","serine":"ser__L","threonine":"thr__L","tryptophan":"trp__L",
       "tyrosine":"tyr__L","valine":"val__L","ornithine":"orn","citrulline":"citr__L"}
_ALIASES = {**_AA,
    # gases / inorganics
    "o2":"o2","oxygen":"o2","dioxygen":"o2","co2":"co2","carbondioxide":"co2","h2":"h2","hydrogen":"h2",
    "n2":"n2","dinitrogen":"n2","h2s":"h2s","hydrogensulfide":"h2s","ch4":"ch4","methane":"ch4","co":"co",
    "carbonmonoxide":"co","no":"no","no2":"no2","no3":"no3","nitrate":"no3","nitrite":"no2","n2o":"n2o",
    "nh3":"nh4","ammonia":"nh4","ammonium":"nh4","h2o":"h2o","water":"h2o","proton":"h","phosphate":"pi",
    # organic acids (name "X acid" or "X-ic acid" -> conjugate base id)
    "aceticacid":"ac","acetate":"ac","aceticacidglacial":"ac","succinicacid":"succ","succinate":"succ",
    "lacticacid":"lac__L","lactate":"lac__L","dllacticacid":"lac__L","propionicacid":"ppa","propionate":"ppa",
    "propanoicacid":"ppa","butyricacid":"but","butyrate":"but","butanoicacid":"but","isobutyricacid":"isobut",
    "formicacid":"for","formate":"for","citricacid":"cit","citrate":"cit","pyruvicacid":"pyr","pyruvate":"pyr",
    "fumaricacid":"fum","fumarate":"fum","malicacid":"mal__L","malate":"mal__L","oxalicacid":"oxa","oxalate":"oxa",
    "gluconicacid":"glcn","gluconate":"glcn","glycolicacid":"glyclt","glycolate":"glyclt","glyoxylicacid":"glx",
    "glyoxylate":"glx","alphaketoglutaricacid":"akg","2oxoglutaricacid":"akg","2oxoglutarate":"akg",
    "ketoglutaricacid":"akg","caproicacid":"hxa","hexanoicacid":"hxa",
    # alcohols / misc products (confident BiGG ids only)
    "ethanol":"etoh","methanol":"meoh","glycerol":"glyc","butanol":"btoh","1butanol":"btoh","nbutanol":"btoh",
    "indole":"indole","urea":"urea","putrescine":"ptrc","cadaverine":"15dap","spermidine":"spmd",
    # sugar-alcohol / sugar synonyms Biolog uses under non-BiGG names
    "dulcitol":"galt","galactitol":"galt","adonitol":"rbt","ribitol":"rbt","myoinositol":"inost",
    "iinositol":"inost","mesoinositol":"inost","dglucosamine":"gam","glucosamine":"gam",
    "nacetylglucosamine":"acgam","nacetyldglucosamine":"acgam","nacetylgalactosamine":"acgal__D",
    "2ketogluconate":"2dhguln","5ketogluconate":"5dglcn","sorbose":"srb__L","dmannitol":"mnl","mannitol":"mnl"}

class Mapper:
    def __init__(self, base=HERE):
        self.dict = json.load(open(os.path.join(base, "bigg_metabolite_dict.json")))
        ri = json.load(open(os.path.join(base, "bigg_reverse_index.json")))
        self.name_idx = ri["name"]
        self.name_strict = ri["name_strict"]
        self.xref_idx = ri["xref"]           # {inchikey:{...}, chebi:{...}, kegg:{...}, hmdb:{...}, mnx:{...}, seed:{...}}
        # keep only aliases whose target id actually exists (avoid mismapping to a bogus id)
        self.aliases = {k: v for k, v in _ALIASES.items() if v in self.dict}
        # index BiGG names with the trailing molecular formula stripped, e.g.
        # "Lactose C12H22O11" -> "lactose". This recovers hundreds of common sugars/substrates.
        self.name_nf = {}
        for bid, rec in self.dict.items():
            nm = strip_formula(rec.get("name", ""))
            k = norm(nm)
            if k:
                self.name_nf.setdefault(k, []).append(bid)

    def _prefer(self, ids):
        """dedupe; prefer BiGGr-present ids, then shortest id (usually the canonical)."""
        seen, uniq = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i); uniq.append(i)
        uniq.sort(key=lambda i: (0 if self.dict.get(i, {}).get("in_biggr") else 1, len(i)))
        return uniq

    def _result(self, bid, method, conf):
        rec = self.dict.get(bid, {})
        return {"bigg_metabolite": bid, "exchange": f"EX_{bid}_e", "name": rec.get("name", bid),
                "in_biggr": rec.get("in_biggr", False), "xref": rec.get("xrefs", {}),
                "mapping_method": method, "mapping_confidence": conf}

    @staticmethod
    def _norm_xref(key, val):
        v = str(val).strip()
        if key == "inchikey": return v.upper()
        if key in ("chebi", "hmdb"): return re.sub(r"\D", "", v).lstrip("0") or "0"
        return v

    def map(self, name=None, inchikey=None, chebi=None, kegg=None, hmdb=None, mnx=None, seed=None):
        # 1) cross-references (exact, most reliable), in order of specificity
        for key, val in (("inchikey", inchikey), ("chebi", chebi), ("kegg", kegg),
                         ("hmdb", hmdb), ("mnx", mnx), ("seed", seed)):
            if not val:
                continue
            bid = self.xref_idx.get(key, {}).get(self._norm_xref(key, val))
            if bid:
                return self._result(bid, key, "exact")
        # 2) name (normalized, then strict)
        if name:
            n = norm(name)
            hits = self.name_idx.get(n) or self.name_strict.get(re.sub(r"[^a-z0-9]", "", name.lower()))
            if hits:
                best = self._prefer(hits)[0]
                return self._result(best, "name", "inferred")
            # 3) alias table (acids, gases, amino acids, common products)
            if n in self.aliases:
                return self._result(self.aliases[n], "name_alias", "inferred")
            # 4) name with trailing molecular formula stripped ("Lactose C12H22O11" -> lactose)
            if n in self.name_nf:
                return self._result(self._prefer(self.name_nf[n])[0], "name_deformula", "inferred")
            # 5) data-driven acid heuristic: "…ic acid" -> try "…ate" / "…oate" via the name index
            m2 = re.match(r"(.+?)ic(?:acid)?$", n)
            if m2:
                stem = m2.group(1)
                for cand in (stem + "ate", stem + "oate"):
                    h = self.name_idx.get(cand)
                    if h:
                        return self._result(self._prefer(h)[0], "name_acid_heuristic", "inferred")
        return None


if __name__ == "__main__":
    m = Mapper()
    for kw in [dict(name="D-Glucose"), dict(inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N"),
               dict(kegg="C00031"), dict(hmdb="HMDB0000122"), dict(name="L-Tryptophan"),
               dict(chebi="CHEBI:16810"), dict(name="not-a-real-metabolite")]:
        print(kw, "->", m.map(**kw))
