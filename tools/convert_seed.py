#!/usr/bin/env python3
"""Convert the 5 existing cited media into the Media-repo schema, enriching each
component with BiGG name + xrefs, and write the seed data/ tree."""
import json, os, re

WORK = "/tmp/claude-1000/-data-Brilliant-genomics-department/eb8d91f3-1707-45de-a10d-2de68fef6627/scratchpad/media_work"
REPO = os.path.join(WORK, "repo")
os.makedirs(os.path.join(REPO, "data", "media"), exist_ok=True)

DICT = json.load(open(os.path.join(WORK, "bigg_metabolite_dict.json")))
presets = json.load(open("/data/EcopanGEM/docs/fba/media_presets.json"))

# hand-authored provenance for the seed media (impeccable citations)
PROV = {
    "M9_glucose_aerobic": dict(id="m9_glucose_aerobic", name="M9 minimal + glucose (aerobic)",
        category="minimal", organism_scope="prokaryote-generic", aerobic=True,
        description="Standard M9 minimal salts with D-glucose as sole carbon source, aerobic. Mineral exchanges open; glucose and O2 uptake capped at 20 mmol gDW-1 h-1.",
        provenance=dict(source_type="standard", citation="Sambrook J, Russell DW. Molecular Cloning: A Laboratory Manual, 3rd ed. CSHL Press (2001); uptake bounds per iML1515 (Monk et al., Nat Biotechnol 2017).",
            doi="10.1038/nbt.3956", url="http://bigg.ucsd.edu/models/iML1515", notes="Model-default minimal medium; minerals unlimited.")),
    "M9_glucose_anaerobic": dict(id="m9_glucose_anaerobic", name="M9 minimal + glucose (anaerobic)",
        category="minimal", organism_scope="prokaryote-generic", aerobic=False,
        description="M9 minimal salts with D-glucose, O2 removed (fermentative growth).",
        provenance=dict(source_type="standard", citation="Sambrook J, Russell DW. Molecular Cloning, 3rd ed. CSHL Press (2001); iML1515 (Monk et al., Nat Biotechnol 2017), O2 removed.",
            doi="10.1038/nbt.3956", url="http://bigg.ucsd.edu/models/iML1515", notes="Anaerobic M9.")),
    "Feces": dict(id="biospecimen_feces", name="Simulated gut / faecal medium",
        category="biospecimen", organism_scope="gut microbiota", aerobic=False,
        description="Gut-luminal / faecal metabolite environment, HMDB-derived concentrations converted to FBA uptake bounds.",
        provenance=dict(source_type="literature", citation="Ardalani et al. Rare metabolic gene essentiality is a determinant of microniche adaptation in Escherichia coli. PLOS Pathogens (2025); HMDB faecal metabolome (S3 Table).",
            doi="10.1371/journal.ppat.1013775", url="https://journals.plos.org/plospathogens/article?id=10.1371/journal.ppat.1013775", notes="Body-site medium from HMDB-derived tables.")),
    "Urine": dict(id="biospecimen_urine", name="Simulated urine medium",
        category="biospecimen", organism_scope="uropathogen", aerobic=True,
        description="Urine metabolite environment, HMDB-derived concentrations converted to FBA uptake bounds.",
        provenance=dict(source_type="literature", citation="Ardalani et al. PLOS Pathogens (2025); HMDB urine metabolome (S4 Table).",
            doi="10.1371/journal.ppat.1013775", url="https://journals.plos.org/plospathogens/article?id=10.1371/journal.ppat.1013775", notes="Body-site medium from HMDB-derived tables.")),
    "Serum": dict(id="biospecimen_serum", name="Simulated blood / serum medium",
        category="biospecimen", organism_scope="bloodstream pathogen", aerobic=True,
        description="Blood-serum metabolite environment, HMDB-derived concentrations converted to FBA uptake bounds.",
        provenance=dict(source_type="literature", citation="Ardalani et al. PLOS Pathogens (2025); HMDB serum metabolome (S5 Table).",
            doi="10.1371/journal.ppat.1013775", url="https://journals.plos.org/plospathogens/article?id=10.1371/journal.ppat.1013775", notes="Body-site medium from HMDB-derived tables.")),
}

def met_of_exchange(ex):
    # EX_glc__D_e -> glc__D
    m = re.match(r"EX_(.+)_(.)$", ex)
    return m.group(1) if m else ex

def enrich(ex, lb):
    met = met_of_exchange(ex)
    d = DICT.get(met, {})
    return {
        "name": d.get("name", met),
        "bigg_metabolite": met,
        "exchange": ex,
        "lower_bound": lb,
        "upper_bound": 1000.0,
        "concentration_mM": None,
        "xref": d.get("xrefs", {}),
        "in_biggr": d.get("in_biggr", False),
        "mapping_method": "bigg_native",
        "mapping_confidence": "exact",
    }

index = []
for key, meta in PROV.items():
    bounds = presets[key]["bounds"]
    comps = [enrich(ex, lb) for ex, lb in bounds.items()]
    comps.sort(key=lambda c: c["exchange"])
    rec = dict(meta)
    rec.update({
        "components": comps,
        "unmapped": [],
        "n_components": len(comps),
        "n_mapped": sum(1 for c in comps if c["bigg_metabolite"]),
        "n_in_biggr": sum(1 for c in comps if c["in_biggr"]),
        "namespace": "bigg",
        "version": "1.0",
    })
    with open(os.path.join(REPO, "data", "media", rec["id"] + ".json"), "w") as f:
        json.dump(rec, f, indent=1)
    index.append({k: rec[k] for k in ("id", "name", "category", "organism_scope", "aerobic",
                                       "n_components", "n_mapped", "n_in_biggr", "namespace")}
                 | {"source_type": rec["provenance"]["source_type"],
                    "citation": rec["provenance"]["citation"][:120],
                    "doi": rec["provenance"].get("doi", "")})

json.dump({"count": len(index), "media": index}, open(os.path.join(REPO, "data", "index.json"), "w"), indent=1)
print("seed media written:", len(index))
for m in index:
    print(f"  {m['id']:24s} {m['category']:12s} {m['n_components']:3d} comp | {m['n_in_biggr']:3d} in BiGGr | {m['source_type']}")
