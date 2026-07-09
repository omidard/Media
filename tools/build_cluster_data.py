#!/usr/bin/env python3
"""
Precompute hierarchically-clustered views of the presence/absence data for the
Patterns page. Real row + column clustering (SciPy, Ward linkage) is done here,
server-side; the browser just renders the ordered matrices + dendrogram segments.

Outputs -> data/cluster/:
  clustergram.json    - compound x media-group presence-frequency clustergrams,
                        one per group-by axis (source_db / food_group / category);
                        rows (compounds) and columns (groups) both clustered, with
                        dendrogram coordinates for each axis.
  cooccurrence.json    - compound x compound co-occurrence (Jaccard) matrix, clustered,
                        with a single dendrogram (symmetric).

Reads the API parquet exports (built by build_api_exports.py), so run that first.

Rebuild:  python3 tools/build_cluster_data.py
"""
import os
import json

import numpy as np
import pyarrow.parquet as pq
from scipy.cluster.hierarchy import linkage, dendrogram, leaves_list

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
API = os.path.join(REPO, "data", "api")
OUT = os.path.join(REPO, "data", "cluster")
os.makedirs(OUT, exist_ok=True)

# Compound-selection thresholds (fractions of all media).
MIN_PREV = 0.02      # drop near-absent compounds
MAX_PREV = 0.97      # drop near-universal compounds (water, protons, O2, ...)
N_CLUSTERGRAM = 60   # compounds shown in each clustergram
N_COOCCUR = 48       # compounds in the co-occurrence matrix

GROUP_BYS = [
    {"key": "source_db", "label": "Source database", "food_only": False, "max_groups": 12},
    {"key": "food_group", "label": "Food group", "food_only": True, "max_groups": 22},
    {"key": "category", "label": "Category", "food_only": False, "max_groups": 8},
]


def load():
    media = pq.read_table(
        os.path.join(API, "media.parquet"),
        columns=["id", "category", "source_db", "food_group"],
    ).to_pandas()
    comp = pq.read_table(
        os.path.join(API, "components.parquet"),
        columns=["medium_id", "exchange", "name"],
    ).to_pandas()
    comp = comp.dropna(subset=["exchange"]).drop_duplicates(["medium_id", "exchange"])
    return media, comp


def compound_names(comp):
    # most-common human name per exchange
    top = (
        comp.groupby(["exchange", "name"]).size().reset_index(name="n")
        .sort_values("n", ascending=False).drop_duplicates("exchange")
    )
    return dict(zip(top["exchange"], top["name"]))


def label_for(ex, names):
    nm = names.get(ex, ex)
    if len(nm) > 26:
        nm = nm[:25] + "…"
    return {"exchange": ex, "name": nm}


def dendro_payload(Z):
    """Serialize a dendrogram's leaf order + segment coordinates."""
    d = dendrogram(Z, no_plot=True)
    return {
        "order": leaves_list(Z).tolist(),
        "icoord": d["icoord"],   # x coords of each link (leaf axis, units of 10)
        "dcoord": d["dcoord"],   # y coords of each link (distance)
    }


def cluster_axis(matrix):
    """Ward-linkage clustering of the rows of `matrix`. Returns dendro payload."""
    n = matrix.shape[0]
    if n < 3:
        return {"order": list(range(n)), "icoord": [], "dcoord": []}
    Z = linkage(matrix, method="ward", metric="euclidean")
    return dendro_payload(Z)


def build_clustergram(media, comp, names, prevalence, gb):
    key = gb["key"]
    sub = media
    if gb["food_only"]:
        sub = media[media["category"] == "food"]
    labels = sub[["id", key]].copy()
    labels[key] = labels[key].fillna("").replace("", "(unspecified)")

    group_sizes = labels[key].value_counts()
    keep_groups = list(group_sizes.head(gb["max_groups"]).index)
    labels = labels[labels[key].isin(keep_groups)]
    if labels.empty or len(keep_groups) < 2:
        return None

    id2grp = dict(zip(labels["id"], labels[key]))
    cand = [ex for ex, p in prevalence.items() if MIN_PREV <= p <= MAX_PREV]

    # frequency matrix: rows = candidate compounds, cols = groups
    c = comp[comp["medium_id"].isin(id2grp)].copy()
    c["grp"] = c["medium_id"].map(id2grp)
    c = c[c["exchange"].isin(cand)]
    # count of distinct media per (group, exchange)
    hit = c.groupby(["exchange", "grp"])["medium_id"].nunique().unstack(fill_value=0)
    hit = hit.reindex(columns=keep_groups, fill_value=0)
    denom = np.array([group_sizes[g] for g in keep_groups], dtype=float)
    freq = hit.to_numpy(dtype=float) / denom[None, :]
    exchanges = list(hit.index)

    # pick the most discriminating compounds (highest variance across groups)
    var = freq.var(axis=1)
    top_idx = np.argsort(-var)[:N_CLUSTERGRAM]
    top_idx = sorted(top_idx.tolist())
    freq = freq[top_idx, :]
    exchanges = [exchanges[i] for i in top_idx]

    row_d = cluster_axis(freq)
    col_d = cluster_axis(freq.T)
    ro, co = row_d["order"], col_d["order"]
    ordered = freq[np.ix_(ro, co)]

    return {
        "key": key,
        "label": gb["label"],
        "rows": [label_for(exchanges[i], names) for i in ro],
        "cols": [{"name": keep_groups[j], "n": int(group_sizes[keep_groups[j]])} for j in co],
        "matrix": np.round(ordered, 3).tolist(),
        "row_dendro": row_d,
        "col_dendro": col_d,
    }


def build_cooccurrence(media, comp, names, prevalence):
    # interesting band of prevalence -> avoid trivially co-present universals
    cand = sorted(
        [ex for ex, p in prevalence.items() if 0.05 <= p <= 0.90],
        key=lambda e: -prevalence[e],
    )[:N_COOCCUR]
    idx = {ex: i for i, ex in enumerate(cand)}
    n_media = media["id"].nunique()
    mid2row = {m: i for i, m in enumerate(media["id"].tolist())}

    X = np.zeros((n_media, len(cand)), dtype=np.float32)
    c = comp[comp["exchange"].isin(idx)]
    rows = c["medium_id"].map(mid2row).to_numpy()
    cols = c["exchange"].map(idx).to_numpy()
    ok = ~np.isnan(rows)
    X[rows[ok].astype(int), cols[ok].astype(int)] = 1.0

    inter = X.T @ X                      # |a & b|
    diag = np.diag(inter)
    union = diag[:, None] + diag[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        jac = np.where(union > 0, inter / union, 0.0)
    np.fill_diagonal(jac, 1.0)

    dist = 1.0 - jac
    condensed = dist[np.triu_indices(len(cand), k=1)]
    Z = linkage(condensed, method="average")
    order = leaves_list(Z).tolist()
    d = dendro_payload(Z)
    ordered = jac[np.ix_(order, order)]

    return {
        "labels": [label_for(cand[i], names) for i in order],
        "matrix": np.round(ordered, 3).tolist(),
        "dendro": d,
    }


def main():
    media, comp = load()
    names = compound_names(comp)
    n_media = media["id"].nunique()
    prevalence = (
        comp.groupby("exchange")["medium_id"].nunique() / n_media
    ).to_dict()
    print("media:", n_media, "distinct exchanges:", len(prevalence))

    clustergrams = []
    for gb in GROUP_BYS:
        cg = build_clustergram(media, comp, names, prevalence, gb)
        if cg:
            clustergrams.append(cg)
            print("clustergram[%s]: %d compounds x %d groups"
                  % (gb["key"], len(cg["rows"]), len(cg["cols"])))

    with open(os.path.join(OUT, "clustergram.json"), "w") as fh:
        json.dump({"views": clustergrams}, fh, separators=(",", ":"))

    co = build_cooccurrence(media, comp, names, prevalence)
    with open(os.path.join(OUT, "cooccurrence.json"), "w") as fh:
        json.dump(co, fh, separators=(",", ":"))
    print("cooccurrence: %d x %d compounds" % (len(co["labels"]), len(co["labels"])))

    for f in ("clustergram.json", "cooccurrence.json"):
        p = os.path.join(OUT, f)
        print("  data/cluster/%-20s %.1f KB" % (f, os.path.getsize(p) / 1024))


if __name__ == "__main__":
    main()
