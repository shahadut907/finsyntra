# Enterprise RAG Staged Rollout Runbook

## Executive Summary

This runbook provides step-by-step instructions for deploying enterprise RAG features with zero downtime and full rollback capability. All new features ship **disabled by default** and are progressively enabled after validation.

## Pre-Deployment Checklist

### Required Validations
- [ ] All CI tests passing (legacy + new)
- [ ] Database backup completed
- [ ] Vector store backup completed
- [ ] Feature flags confirmed OFF in production
- [ ] Monitoring dashboards configured
- [ ] Rollback plan reviewed with team
- [ ] Staging environment validated

### Feature Flags (Default: OFF)
```bash
STRICT_MODE=false              # Lifecycle filtering
TENANT_SCOPING_ON=false        # Multi-tenant isolation
ENABLE_DELETION_WORKER=false  # Async deletion
ENABLE_RECONCILIATION=false   # Drift correction
BLOCK_BACKUP_FOLDERS=true     # Safety check (ON by default)
```

## Stage 1: Foundation (Day 1)

### 1.1 Deploy Code with Flags OFF
```bash
# Deploy application code
git pull origin main
pip install -r requirements.txt

# Verify flags are OFF
make check-flags

# Run regression tests
make test-regression
```

### 1.2 Run Database Migrations
```bash
# Backup database first
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Run migrations (additive only)
make migrate

# Verify new columns exist
psql $DATABASE_URL -c "\d documents"
# Should see: is_active, deleted_at, version, checksum, tenant_id (all nullable)
```

### 1.3 Clean Backup Folders
```bash
# List any backup folders
find ./src/data/embeddings -name '*BACKUP*' -type d

# Remove backup folders
make clean-backups

# Verify clean
ls -la ./src/data/embeddings/
```

### Validation Gate 1
- [ ] Application running normally
- [ ] No errors in logs
- [ ] Legacy upload/search/delete working
- [ ] Performance metrics stable

## Stage 2: Metadata Backfill (Day 2)

### 2.1 Dry Run Backfill
```bash
# Preview changes
make backfill-dry > backfill_preview.log

# Review affected records
grep "Would update" backfill_preview.log | wc -l
```

### 2.2 Execute Backfill
```bash
# Run in batches during low traffic
make backfill

# Verify completion
psql $DATABASE_URL -c "
  SELECT COUNT(*) FROM documents 
  WHERE is_active IS NULL OR version IS NULL
"
# Should return 0
```

### 2.3 Initial Reconciliation
```bash
# Dry run first
make reconcile-dry

# Review drift
# Orphaned: vectors without DB records
# Missing: DB records without vectors

# Fix drift
make reconcile
```

### Validation Gate 2
- [ ] All documents have lifecycle metadata
- [ ] Vector drift = 0
- [ ] No performance degradation
- [ ] Search results unchanged

## Stage 3: Enable Deletion Worker (Day 3)

### 3.1 Start Worker Process
```bash
# Enable worker flag
export ENABLE_DELETION_WORKER=true

# Start worker (use supervisor/systemd in production)
make worker &

# Verify running
make worker-status
```

### 3.2 Test Deletion Flow
```bash
# Delete test document via API
curl -X DELETE http://localhost:8000/admin/documents/test-doc-id

# Check job queue
psql $DATABASE_URL -c "
  SELECT * FROM vector_deletion_jobs 
  WHERE status = 'pending'
"

# Monitor processing
watch -n 5 'psql $DATABASE_URL -t -c "
  SELECT status, COUNT(*) 
  FROM vector_deletion_jobs 
  GROUP BY status
"'
```

### Validation Gate 3
- [ ] Deletion jobs processing successfully
- [ ] Jobs completing within SLA (< 30s)
- [ ] No failed jobs accumulating
- [ ] Legacy deletion still works

## Stage 4: Enable Strict Mode - Canary (Day 4)

### 4.1 Enable for 10% Traffic
```bash
# In load balancer or feature flag service
# Route 10% of traffic to strict mode instances

# For canary instances:
export STRICT_MODE=true

# Restart application
systemctl restart finsolve-api
```

### 4.2 Monitor Canary Metrics
```bash
# Watch for errors
tail -f /var/log/finsolve/api.log | grep "STRICT_MODE"

# Check empty result rate
# Should see "No eligible documents" messages for truly empty queries

# Monitor latency
curl http://localhost:9090/metrics | grep retrieval_latency
```

### 4.3 Gradual Rollout
```
Hour 0-4:   10% traffic (canary)
Hour 4-8:   25% traffic
Hour 8-12:  50% traffic
Hour 12-24: 100% traffic
```

### Validation Gate 4
- [ ] No increase in error rate
- [ ] P95 latency < 2s maintained
- [ ] Correct "no results" for deleted docs
- [ ] User complaints = 0

## Stage 5: Enable Tenant Scoping (Day 5)

### 5.1 Configure Tenant IDs
```bash
# Ensure all documents have tenant_id
psql $DATABASE_URL -c "
  UPDATE documents 
  SET tenant_id = organization_id 
  WHERE tenant_id IS NULL
"

# Enable scoping
export TENANT_SCOPING_ON=true
export ENABLE_RECONCILIATION=true
```

### 5.2 Test Isolation
```bash
# Create test data for different tenants
# Query as tenant A - should not see tenant B data

# Run isolation tests
make test-strict
```

### 5.3 Enable Reconciliation Schedule
```bash
# Add to crontab
0 2 * * * cd /app && make reconcile >> /var/log/reconcile.log 2>&1

# Or use systemd timer
systemctl enable finsolve-reconcile.timer
systemctl start finsolve-reconcile.timer
```

### Validation Gate 5
- [ ] Zero cross-tenant data leaks
- [ ] Reconciliation running nightly
- [ ] Drift stays at 0
- [ ] All integration tests passing

## Monitoring & Alerts

### Key Metrics to Watch
```bash
# Vector drift
curl http://localhost:9090/metrics | grep vector_db_drift

# Deletion job success rate
curl http://localhost:9090/metrics | grep deletion_jobs

# Query latency (P95 < 2s)
curl http://localhost:9090/metrics | grep retrieval_latency

# Cache hit rate
curl http://localhost:9090/metrics | grep cache_hits
```

### Alert Thresholds
- Vector drift > 10 documents
- Deletion job failure rate > 1%
- P95 latency > 2 seconds
- Error rate > 0.1%

## Rollback Procedures

### Quick Rollback (< 1 minute)
```bash
# Disable all flags immediately
make rollback

# This sets:
# STRICT_MODE=false
# TENANT_SCOPING_ON=false
# ENABLE_DELETION_WORKER=false
# ENABLE_RECONCILIATION=false

# Restart application
systemctl restart finsolve-api
```

### Partial Rollback
```bash
# Disable specific feature
export STRICT_MODE=false  # Keep other features enabled

# Restart
systemctl restart finsolve-api
```

### Full Rollback (if needed)
```bash
# Stop services
systemctl stop finsolve-api
systemctl stop finsolve-deletion-worker

# Restore database backup
psql $DATABASE_URL < backup_YYYYMMDD.sql

# Restore vector backup
cp -r /backup/chroma_db/* ./src/data/embeddings/chroma_db/

# Revert code
git checkout stable-pre-enterprise

# Start services
systemctl start finsolve-api
```

## Validation Tests

### Test 1: Deletion Propagation
```bash
# Create test document
DOC_ID=$(curl -X POST http://localhost:8000/admin/upload \
  -F "file=@test.txt" \
  -F "department=general" | jq -r '.doc_id')

# Search for it
curl "http://localhost:8000/search?q=test+content"
# Should find document

# Delete it
curl -X DELETE "http://localhost:8000/admin/documents/$DOC_ID"

# Wait 10 seconds for processing
sleep 10

# Search again
curl "http://localhost:8000/search?q=test+content"
# Should return 0 results
```

### Test 2: Tenant Isolation
```bash
# As Tenant A
curl -H "X-Tenant-ID: tenant-a" \
  "http://localhost:8000/search?q=confidential"

# Should only see tenant-a results
# Verify no tenant-b data in response
```

### Test 3: Backup Folder Rejection
```bash
# Try to start with backup in path
VECTOR_DB_PATH=./data/chroma_BACKUP python -m src.backend.api

# Should fail with: "Backup folder detected"
```

### Test 4: Performance Benchmark
```bash
# Run scale test
make benchmark

# Verify:
# - P95 < 2s
# - Citation precision >= 0.8
```

## Post-Deployment

### Week 1 Tasks
- [ ] Monitor metrics daily
- [ ] Review error logs
- [ ] Gather user feedback
- [ ] Run reconciliation report
- [ ] Document any issues

### Week 2 Tasks
- [ ] Performance tuning based on metrics
- [ ] Optimize deletion worker batch size
- [ ] Review and adjust cache TTLs
- [ ] Plan next features

### Success Criteria
- Zero regression in existing features
- Drift maintained at 0
- P95 latency < 2s sustained
- Deletion success rate > 99%
- Zero cross-tenant leaks
- User satisfaction maintained/improved

## Troubleshooting

### Issue: High Vector Drift
```bash
# Check for failed deletion jobs
psql $DATABASE_URL -c "
  SELECT COUNT(*), status, error_message 
  FROM vector_deletion_jobs 
  WHERE status = 'failed' 
  GROUP BY status, error_message
"

# Retry failed jobs
psql $DATABASE_URL -c "
  UPDATE vector_deletion_jobs 
  SET status = 'pending', attempts = 0 
  WHERE status = 'failed'
"

# Force reconciliation
make reconcile-force
```

### Issue: Slow Queries
```bash
# Check vector store size
psql $DATABASE_URL -c "
  SELECT COUNT(*) as chunks, 
         COUNT(DISTINCT doc_id) as documents 
  FROM vectors
"

# Rebuild indexes if needed
python scripts/rebuild_indexes.py

# Clear caches
redis-cli FLUSHDB
```

### Issue: Worker Crash
```bash
# Check worker logs
journalctl -u finsolve-deletion-worker -n 100

# Restart with increased memory
systemctl edit finsolve-deletion-worker
# Add: MemoryMax=4G

systemctl restart finsolve-deletion-worker
```

## Emergency Contacts

- On-call Engineer: [Phone/Slack]
- Database Admin: [Phone/Slack]
- Platform Team: [Phone/Slack]
- Escalation: [Management Contact]

## Appendix: Environment Variables

```bash
# Feature Flags
STRICT_MODE=false|true
TENANT_SCOPING_ON=false|true
ENABLE_DELETION_WORKER=false|true
ENABLE_RECONCILIATION=false|true
BLOCK_BACKUP_FOLDERS=true|false

# Configuration
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
VECTOR_SCHEMA_VERSION=1
ENVIRONMENT=production|staging|development

# Tuning
DELETION_WORKER_BATCH_SIZE=10
RECONCILIATION_INTERVAL_HOURS=24
MAX_VERSIONS_PER_DOC=5
```

## Sign-off

- [ ] Engineering Lead
- [ ] Platform Team
- [ ] Security Review
- [ ] Product Owner

---

Last Updated: 2024-01-15
Version: 1.0.0
