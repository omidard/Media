#!/usr/bin/env python3
"""Verified source identity for a Media/MediaDB medium record.

WHY THIS MODULE EXISTS
----------------------
Every downstream legal and provenance claim in this resource depends on the answer to one
question: *which upstream source is this record's composition actually from?*

The repository's existing answer, `build_index.py:source_db()`, infers that from the record
id PREFIX::

    if idv.startswith('mediadive_'): return 'DSMZ MediaDive'
    ...
    if idv.startswith('biospecimen_'): return 'Published (HMDB-derived)'

That is a string match on a filename, and it is already provably wrong:

  * 5 records cite DSMZ but carry no ``mediadive_`` prefix (std_halobacterium,
    std_marine_broth_2216, std_methanobacterium, std_nitrobacter, std_nitrosomonas);
  * 5 bovine BMDB records (biospecimen_bmdb_*) are filed as "Published (HMDB-derived)",
    so bovine rumen and colostrum ship labelled as human-metabolome-derived.

Findings PROV-05, PROV-11 and COV-06 all name this mechanism, and the audit's verification
pass says explicitly: *do not key the licence table on build_index.py's source_db()*.

WHAT THIS MODULE DOES INSTEAD
-----------------------------
It resolves identity from EVIDENCE INSIDE THE RECORD — the provenance URL host, the DOI, and
verbatim substrings of the citation and notes — and it returns the evidence alongside the
answer, so any stamped licence can be audited back to the field it was read from.

  * The id is never consulted. ``resolve()`` does not receive it.
  * An unresolved record returns ``source_id=None``. It is never guessed into a bucket.
    Callers are expected to treat that as a hard failure.
  * Where two upstream collections hide behind one aggregator (MediaDive: DSMZ / JCM / CCAP),
    the collection is resolved separately, from the URL host, with the MediaDive medium
    number used only as a cross-check — and reported as ``None`` when unverifiable rather
    than asserted (a CCAP medium number is not published in a form we can verify).

Import surface::

    from source_identity import resolve, SOURCE_IDS
    ident = resolve(record["provenance"])
    ident.source_id, ident.source_name, ident.evidence, ident.collection, ident.flags
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# The closed vocabulary. Every id here must have a row in tools/licenses.tsv,
# and every row in tools/licenses.tsv must appear here. stamp_provenance.py
# asserts that both ways round.
# ---------------------------------------------------------------------------
SOURCE_IDS: Dict[str, str] = {
    "usda_fdc": "USDA FoodData Central",
    "dsmz_mediadive": "DSMZ MediaDive",
    "foodb": "FooDB",
    "mediadb_isb": "MediaDB (ISB defined media)",
    "hmdb": "Human Metabolome Database (HMDB 5.0)",
    "bmdb": "Bovine Metabolome Database (BMDB)",
    "hmdb_via_publication": "HMDB tables republished in an open-access paper",
    "growthdb_literature": "Primary literature via GrowthDB",
    "primary_literature": "Primary literature (GEM papers)",
    "standard_classic": "Classic and standard formulations (project-curated)",
}

MEDIADIVE_DOI = "10.1093/nar/gkac803"
HMDB_DOI = "10.1093/nar/gkab1062"
BMDB_DOI = "10.3390/metabo10060233"
ARDALANI_DOI = "10.1371/journal.ppat.1013775"

# DOIs that identify an aggregating DATABASE's own paper rather than a work containing any
# medium's formulation. They are legitimate citations of the aggregator and must never be
# counted as a primary source for a medium.
DATABASE_PAPER_DOIS = {MEDIADIVE_DOI, HMDB_DOI, BMDB_DOI}

# Hosts that identify an upstream source outright.
HOST_SOURCE = {
    "fdc.nal.usda.gov": "usda_fdc",
    "foodb.ca": "foodb",
    "mediadb.systemsbiology.net": "mediadb_isb",
}

# Hosts that identify the originating culture collection behind MediaDive.
HOST_COLLECTION = {
    "www.dsmz.de": "DSMZ",
    "mediadive.dsmz.de": "DSMZ",
    "www.jcm.riken.jp": "JCM",
    "www.ccap.ac.uk": "CCAP",
}

# MediaDive namespaces the medium number by a leading letter. This is used only to
# CROSS-CHECK the host-derived collection, never as the primary evidence.
MEDIADIVE_NUMBER_NAMESPACE = {"J": "JCM", "C": "CCAP", "P": "public"}

_PMCID_RE = re.compile(r"\bPMC\d{5,9}\b")
_MEDIADIVE_NUM_RE = re.compile(r"DSMZ Medium\s+([A-Za-z]?\d+[a-z]?)\s*:", re.I)


@dataclass
class SourceIdentity:
    """The resolved identity of one record, carrying the evidence it rests on."""

    source_id: Optional[str]
    source_name: Optional[str]
    evidence: Optional[str] = None          # which field matched, and on what
    confidence: str = "unresolved"          # verified | unresolved
    collection: Optional[str] = None        # MediaDive only: DSMZ | JCM | CCAP
    collection_evidence: Optional[str] = None
    collection_medium_id: Optional[str] = None   # None whenever unverifiable — never guessed
    mediadive_number: Optional[str] = None       # the MediaDive-namespaced number, e.g. "J557"
    primary_identifier: Optional[Dict[str, str]] = None  # {"type": "pmcid"|"doi", "value": ...}
    flags: List[str] = field(default_factory=list)


def _host(url: Any) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def _primary_identifier(prov: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Deterministically recover the primary work's identifier.

    PROV-01 notes that 1,456 literature records store their identifier as a PMC id inside
    the URL while ``doi`` is empty, which is why a naive DOI census reports 236 distinct
    works instead of ~1,070. This reads the PMC id out of the url/citation with a regex —
    no network, no inference, no Crossref author-year matching (which the audit proves
    manufactures confidently-wrong DOIs at scale).
    """
    doi = (prov.get("doi") or "").strip()
    blob = " ".join(str(prov.get(k) or "") for k in ("url", "citation", "notes"))
    m = _PMCID_RE.search(blob)
    if m:
        return {"type": "pmcid", "value": m.group(0)}
    # A database's OWN paper is not a primary identifier for the medium: 3,148 records carry
    # the MediaDive database paper's DOI, which describes the database, not any of the media.
    # Counting it as a primary work is what makes "91.8% of DOIs are one DOI" look like
    # diversity instead of the artifact it is (PROV-01).
    if doi and doi not in DATABASE_PAPER_DOIS:
        return {"type": "doi", "value": doi}
    return None


def _resolve_collection(prov: Dict[str, Any], ident: SourceIdentity) -> None:
    """Resolve the true culture collection behind a MediaDive record (finding PROV-06).

    Primary evidence is the URL host, because MediaDive's own record links straight at the
    originating collection (a JCM medium links to jcm.riken.jp). The MediaDive medium
    number's leading letter is a cross-check only: a mismatch is FLAGGED, never silently
    resolved in favour of one or the other.
    """
    host = _host(prov.get("url"))
    citation = prov.get("citation") or ""
    m = _MEDIADIVE_NUM_RE.search(citation)
    number = m.group(1) if m else None
    ident.mediadive_number = number

    coll = HOST_COLLECTION.get(host)
    if coll:
        ident.collection = coll
        ident.collection_evidence = f"provenance.url host {host!r}"
    elif number:
        ns = MEDIADIVE_NUMBER_NAMESPACE.get(number[0].upper())
        if ns and ns != "public":
            ident.collection = ns
            ident.collection_evidence = (
                f"MediaDive medium number {number!r} namespace letter "
                f"(url host {host!r} does not identify a collection)"
            )
            ident.flags.append("collection_from_number_not_host")
        else:
            ident.flags.append("collection_unresolved")
    else:
        ident.flags.append("collection_unresolved")

    # Cross-check host against the number's namespace letter.
    if number and ident.collection:
        ns = MEDIADIVE_NUMBER_NAMESPACE.get(number[0].upper())
        expected = ns if ns and ns != "public" else "DSMZ"
        if expected != ident.collection:
            ident.flags.append(
                f"collection_conflict:host={ident.collection},number={expected}"
            )

    # The collection's own medium id. Only assert it where it is verifiable.
    #   DSMZ  -> the number as MediaDive states it.
    #   JCM   -> the letter is MediaDive's namespace; jcm.riken.jp links GRMD=<n>, so the
    #            numeric remainder is the JCM id and we verify it against the URL.
    #   CCAP  -> CCAP publishes filename-based recipe PDFs with no visible numeric id.
    #            Absent is null, never a guess.
    if number:
        if ident.collection == "DSMZ":
            ident.collection_medium_id = number
        elif ident.collection == "JCM":
            stem = number[1:] if number[0].upper() == "J" else number
            url = prov.get("url") or ""
            if re.search(r"GRMD=%s\b" % re.escape(stem), url):
                ident.collection_medium_id = stem
            else:
                ident.flags.append("jcm_number_not_confirmed_by_url")
        # CCAP and anything else: leave collection_medium_id as None.


def resolve(prov: Dict[str, Any]) -> SourceIdentity:
    """Resolve one record's upstream source from its provenance block.

    The record id is deliberately not a parameter. Rules are ordered most-specific first;
    each records the field and the substring it matched on.
    """
    prov = prov or {}
    host = _host(prov.get("url"))
    doi = (prov.get("doi") or "").strip()
    citation = prov.get("citation") or ""
    notes = prov.get("notes") or ""
    stype = (prov.get("source_type") or "").strip()

    ident = SourceIdentity(source_id=None, source_name=None)
    ident.primary_identifier = _primary_identifier(prov)

    # R1-R3: the URL host names the upstream database outright.
    if host in HOST_SOURCE:
        ident.source_id = HOST_SOURCE[host]
        ident.evidence = f"provenance.url host {host!r}"

    # R4: HMDB biospecimen records — DOI of the HMDB 5.0 paper AND the database named.
    elif doi == HMDB_DOI and "Human Metabolome Database" in citation:
        ident.source_id = "hmdb"
        ident.evidence = (
            f"provenance.doi == {HMDB_DOI!r} and citation contains "
            "'Human Metabolome Database'"
        )

    # R5: BMDB biospecimen records. Checked BEFORE any biospecimen catch-all so bovine
    #     records can never fall into the HMDB bucket the way build_index.py:8 puts them.
    elif doi == BMDB_DOI and "Bovine Metabolome Database" in citation:
        ident.source_id = "bmdb"
        ident.evidence = (
            f"provenance.doi == {BMDB_DOI!r} and citation contains "
            "'Bovine Metabolome Database'"
        )

    # R6: MediaDive. The database paper's DOI plus the aggregator named in the citation.
    elif doi == MEDIADIVE_DOI and "MediaDive" in citation:
        ident.source_id = "dsmz_mediadive"
        ident.evidence = (
            f"provenance.doi == {MEDIADIVE_DOI!r} (MediaDive database paper) and "
            "citation contains 'MediaDive'"
        )
        _resolve_collection(prov, ident)

    # R7: HMDB-derived tables republished in an open-access paper.
    elif doi == ARDALANI_DOI and "HMDB" in (citation + notes):
        ident.source_id = "hmdb_via_publication"
        ident.evidence = (
            f"provenance.doi == {ARDALANI_DOI!r} (open-access paper) and 'HMDB' named in "
            "citation/notes as the origin of the tables"
        )

    # R8: classic/standard formulations curated in this repository. Checked BEFORE the
    #     GrowthDB rule: source_type == 'standard' is the record's own declaration of what it
    #     is, whereas "GrowthDB" appearing in its citation is usually a mention of where one
    #     detail came from. 13 records say both — e.g. m9_benzoate is M9 minimal salts
    #     (Sambrook & Russell) whose carbon source was taken from a GrowthDB growth record.
    #     Calling those "primary literature via GrowthDB" would misattribute the formulation.
    elif stype == "standard":
        ident.source_id = "standard_classic"
        ident.evidence = "provenance.source_type == 'standard'"
        if "GrowthDB" in citation or "GrowthDB" in notes:
            ident.flags.append("standard_formulation_with_growthdb_derived_detail")

    # R9: literature curated through GrowthDB — named in the citation or the notes.
    elif "GrowthDB" in citation or "GrowthDB" in notes:
        ident.source_id = "growthdb_literature"
        which = "citation" if "GrowthDB" in citation else "notes"
        ident.evidence = f"provenance.{which} names 'GrowthDB'"

    # R10: literature mined directly from the primary paper.
    elif stype == "literature" and "Extracted from the primary paper" in notes:
        ident.source_id = "primary_literature"
        ident.evidence = "provenance.notes contains 'Extracted from the primary paper'"

    # R11: a medium published in a GEM paper.
    elif stype == "Published (GEM paper)":
        ident.source_id = "primary_literature"
        ident.evidence = "provenance.source_type == 'Published (GEM paper)'"

    # R12: MediaDB (ISB) records identified by their source_type when the URL is absent.
    elif stype == "MediaDB (ISB defined media)":
        ident.source_id = "mediadb_isb"
        ident.evidence = "provenance.source_type == 'MediaDB (ISB defined media)'"

    if ident.source_id:
        ident.source_name = SOURCE_IDS[ident.source_id]
        ident.confidence = "verified"

    # --- attribution hazards that must not be resolved silently -------------------------
    # A record we call project-compiled whose URL points at MediaDive may have taken its
    # composition from MediaDive, which is CC BY and requires attribution + licence
    # indication. We cannot tell from the record, so we say so instead of choosing.
    if ident.source_id == "standard_classic" and host in HOST_COLLECTION:
        ident.flags.append(f"license_review_required:composition_url_host={host}")

    # A record whose displayed provenance says DSMZ while the resolved collection does not.
    if ident.source_id == "dsmz_mediadive" and ident.collection and ident.collection != "DSMZ":
        if "DSMZ Medium" in citation or "(DSMZ " in citation:
            ident.flags.append(f"citation_misattributes_dsmz:true_collection={ident.collection}")

    return ident
