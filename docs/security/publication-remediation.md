# Publication remediation and history-cleanup runbook

FinSyntra is not safe to publish merely because sensitive files are removed from the current index. Git objects remain recoverable from earlier commits, clones, forks, caches, pull requests, and backups until history is deliberately rewritten and every exposed credential is rotated.

## Sensitive material identified

The audit found committed environment files, JWT/signing-key files, cookie/session dumps, SQLite databases, Chroma persistence, uploaded documents, newsletter/subscriber exports, logs, server output, caches, and a complete virtual environment. Historical paths include `.env`, `.env.backup`, `.env.bak.audit`, `jwt_key.txt`, `secret_key.txt`, `cookies.txt`, `data/finsolve.db`, `src/data/embeddings/`, and `src/data/raw/`.

## Required manual response

1. Preserve a private mirror and bundle before rewriting history. Restrict access to the backup because it still contains the exposed material.
2. Inventory every value in the historical environment, key, cookie, database, upload, and subscriber files without copying secret values into tickets or chat.
3. Rotate external service credentials first, then database/Redis credentials, then the JWT signing secret.
4. Deploy the new JWT signing secret and invalidate all access and refresh sessions. With stateless JWTs, changing the signing key invalidates old tokens; any server-side refresh/session records must also be revoked or deleted.
5. Expire browser cookies using the same names, domain, path, `Secure`, and `SameSite` attributes with which they were issued. Do not rely on deleting a local `cookies.txt` file.
6. Review exposed SQLite databases and Chroma metadata for conversation text, filenames, tenant identifiers, document fragments, and personal data. Follow the applicable incident-response and retention policy.
7. Review every uploaded document individually. Treat the historical `Neocart.pdf`, newsletter/subscriber CSVs, HR data, and any unverified financial document as potentially private until its owner and provenance are confirmed.
8. For newsletter/subscriber exposure, identify affected fields and recipients, revoke any associated export links or credentials, and obtain legal/privacy guidance on notification requirements.

## Manual `git-filter-repo` procedure

Do not run these commands until credential rotation is complete, a private backup is verified, collaborators are notified, and force-push approval is explicit. Run them from a fresh disposable clone, not the active development checkout.

```bash
git clone --mirror <private-repository-url> finsolve-cleanup.git
cd finsolve-cleanup.git
git filter-repo --invert-paths \
  --path .env \
  --path .env.backup \
  --path .env.bak.audit \
  --path jwt_key.txt \
  --path secret_key.txt \
  --path cookies.txt \
  --path data/finsolve.db \
  --path finsolve_dev.db \
  --path src/data/embeddings \
  --path src/data/raw \
  --path venv
```

Extend the path list from the publication checker and a full history scan. Review rewritten refs before any push:

```bash
git log --all --name-only --format= | sort -u
git rev-list --objects --all
git fsck --full
python scripts/check_publication_readiness.py
```

Use an approved secret scanner against all rewritten refs. Verify prohibited paths and high-confidence secret fingerprints are absent without printing secret values.

Only after review and explicit repository-owner approval should rewritten branches and tags be force-pushed. Protected branches may require a temporary policy change. All collaborators must delete or archive old clones and re-clone; merging an old branch can reintroduce purged objects.

## Rollback precautions

- Keep the original mirror offline, encrypted, access-controlled, and clearly labeled as contaminated.
- Record original and rewritten commit IDs.
- Test application checkout and build from the rewritten mirror before replacing remote refs.
- Never use the contaminated backup as a source for ordinary merges.
- If verification fails, discard the disposable rewritten mirror and restart from the protected backup; do not partially force-push.

History rewriting and force-pushing were intentionally not performed by the Batch 1 cleanup.

## Configuration-name migration

Legacy templates contained names that the current Pydantic `Settings` class does not read. Use the following current names when migrating private deployment configuration:

| Legacy template name | Current setting |
| --- | --- |
| `ENVIRONMENT` | `ENV` |
| `JWT_SECRET_KEY` | `SECRET_KEY` |
| `JWT_ALGORITHM` | `ALGORITHM` |
| `CORS_ORIGINS` | `ALLOWED_ORIGINS` |
| `CHROMA_DB_PATH` | `VECTOR_DB_PATH` |
| `EMBEDDING_MODEL` | `LOCAL_EMBEDDINGS_MODEL` |

The current model has no environment fields for refresh-token lifetime, cookie policy, demo mode, upload limits, or logging level. Do not assume older variables for those controls have any effect.
