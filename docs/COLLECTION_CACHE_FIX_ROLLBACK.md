# Collection/Cache Fix Rollback Guide

## Overview

This document provides step-by-step rollback procedures for the collection canonicalization and cross-process cache invalidation fixes. All fixes are designed to be instantly reversible via feature flags.

## Feature Flags Added

### Collection Consistency
- `CANONICAL_COLLECTION_ENFORCED=false` (default OFF)
- `ENABLE_UPLOAD_LOGGING=false` (default OFF)

### Cache Synchronization  
- `ENABLE_CROSS_PROCESS_CACHE_SYNC=false` (default OFF)

## Quick Rollback (Emergency)

### Immediate Disable All Fixes
```bash
export CANONICAL_COLLECTION_ENFORCED=false
export ENABLE_CROSS_PROCESS_CACHE_SYNC=false
export ENABLE_UPLOAD_LOGGING=false

# Restart services
systemctl restart finsolve-api
systemctl restart finsolve-worker
```

### Verification
```bash
# Check flags are OFF
make check-flags

# Verify legacy behavior
curl -s http://localhost:8000/health | jq '.collection_name'
# Should show: "company_docs"

# Test upload/search still works
make test-regression
```

## Individual Fix Rollback

### 1. Collection Canonicalization Rollback

**Risk**: Medium - may temporarily disrupt searches if collection names diverged

**Steps**:
```bash
# Disable canonical enforcement
export CANONICAL_COLLECTION_ENFORCED=false

# Restart API services
systemctl restart finsolve-api

# Verify legacy collection in use
grep "Using legacy collection" /var/log/finsolve/api.log
```

**Validation**:
- Upload test document
- Verify it uses `company_docs` collection
- Confirm search finds the document
- Check no "Using canonical collection" messages in logs

### 2. Cross-Process Cache Sync Rollback

**Risk**: Low - only affects cache invalidation, no data loss

**Steps**:
```bash
# Disable cross-process cache sync
export ENABLE_CROSS_PROCESS_CACHE_SYNC=false

# Restart services (clears any pending Redis connections)
systemctl restart finsolve-api
systemctl restart finsolve-worker
```

**Validation**:
- Upload document and delete it
- Verify local cache clearing still works
- Confirm no Redis connection attempts in logs
- Test search cache behavior (MISS→HIT pattern)

### 3. Upload Logging Rollback

**Risk**: None - only affects log verbosity

**Steps**:
```bash
# Disable upload logging
export ENABLE_UPLOAD_LOGGING=false

# No restart required (takes effect immediately)
```

**Validation**:
- Upload test document
- Verify no extra collection/path logging
- Confirm normal operation without verbose output

## Staged Rollback (Recommended)

### Phase 1: Disable New Features (Keep Code)
1. Set all flags to `false`
2. Restart services
3. Verify legacy behavior
4. Monitor for 24 hours

### Phase 2: Remove Code (If Needed)
1. Revert code changes via git
2. Remove new files
3. Restore original behavior
4. Deploy and test

## Rollback Validation Checklist

### System Health
- [ ] API starts without errors
- [ ] Collection name is `company_docs`
- [ ] Upload/search cycle works
- [ ] No Redis connection errors (if Redis not available)
- [ ] Performance metrics stable

### Legacy Behavior Confirmed
- [ ] No "canonical collection" in logs
- [ ] No cross-process cache events
- [ ] Standard cache behavior (local only)
- [ ] Original upload logging level

### Data Integrity
- [ ] Existing documents still searchable
- [ ] New uploads work correctly
- [ ] Deletion removes documents
- [ ] No data loss during rollback

## Troubleshooting

### Collection Not Found After Rollback
**Symptom**: Search returns no results after disabling canonical enforcement
**Cause**: Documents may be in enterprise-named collection
**Fix**:
```bash
# Check which collections exist
python scripts/db_stats.py

# If enterprise collection has documents, temporarily re-enable flag
export CANONICAL_COLLECTION_ENFORCED=true
systemctl restart finsolve-api

# Or move data to legacy collection (manual process)
```

### Redis Connection Errors
**Symptom**: Errors about Redis connections after disabling cache sync
**Cause**: Code may still reference Redis client
**Fix**:
```bash
# Ensure flag is properly set
export ENABLE_CROSS_PROCESS_CACHE_SYNC=false

# Restart all services
systemctl restart finsolve-api
systemctl restart finsolve-worker

# Check logs for remaining Redis references
grep -i redis /var/log/finsolve/api.log
```

### Performance Degradation
**Symptom**: Slower response times after rollback
**Cause**: Cache invalidation patterns may have changed
**Fix**:
```bash
# Clear all caches
redis-cli FLUSHDB  # If Redis available

# Or restart services to clear in-memory caches
systemctl restart finsolve-api
```

## Prevention Measures

### Pre-Deployment Testing
1. Test rollback in staging environment
2. Verify flag toggles work correctly
3. Measure rollback time (should be < 2 minutes)
4. Document specific environment differences

### Monitoring
1. Set alerts for collection name changes
2. Monitor Redis connection status
3. Track cache hit/miss ratios
4. Watch for error rate increases

### Communication
1. Notify team before rollback
2. Document reason for rollback
3. Plan fix implementation for issues found
4. Schedule post-rollback review

## Success Criteria

Rollback is successful when:
1. All services running normally
2. Upload/search/delete cycle works
3. Performance metrics at baseline
4. No errors in logs for 30 minutes
5. Legacy behavior confirmed via testing

## Contact

For rollback assistance:
- Check runbook first
- Review logs for specific errors  
- Test individual flag toggles
- Document issues for future improvements
