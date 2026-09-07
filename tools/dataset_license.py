#!/usr/bin/env python3
"""The single licence the whole dataset is redistributed under.

One licence, stated once. Every artifact that has to name it imports it from
here, so the site, the catalogue, the API exports and the client cannot drift
apart or reintroduce a per-record licence field.

Why one licence and not a per-source schedule: a compilation cannot grant more
than its most restrictive input allows. The upstream mix includes CC BY-NC 4.0
material (FooDB, HMDB) and material redistributed by permission only, so
CC BY-NC 4.0 is the strongest licence the whole corpus can carry. It also
carries the attribution the CC BY sources are owed. Which source each record
came from stays on the record as provenance.source_id / source_name, and NOTICE
names every source and the terms it was taken under; neither is a licence split.

Code in this repository is MIT, which is a different question from the data.
"""

DATASET_LICENSE = {
    "id": "CC-BY-NC-4.0",
    "name": "Creative Commons Attribution-NonCommercial 4.0 International",
    "url": "https://creativecommons.org/licenses/by-nc/4.0/",
    "applies_to": "the data in this repository: data/media, data/index.json, "
                  "data/web, data/api and every export built from them",
    "attribution": "MediaDB (github.com/omidard/Media), plus the primary "
                   "citation on each record it is used from",
    "code_license": "MIT",
}

#: The one line a page, a README or a payload states.
LICENSE_LINE = ("The data is licensed CC BY-NC 4.0. Code in this repository is "
                "MIT.")
