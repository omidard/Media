#!/usr/bin/env python3
"""
refs — the corpus's one string/reference lookup layer.

WHY THIS EXISTS
---------------
GitHub Pages publishes this repository's root and refuses to publish a site over
1 GiB. After the remediation the tracked tree measured 1,597.8 MiB, of which
data/media alone was 1,382.3 MiB, and a byte census over all 13,515 records
(665,582 components) attributed that as follows:

    247.2 MiB  components[].target_xref     2,287 distinct blobs, 291x repeated
    242.8 MiB  components[].xref            byte-identical to target_xref in
                                            665,582 of 665,582 (100.00%)
     89.8 MiB  components[].target_xref_note  ONE sentence, on 654,067 components
     71.2 MiB  components[].mapping_note    113 distinct strings, on 621,274
     21.1 MiB  components[].quantity_basis  == quantity.basis in 665,582/665,582
     11.8 MiB  usda_amount / usda_unit      == quantity.value / .unit in
                                            268,697 of 268,697, type-exact

None of that is information. It is the same handful of strings written out
hundreds of thousands of times. This module holds the *facts* exactly once, in
data/refs.json, and the corpus refers to them by key. Nothing was deleted: every
byte removed from a component is reconstructible from this table, and
``resolve_component`` is the function that does it. tests/test_refs.py asserts
the round trip over the whole corpus.

THE JOIN
--------
    components[].xref_id          -> refs["xrefs"][id]   (dict of cross-references)
    components[].xref_note_id     -> refs["notes"][id]   (verbatim sentence)
    components[].mapping_note_id  -> refs["notes"][id]   (verbatim sentence)

An ABSENT ``xref_id`` means the component has no cross-references at all
(resolve to ``{}``) — it never means "look it up somewhere else". An absent
note id means the component carried no such note. This distinction is the
reason the table is keyed rather than defaulted.

Dropped outright, because they were type-exact copies of a field that is still
present on the same component:

    quantity_basis  == (quantity or {})["basis"]
    usda_amount     == (quantity or {})["value"]
    usda_unit       == (quantity or {})["unit"]

``resolve_component`` restores those too, so a consumer that wants the flat
pre-deduplication record gets it back byte-for-byte.

KEY SHAPE
---------
An xref key is the BiGG metabolite id when that id has exactly one distinct
cross-reference block in the corpus (581 of 1,133 ids), and ``<bigg>~<hash>``
when the corpus holds more than one — which it does for 552 ids, because some
records carry a richer snapshot of the same metabolite (with ``formula`` and
``inchi``) than others. The keys are therefore content-addressed and readable,
and a reader can see at a glance which metabolite a block describes. A note key
is ``n<hash>``. Hashes are sha1 over canonical JSON; collisions are asserted
against, never assumed away.
"""
from __future__ import annotations

import hashlib
import json
import os

__all__ = [
    "REFS_FILENAME", "SCHEMA", "canonical", "note_id", "build_tables",
    "load_refs", "resolve_component", "resolve_record", "dedupe_component",
    "XREF_FIELDS_REMOVED", "DERIVED_FROM_QUANTITY",
]

REFS_FILENAME = "refs.json"
SCHEMA = "mediadb-reference-tables/1"

#: component fields whose value now lives in data/refs.json
XREF_FIELDS_REMOVED = ("xref", "target_xref", "target_xref_note", "mapping_note")

#: component field -> the key inside ``quantity`` it was a type-exact copy of.
#:
#: Each of these is redundant BY CONSTRUCTION, not by coincidence: stage 50 built
#: ``quantity`` out of ``usda_amount``/``usda_unit`` and records that lineage in
#: ``quantity.source_field``, and ``quantity_basis`` is the same field under two
#: names. Measured on the corpus: equal and same-typed in 665,582 of 665,582 and
#: 268,697 of 268,697 components respectively.
#:
#: ``amount_basis`` is DELIBERATELY NOT HERE, and that is the interesting one. It
#: also equals ``quantity.basis`` on all 268,697 components that carry it — but it
#: is the basis label of ``amount_mmol_per_100g``, a different measurement from
#: ``quantity.value``. The two agreeing is a property of this corpus, not of the
#: schema: a record whose USDA amount was per litre while the mmol figure stayed
#: per 100 g would be silently relabelled. 9.2 MiB is not worth a field that means
#: one thing and would be restored from another.
DERIVED_FROM_QUANTITY = {
    "quantity_basis": "basis",
    "usda_amount": "value",
    "usda_unit": "unit",
}


def canonical(obj) -> str:
    """Stable text for hashing and equality. Key order never matters here."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _h(text: str, n: int) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def note_id(text: str) -> str:
    return "n" + _h(text, 6)


# --------------------------------------------------------------------- build


def build_tables(records) -> dict:
    """Build the reference tables from an ITERABLE of full medium records.

    Streams: it retains the distinct blocks and sentences, never the records, so
    a 1.4 GB corpus costs about a megabyte here. The key for a cross-reference
    block depends on whether its BiGG id has one block in the corpus or several,
    which is not knowable until the whole corpus has been read — so key
    assignment happens after the scan, not during it. Assigning per-record would
    produce keys that depend on iteration order.
    """
    by_bigg: dict[str, dict[str, object]] = {}
    notes: dict[str, str] = {}
    for rec in records:
        for c in rec.get("components") or []:
            xr = c.get("target_xref")
            if xr is None:
                xr = c.get("xref")
            if xr:
                by_bigg.setdefault(c.get("bigg_metabolite") or "", {})[canonical(xr)] = xr
            for field in ("target_xref_note", "mapping_note"):
                t = c.get(field)
                if isinstance(t, str) and t:
                    # A truncated hash that mapped two different sentences to one
                    # key would silently rewrite a note. Asserted, not hoped for.
                    k = note_id(t)
                    if notes.setdefault(k, t) != t:
                        raise ValueError(
                            "note id collision on %s: %r and %r hash to the same key; "
                            "widen the hash in refs.note_id" % (k, notes[k], t))

    # key assignment
    xrefs: dict[str, object] = {}
    key_of: dict[tuple, str] = {}
    for bigg in sorted(by_bigg):
        blobs = by_bigg[bigg]
        if len(blobs) == 1 and bigg:
            (cj, xr), = blobs.items()
            xrefs[bigg] = xr
            key_of[(bigg, cj)] = bigg
        else:
            for cj in sorted(blobs):
                key = ("%s~%s" % (bigg, _h(cj, 4))) if bigg else ("~" + _h(cj, 6))
                if key in xrefs and canonical(xrefs[key]) != cj:
                    raise ValueError("xref key collision on %s; widen the hash" % key)
                xrefs[key] = blobs[cj]
                key_of[(bigg, cj)] = key

    return {
        "schema": SCHEMA,
        "built_by": "tools/stages/60_dedupe_references.py",
        "doc": (
            "Cross-reference blocks and prose notes held once, referenced by key "
            "from data/media/<id>.json. Join components[].xref_id on 'xrefs'; join "
            "components[].xref_note_id and components[].mapping_note_id on 'notes'. "
            "An absent xref_id means the component has no cross-references, not "
            "that they live elsewhere. tools/refs.py:resolve_component() performs "
            "the join and reconstructs the flat record exactly."),
        "joins": {
            "components[].xref_id": "xrefs",
            "components[].xref_note_id": "notes",
            "components[].mapping_note_id": "notes",
        },
        "xref_semantics": (
            "A cross-reference block describes the BiGG id that was CHOSEN for the "
            "component. Whether it was also the evidence for that choice is stated "
            "per component by match_field / match_key / source_xref, and by the note "
            "referenced from xref_note_id, not by this table."),
        "n_xrefs": len(xrefs),
        "n_notes": len(notes),
        "xrefs": xrefs,
        "notes": dict(sorted(notes.items())),
        "_key_of": key_of,          # build-time only; stripped before writing
    }


def write_refs(tables: dict, path: str) -> int:
    """Write data/refs.json. Returns the byte size written."""
    out = {k: v for k, v in tables.items() if not k.startswith("_")}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return os.path.getsize(path)


# ------------------------------------------------------------------ dedupe


def dedupe_component(c: dict, key_of: dict) -> bool:
    """Rewrite one component in place to refer to the tables. True iff changed.

    Idempotent: a component that already carries ``xref_id`` and no ``xref`` is
    left untouched, so re-running the stage over its own output is a no-op.
    """
    changed = False

    xr = c.get("target_xref")
    if xr is None:
        xr = c.get("xref")
    if "xref" in c or "target_xref" in c:
        c.pop("xref", None)
        c.pop("target_xref", None)
        changed = True
        if xr:
            c["xref_id"] = key_of[(c.get("bigg_metabolite") or "", canonical(xr))]

    for field, id_field in (("target_xref_note", "xref_note_id"),
                            ("mapping_note", "mapping_note_id")):
        if field in c:
            t = c.pop(field)
            changed = True
            if isinstance(t, str) and t:
                c[id_field] = note_id(t)

    # A quantity copy is dropped only when it is EXACTLY reconstructible, which
    # takes three things at once, all checked here rather than assumed:
    #   * the component carries a `quantity` key, so `(quantity or {})[k]` is the
    #     defined way back (on the pre-remediation corpus, before stage 50, there
    #     is no `quantity` at all and `usda_amount` is the only copy that exists —
    #     dropping it there would destroy the measurement);
    #   * for the three amount_*/usda_* copies, `amount_source` is present, because
    #     that is the marker resolve_component() restores them on;
    #   * the values are equal AND the same type.
    # Anything else is left in place. This is not a fallback: it is why the stage
    # can be run over any corpus shape without losing a number.
    q = c.get("quantity")
    qd = q if isinstance(q, dict) else {}
    if "quantity" in c:
        for field, qkey in DERIVED_FROM_QUANTITY.items():
            if field not in c:
                continue
            if field != "quantity_basis" and "amount_source" not in c:
                continue
            if c[field] != qd.get(qkey) or type(c[field]) is not type(qd.get(qkey)):
                raise ValueError(
                    "%s=%r is not a copy of quantity.%s=%r on this component; it "
                    "carries information and must not be dropped"
                    % (field, c[field], qkey, qd.get(qkey)))
            del c[field]
            changed = True

    return changed


# ----------------------------------------------------------------- resolve


def load_refs(repo_or_path: str) -> dict:
    """Load data/refs.json given a repo root or a direct path to the file."""
    path = repo_or_path
    if os.path.isdir(path):
        path = os.path.join(path, "data", REFS_FILENAME)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_component(c: dict, refs: dict, flat: bool = True) -> dict:
    """Return the component with every deduplicated field restored.

    ``flat=True`` reconstructs the pre-deduplication shape exactly, including the
    ``xref`` alias, so that a consumer written against the old record and a
    consumer written against the new one see the same bytes. ``flat=False``
    restores the values but not the alias.
    """
    out = dict(c)
    xid = out.pop("xref_id", None)
    xr = refs["xrefs"][xid] if xid is not None else {}
    out["target_xref"] = xr
    if flat:
        out["xref"] = xr

    nid = out.pop("xref_note_id", None)
    if nid is not None:
        out["target_xref_note"] = refs["notes"][nid]
    nid = out.pop("mapping_note_id", None)
    if nid is not None:
        out["mapping_note"] = refs["notes"][nid]

    # The mirror image of dedupe_component's rule: restored only where it was
    # droppable, and never over a value the component still carries.
    q = out.get("quantity")
    qd = q if isinstance(q, dict) else {}
    if flat and "quantity" in out:
        out.setdefault("quantity_basis", qd.get("basis"))
        if out.get("amount_source") is not None:
            out.setdefault("usda_amount", qd.get("value"))
            out.setdefault("usda_unit", qd.get("unit"))
    return out


#: `flat=True` always materialises both names for the cross-reference block. On the
#: shipped corpus both were present on 665,582 of 665,582 components, so the restore
#: is exact; on the pre-remediation corpus only `xref` existed, so restoring adds
#: `target_xref`. That is the ONLY field a restore is allowed to add, and
#: roundtrip_diff enforces it rather than tolerating a general mismatch.
ALIAS_FIELDS = {"xref", "target_xref"}


def roundtrip_diff(before: dict, restored: dict) -> list:
    """Real differences between a component and its restored form. [] means none.

    Strict: every key the original carried must come back with the identical value.
    The only slack is that `flat=True` may ADD one of the two interchangeable names
    for the cross-reference block, and only when its value equals the block the
    original carried under the other name.
    """
    bad = []
    for k, v in before.items():
        if k not in restored:
            bad.append("missing:" + k)
        elif restored[k] != v or type(restored[k]) is not type(v):
            bad.append("changed:" + k)
    for k in restored:
        if k in before:
            continue
        if k not in ALIAS_FIELDS:
            bad.append("added:" + k)
        else:
            other = (ALIAS_FIELDS - {k}).pop()
            if other not in before or before[other] != restored[k]:
                bad.append("added:" + k)
    return bad


def resolve_record(rec: dict, refs: dict, flat: bool = True) -> dict:
    out = dict(rec)
    out["components"] = [resolve_component(c, refs, flat=flat)
                         for c in rec.get("components") or []]
    return out


def component_xref(c: dict, refs: dict) -> dict:
    """The component's cross-reference block. ``{}`` when it has none.

    An ``xref_id`` the table cannot resolve is FATAL, never an empty dict. The
    whole point of moving these blocks out of the corpus is that they are still
    there; a builder that silently substituted ``{}`` would ship a components
    table with every cross-reference column blank and no error anywhere.
    """
    xid = c.get("xref_id")
    if xid is None:
        # a corpus that has not been through stage 60 still carries them inline
        return c.get("target_xref") or c.get("xref") or {}
    try:
        return refs["xrefs"][xid]
    except KeyError:
        raise KeyError(
            "component %r carries xref_id=%r which is not in the reference table "
            "(%d keys). data/refs.json and data/media are out of step — rebuild "
            "with `make refs-verify` to see which." % (c.get("name"), xid,
                                                       len(refs.get("xrefs") or {})))


def component_note(c: dict, refs: dict, field: str = "mapping_note") -> str | None:
    """The component's ``mapping_note`` / ``target_xref_note``, or None."""
    id_field = {"mapping_note": "mapping_note_id",
                "target_xref_note": "xref_note_id"}[field]
    nid = c.get(id_field)
    if nid is None:
        return c.get(field)
    try:
        return refs["notes"][nid]
    except KeyError:
        raise KeyError(
            "component %r carries %s=%r which is not in the reference table; "
            "data/refs.json and data/media are out of step"
            % (c.get("name"), id_field, nid))
