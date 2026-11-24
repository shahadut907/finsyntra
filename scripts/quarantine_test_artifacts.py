#!/usr/bin/env python3
"""Move confirmed test artifacts out of the live demo corpus.

    python scripts/quarantine_test_artifacts.py --report
    python scripts/quarantine_test_artifacts.py --quarantine

Files are MOVED, never deleted, into a gitignored quarantine directory with a
JSON manifest recording original path, destination and SHA256 so the operation
is fully reversible.

Classification is by CONTENT, not filename. A file is quarantined only when its
bytes exactly match a known canned test payload, or it is empty, or it is pure
filler. Anything else — including anything that merely looks test-ish by name —
is left in place for a human to decide.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.config.settings import get_raw_documents_path, PROJECT_ROOT  # noqa: E402

# Exact canned payloads emitted by the test-suite upload fixtures.
KNOWN_TEST_PAYLOADS = {
    "",                                                  # empty-file test
    "Content",                                           # filename-sanitisation tests
    "test content",
    "Test document content",
    "Duplicate test content",                            # duplicate-upload test
    "# Test content",
    "# Test content\nSome text",     # tests/test_document_upload_auth.py:190
    "# Test content\n\nSome text",
    "# Header\n\nSome **bold** content\n\n- List item",
    "%PDF-1.4\n%Test PDF content",
    "Unicode: 日本語 中文 العربية émojis \U0001f389",
    "Q4 2024 Summary: Revenue was $4.5 million. Expenses were $3.2 million.",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_text(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except Exception:
        return None


def classify(path):
    """-> (category, reason). B = confirmed artifact, A/C = leave alone."""
    size = os.path.getsize(path)
    text = read_text(path)
    if text is None:
        return "C", "unreadable — leaving in place"

    normalised = text.replace("\r\n", "\n").strip()

    if size == 0:
        return "B", "zero-byte file (empty-upload test fixture)"
    if normalised in KNOWN_TEST_PAYLOADS:
        return "B", "content is an exact known test payload: %r" % normalised[:60]
    body = normalised.replace("\n", "")
    if len(body) >= 512 and len(set(body)) == 1:
        return "B", "pure filler (%d bytes of %r) — file-size test fixture" % (size, body[0])
    return "C", "content is not a recognised test payload — left for human review"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarantine", action="store_true", help="perform the move")
    ap.add_argument("--report", action="store_true", help="classify only")
    args = ap.parse_args()

    raw = get_raw_documents_path()
    files = sorted(f for f in os.listdir(raw) if os.path.isfile(os.path.join(raw, f)))

    confirmed, kept = [], []
    for name in files:
        p = os.path.join(raw, name)
        cat, reason = classify(p)
        (confirmed if cat == "B" else kept).append((name, reason, os.path.getsize(p)))

    print("raw corpus : %s" % raw)
    print("total files: %d" % len(files))
    print("\n--- CONFIRMED TEST ARTIFACTS (category B, %d) ---" % len(confirmed))
    for n, r, s in confirmed:
        print("  %-56s %7d  %s" % (n[:56], s, r))
    print("\n--- KEPT IN LIVE CORPUS (%d) ---" % len(kept))
    for n, r, s in kept:
        print("  %-56s %7d  %s" % (n[:56], s, r))

    if not args.quarantine:
        print("\nReport only. Pass --quarantine to move category B files.")
        return 0
    if not confirmed:
        print("\nNothing to quarantine.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(PROJECT_ROOT, "backups", "raw-test-artifacts.pre-wave3.%s" % stamp)
    os.makedirs(dest, exist_ok=True)

    manifest = []
    for name, reason, _size in confirmed:
        src = os.path.join(raw, name)
        digest = sha256(src)
        dst = os.path.join(dest, name)
        shutil.move(src, dst)
        manifest.append({
            "original_path": src,
            "quarantined_path": dst,
            "sha256": digest,
            "reason": reason,
            "moved_at": datetime.now().isoformat(timespec="seconds"),
        })

    mpath = os.path.join(dest, "MANIFEST.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump({"source_corpus": raw, "count": len(manifest),
                   "files": manifest}, f, indent=1)

    # Verify every move landed intact.
    bad = [m for m in manifest
           if not os.path.exists(m["quarantined_path"])
           or sha256(m["quarantined_path"]) != m["sha256"]]
    remaining = sorted(f for f in os.listdir(raw) if os.path.isfile(os.path.join(raw, f)))

    print("\n[quarantine] moved   : %d file(s)" % len(manifest))
    print("[quarantine] dest    : %s" % dest)
    print("[quarantine] manifest: %s" % mpath)
    print("[quarantine] checksum mismatches: %d" % len(bad))
    print("[quarantine] remaining in live corpus: %d" % len(remaining))
    for r in remaining:
        print("    %s" % r)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
