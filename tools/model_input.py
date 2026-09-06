#!/usr/bin/env python3
"""The model input a medium record produces, and how many records produce the same one.

FINDING: the audit measured that half this library is degenerate as a *model input*.
Two records can carry different names, different citations, different sources and
different licences and still hand a genome-scale model the identical constraint set.
A user choosing between two media deserves to know they are choosing between two
labels on one experiment.

WHAT A "MODEL INPUT" IS HERE
----------------------------
The documented way to use a record is

    model.medium = {c["exchange"]: -c["lower_bound"] for c in med["components"]
                    if c["exchange"] in model.reactions}

so what actually reaches the solver is the set of (exchange, lower_bound,
upper_bound) triples. Name, description, provenance, citation, licence, oxygen
label and every cross-reference are dropped on the way in. `signature()` hashes
exactly what survives that projection, and nothing else.

Concentrations are deliberately NOT in the primary signature, because no line of
the documented adoption path reads them. They are measured separately
(`signature_with_concentrations`) so the resource can state both numbers: how many
records are indistinguishable to a solver, and how many remain indistinguishable
even to a reader who also inspects the source-stated concentrations.

This module is the single definition. build_index.py and tools/web_payload.py both
import it, so the catalog, the browser payload and the bulk exports cannot disagree
about which records are twins.
"""
from __future__ import annotations

import collections
import hashlib
import json

# Stated on every artifact that carries a count derived from this module, so the
# number is never a bare adjective.
PRIMARY_DEFINITION = (
    "Two records share a model input when the set of (exchange reaction, lower "
    "bound, upper bound) triples they hand a model is identical. That set is "
    "everything the documented COBRApy adoption path reads; the name, the source, "
    "the citation and the licence are not part of it. Records sharing one are "
    "indistinguishable to a solver, not merely similar.")

CONCENTRATION_DEFINITION = (
    "The same comparison with each component's source-stated concentration added "
    "to the tuple. It is the stricter test: a pair that still collides here is "
    "identical even to a reader who inspects the amounts, not only the bounds.")


def _hash(rows) -> str:
    return hashlib.sha256(
        json.dumps(sorted(rows), default=str).encode("utf-8")).hexdigest()[:16]


def signature(rec: dict) -> str:
    """Hash of the constraint set this record hands a model."""
    return _hash({(c.get("exchange"), c.get("lower_bound"), c.get("upper_bound"))
                  for c in rec.get("components") or [] if c.get("exchange")})


def signature_with_concentrations(rec: dict) -> str:
    """The stricter signature: bounds AND source-stated concentrations."""
    return _hash({(c.get("exchange"), c.get("lower_bound"), c.get("upper_bound"),
                   c.get("concentration_mM"))
                  for c in rec.get("components") or [] if c.get("exchange")})


class Degeneracy:
    """Accumulates signatures across a corpus and reports the collisions.

    Usage is two-pass by construction: a caller adds every record, then asks for
    the group of any one of them. That is deliberate — a per-record answer cannot
    be honest until the whole corpus has been read, and a builder that emitted the
    field in one pass would be reporting a subset's degeneracy as the library's.
    """

    def __init__(self):
        self._sig: dict[str, str] = {}
        self._sig_conc: dict[str, str] = {}
        self._members: dict[str, list[str]] = collections.defaultdict(list)
        self._members_conc: dict[str, list[str]] = collections.defaultdict(list)

    def add(self, rec: dict) -> str:
        mid = rec["id"]
        sig = signature(rec)
        sig_c = signature_with_concentrations(rec)
        self._sig[mid] = sig
        self._sig_conc[mid] = sig_c
        self._members[sig].append(mid)
        self._members_conc[sig_c].append(mid)
        return sig

    # -- per record ---------------------------------------------------------
    def signature_of(self, mid: str) -> str:
        return self._sig[mid]

    def twins(self, mid: str) -> list[str]:
        """The OTHER records with the identical model input, sorted. May be empty."""
        return [m for m in sorted(self._members[self._sig[mid]]) if m != mid]

    def n_twins(self, mid: str) -> int:
        return len(self._members[self._sig[mid]]) - 1

    # -- corpus-wide --------------------------------------------------------
    def groups(self) -> list[list[str]]:
        """Every group of two or more records sharing a model input, largest first."""
        out = [sorted(v) for v in self._members.values() if len(v) > 1]
        out.sort(key=lambda g: (-len(g), g[0]))
        return out

    def report(self) -> dict:
        n = len(self._sig)
        groups = self.groups()
        shared = sum(len(g) for g in groups)
        groups_c = [v for v in self._members_conc.values() if len(v) > 1]
        shared_c = sum(len(v) for v in groups_c)
        return {
            "n_media": n,
            "n_media_sharing_a_model_input": shared,
            "n_media_with_a_unique_model_input": n - shared,
            "n_groups": len(groups),
            "largest_group": max((len(g) for g in groups), default=0),
            "n_distinct_model_inputs": len(self._members),
            "of": n,
            "definition": PRIMARY_DEFINITION,
            "n_media_sharing_a_model_input_with_concentrations": shared_c,
            "n_groups_with_concentrations": len(groups_c),
            "with_concentrations_definition": CONCENTRATION_DEFINITION,
        }
