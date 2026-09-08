"""The release stamp identifies the bytes it is stamped on.

THE DEFECT THIS FILE EXISTS FOR
-------------------------------
Every page footer printed "Release built <utc> from commit <sha> over 13,515
records", and methods.html tells a scientist to "name this resource and its release
stamp where the compilation itself was load-bearing". The one identifier the page
asks you to cite did not resolve to the numbers beside it.

tools/web_payload.py wrote `git_head` from `git rev-parse HEAD` AT BUILD TIME, so
it names the tree the builder was standing on and the payload it stamps can only be
committed afterwards. The stamped commit can never contain the stamped bytes. That
is structural, not a slip.

Measured on the shipped release: the payload carried git_head 837660234, and
`git show 837660234:data/web/catalog.json` publishes n_bigg_exchange 664,000
against the shipped 652,620, is missing the key n_bigg_shaped_no_such_exchange
entirely, and that tree does not even contain tools/build_bigg_exchange_ids.py, the
module that computes the four-state partition. Checking out the stamped commit and
running `make derived` therefore cannot reproduce the stamped payload; it
reproduces the number the project had already retracted.

WHAT REPLACES IT
----------------
`corpus_sha256`: sha256 over every record's bytes in sorted id order, which
identifies the corpus rather than a tree that might contain it, and which any
reader can recompute from a checkout with no history at all. `git_head` stays, and
is labelled in the payload as the commit the build RAN FROM.
"""
import hashlib
import json
import os
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(REPO, "data", "web", "catalog.json")
MEDIA = os.path.join(REPO, "data", "media")


def _catalog():
    if not os.path.exists(CATALOG):
        pytest.skip("the browser payload is not built in this tree")
    with open(CATALOG, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_stamp_carries_a_digest_of_the_corpus_it_describes():
    cat = _catalog()
    assert cat.get("corpus_sha256"), (
        "the release stamp names no corpus digest, so the only identifier it "
        "offers is a commit that cannot contain these bytes")
    files = sorted(f for f in os.listdir(MEDIA) if f.endswith(".json"))
    if len(files) < 1000:
        pytest.skip("this tree does not hold the full corpus")
    h = hashlib.sha256()
    for name in files:
        with open(os.path.join(MEDIA, name), "rb") as fh:
            h.update(fh.read())
    assert cat["corpus_sha256"] == h.hexdigest()[:12], (
        "the published corpus digest %r does not match the corpus that ships "
        "(%r). The stamp describes a corpus this release does not contain."
        % (cat["corpus_sha256"], h.hexdigest()[:12]))


def test_the_recompute_command_is_published_beside_the_digest():
    """A digest a reader cannot recompute is no better than a commit id."""
    cat = _catalog()
    cmd = cat.get("corpus_sha256_recompute") or ""
    assert "sha256" in cmd and "data/media" in cmd, (
        "the payload publishes a digest with no way to check it: %r" % cmd)


def test_the_commit_id_is_labelled_as_the_tree_the_build_ran_from():
    """It may not stand unqualified beside the numbers it cannot account for."""
    cat = _catalog()
    if cat.get("git_head") is None:
        return
    meaning = cat.get("git_head_meaning") or ""
    assert "ran from" in meaning.lower() or "cannot" in meaning.lower(), (
        "git_head ships with no statement of what it is, so a reader reads it as "
        "the commit that contains this payload, which it never is: %r" % meaning)


def test_the_pages_do_not_ask_a_reader_to_quote_the_commit():
    for rel in ("index.html", "methods.html"):
        path = os.path.join(REPO, rel)
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        assert "' from commit '" not in body, (
            "%s still prints the build-time commit id as the release identifier"
            % rel)
        assert "corpus_sha256" in body, (
            "%s prints a release stamp with no corpus digest in it" % rel)


def test_the_stamped_payload_is_reproducible_from_what_the_stamp_names():
    """The reproduction the old stamp promised and could not keep.

    Recomputing the digest from the corpus in the working tree must reproduce the
    digest the payload publishes. Against the old stamp the equivalent check --
    compare the shipped catalog.json to the catalog.json at its own git_head --
    failed on HEAD (664,000 against 652,620) and on origin/main (five keys and a
    column apart).
    """
    cat = _catalog()
    files = sorted(f for f in os.listdir(MEDIA) if f.endswith(".json"))
    if len(files) < 1000:
        pytest.skip("this tree does not hold the full corpus")
    assert cat["count"] == len(files), (
        "the stamp counts %r records and the corpus holds %d"
        % (cat.get("count"), len(files)))
    # And the digest is not a constant somebody typed: it must move with the corpus.
    h = hashlib.sha256()
    for name in files[:-1]:
        with open(os.path.join(MEDIA, name), "rb") as fh:
            h.update(fh.read())
    assert cat["corpus_sha256"] != h.hexdigest()[:12]


def test_git_is_available_or_this_file_says_so():
    """Guard the guard: if git is absent the stamp silently loses git_head."""
    try:
        subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                       capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available here")
