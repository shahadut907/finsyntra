#!/usr/bin/env python3
"""Deterministically re-index the bundled corpus under an explicit tenant.

    python scripts/rebuild_bootstrap_index.py --report
    python scripts/rebuild_bootstrap_index.py --rebuild

This is an EXPLICIT OPERATOR ACTION. VectorStore never deletes a collection on
its own any more, so purging is only ever done from here, deliberately, and only
for the bootstrap tenant's own chunks.

Sources of truth:
    documents : settings.raw_documents_path      (src/data/raw)
    ownership : settings.bootstrap_tenant_id     (tenant_acme)

Other tenants' vectors are never touched: the purge is scoped by tenant_id.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config.settings import settings, get_raw_documents_path  # noqa: E402
from src.backend.services.vector_store import VectorStore  # noqa: E402
from src.backend.utils.document_processor import DocumentProcessor  # noqa: E402
from src.config.roles import get_bootstrap_department  # noqa: E402


def summarise(store):
    """Tenant/source/department breakdown of the whole collection."""
    res = store.collection.get(include=["metadatas"])
    metas = res.get("metadatas") or []
    return {
        "total": len(metas),
        "tenants": Counter(m.get("tenant_id", "<MISSING>") for m in metas),
        "sources": Counter(m.get("source", "<unknown>") for m in metas),
        "departments": Counter(m.get("department", "<unknown>") for m in metas),
    }


def show(label, s):
    print("\n--- %s ---" % label)
    print("  total chunks : %d" % s["total"])
    print("  tenants      : %s" % dict(s["tenants"]))
    print("  departments  : %s" % dict(s["departments"]))
    print("  sources (%d) :" % len(s["sources"]))
    for src, n in sorted(s["sources"].items()):
        print("      %-58s %d" % (src, n))


def process(path, processor):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return processor.process_csv(path)
    if ext == ".pdf":
        return processor.process_pdf(path)
    if ext in (".md", ".markdown", ".txt"):
        return processor.process_markdown(path)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="purge this tenant's chunks and re-index from source")
    ap.add_argument("--report", action="store_true", help="show current state only")
    args = ap.parse_args()

    tenant = (settings.bootstrap_tenant_id or "").strip()
    if not tenant:
        print("FATAL: settings.bootstrap_tenant_id is empty. Refusing to index "
              "documents without an explicit owning tenant.")
        return 2

    raw_dir = get_raw_documents_path()
    store = VectorStore()

    print("collection : %s" % store.collection_name)
    print("path       : %s" % store.persist_directory)
    print("raw docs   : %s" % raw_dir)
    print("tenant     : %s" % tenant)

    before = summarise(store)
    show("BEFORE", before)

    if args.report and not args.rebuild:
        return 0
    if not args.rebuild:
        print("\nNothing to do. Pass --rebuild to re-index.")
        return 0

    # 1. Purge ONLY this tenant's existing chunks. Scoped delete — other
    #    tenants' vectors are untouched.
    existing = sorted(store.get_unique_sources(tenant_id=tenant))
    if existing:
        print("\n[purge] removing %d source(s) for tenant=%s" % (len(existing), tenant))
        store.delete_documents_by_sources(existing, tenant_id=tenant)

    # 2. Re-index every supported file from source.
    processor = DocumentProcessor()
    files = sorted(
        os.path.join(raw_dir, f) for f in os.listdir(raw_dir)
        if os.path.isfile(os.path.join(raw_dir, f))
        and os.path.splitext(f)[1].lower() in (".md", ".markdown", ".txt", ".csv", ".pdf")
    )
    print("\n[index] %d candidate file(s)" % len(files))

    all_chunks, skipped = [], []
    for path in files:
        name = os.path.basename(path)

        # FAIL-CLOSED: only index bundled files with an explicit department.
        dept = get_bootstrap_department(name)
        if dept is None:
            skipped.append((name, "UNCLASSIFIED — no DOCUMENT_CATEGORIES entry; "
                                  "not indexed (would otherwise default to general access)"))
            continue

        try:
            chunks = process(path, processor)
        except Exception as exc:
            skipped.append((name, "%s: %s" % (type(exc).__name__, exc)))
            continue
        if not chunks:
            skipped.append((name, "no extractable chunks"))
            continue
        for c in chunks:
            c.metadata["department"] = dept
            # Explicit ownership stamped on every chunk. add_documents also
            # receives tenant_id and cross-checks the two.
            c.metadata["tenant_id"] = tenant
        all_chunks.extend(chunks)
        print("    %-58s %d chunk(s)" % (os.path.basename(path), len(chunks)))

    if skipped:
        print("\n[skipped] %d file(s):" % len(skipped))
        for name, why in skipped:
            print("    %-58s %s" % (name, why))

    if not all_chunks:
        print("\nNo chunks produced — nothing indexed.")
        return 1

    print("\n[write] indexing %d chunk(s) as tenant=%s" % (len(all_chunks), tenant))
    store.add_documents(all_chunks, tenant_id=tenant)

    after = summarise(store)
    show("AFTER", after)

    # 3. Acceptance gates.
    failures = []
    if after["tenants"].get("default"):
        failures.append("%d chunk(s) still owned by the phantom 'default' tenant"
                        % after["tenants"]["default"])
    if after["tenants"].get("<MISSING>"):
        failures.append("%d chunk(s) have no tenant_id at all"
                        % after["tenants"]["<MISSING>"])
    if not after["tenants"].get(tenant):
        failures.append("no chunks were indexed for tenant %s" % tenant)

    print()
    if failures:
        for f in failures:
            print("FAIL: %s" % f)
        return 1
    print("OK: %d chunk(s) owned by %s; no 'default' and no missing tenant_id."
          % (after["tenants"][tenant], tenant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
