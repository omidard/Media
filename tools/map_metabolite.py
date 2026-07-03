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

class Mapper:
    def __init__(self, base=HERE):
        self.dict = json.load(open(os.path.join(base, "bigg_metabolite_dict.json")))
        ri = json.load(open(os.path.join(base, "bigg_reverse_index.json")))
        self.name_idx = ri["name"]
        self.name_strict = ri["name_strict"]
        self.xref_idx = ri["xref"]           # {inchikey:{...}, chebi:{...}, kegg:{...}, hmdb:{...}, mnx:{...}, seed:{...}}

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
            hits = self.name_idx.get(norm(name)) or self.name_strict.get(re.sub(r"[^a-z0-9]", "", name.lower()))
            if hits:
                best = self._prefer(hits)[0]
                return self._result(best, "name", "inferred")
        return None


if __name__ == "__main__":
    m = Mapper()
    for kw in [dict(name="D-Glucose"), dict(inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N"),
               dict(kegg="C00031"), dict(hmdb="HMDB0000122"), dict(name="L-Tryptophan"),
               dict(chebi="CHEBI:16810"), dict(name="not-a-real-metabolite")]:
        print(kw, "->", m.map(**kw))
