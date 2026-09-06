#!/usr/bin/env python3
"""Write data/web/*.json: the payload the three browser pages read.

FINDINGS: MEDIA-WEB-04 MEDIA-WEB-06 MEDIA-WEB-07 MEDIA-WEB-11 MEDIA-WEB-20 COV-05

This is the `make derived` entrypoint. It runs over the promoted corpus in
data/media and writes the browser payload beside the other derived artifacts.
The projection itself lives in tools/web_payload.py so that the transform stage
tools/stages/52_web_payload.py can assert the same numbers inside the chain,
against the corrected corpus, before anything is promoted.

  python3 tools/build_web_payload.py [--media DIR] [--out DIR] [--report PATH]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from web_payload import build_payload   # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", default=os.path.join(REPO, "data", "media"))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "web"))
    ap.add_argument("--quarantine",
                    default=os.path.join(REPO, "data", "_quarantine.json"))
    ap.add_argument("--report", default=None,
                    help="write the build report as JSON here as well as to stdout")
    a = ap.parse_args(argv)

    report = build_payload(os.path.abspath(a.media), os.path.abspath(a.out),
                           repo=REPO, quarantine=os.path.abspath(a.quarantine))

    print("web payload -> %s" % report["out_dir"])
    print("media read: %d" % report["media_read"])
    for name, size in report["written"].items():
        print("  %-18s %8.1f KB raw  %7.1f KB gzip"
              % (name, size["bytes"] / 1024, size["bytes_gzip"] / 1024))
    print("components %d = %s" % (report["component_totals"]["n_components"],
                                  " + ".join("%s %d" % (k, v) for k, v in
                                             report["evidence_class_totals"].items())))
    print("source-coverage bands (of %d media): %s"
          % (report["media_read"], report["coverage_bands_source"]))
    print("families: %d covering %d of %d media | exchanges indexed: %d | "
          "withdrawn records published: %d"
          % (report["n_families"], report["n_media_in_a_family"],
             report["media_read"], report["n_exchanges"], report["n_tombstones"]))
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
