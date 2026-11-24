# FinSyntra RAG Pipeline Improvements - Migration Guide

This document provides guidance on enabling the new RAG pipeline improvements while maintaining backward compatibility and system stability.

## Overview

The new features are implemented behind feature flags to ensure zero disruption to existing functionality. All improvements can be enabled gradually, tested, and rolled back if needed.

## Feature Flags

### Core Memory & Consistency Features

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_CONVO_MEMORY` | Session memory for active subjects and facts | `false` | Low - adds memory layer |
| `ENABLE_QUERY_REWRITER` | Query rewriting for pronoun resolution | `false` | Low - pre-processing step |
| `ENABLE_COREF_CANON` | Coreference resolution and entity canonicalization | `false` | Medium - entity processing |
| `ENABLE_ENTITY_REGISTRY` | Entity registry for name/ID resolution | `false` | Medium - entity indexing |

### Grounding & Citations

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_STRICT_GROUNDING` | Strict citation validation | `false` | Medium - validation layer |
| `ENABLE_STABLE_DOC_IDS` | Stable document IDs for citations | `false` | Low - metadata enhancement |

### Security & Policy

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_POLICY_ENFORCEMENT` | RBAC at answer-time | `false` | High - access control |
| `ENABLE_CONSENT_FLOW` | Consent prompts for sensitive data | `false` | Medium - user interaction |
| `ENABLE_AUDIT_LOGGING` | Audit logging for compliance | `false` | Low - logging enhancement |

### Data Processing

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_TABLE_RETRIEVER` | Structured data handling | `false` | Medium - new data layer |
| `ENABLE_CSV_NORMALIZATION` | CSV data normalization | `false` | Low - data formatting |

### User Experience

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_SUBJECT_PIN_UI` | Subject pinning interface | `false` | Low - UI enhancement |
| `ENABLE_DISAMBIGUATION_CHIPS` | Entity disambiguation UI | `false` | Low - UI enhancement |
| `ENABLE_CONSENT_MODAL` | Consent modal for sensitive data | `false` | Medium - UI interaction |

### Quality & Monitoring

| Flag | Description | Default | Impact |
|------|-------------|---------|---------|
| `ENABLE_QUALITY_GATES` | Answer quality checks | `false` | Medium - validation |
| `ENABLE_ANOMALY_DETECTION` | Anomaly detection | `false` | Low - monitoring |

## Migration Strategy

### Phase 1: Foundation (Week 1)
Enable low-impact features that provide immediate value:

```bash
# Enable session memory and basic improvements
export FINSOLVE_ENABLE_CONVO_MEMORY=true
export FINSOLVE_ENABLE_QUERY_REWRITER=true
export FINSOLVE_ENABLE_STABLE_DOC_IDS=true
export FINSOLVE_ENABLE_AUDIT_LOGGING=true
```

**Expected Benefits:**
- Better conversation continuity
- Improved pronoun resolution
- Stable citations
- Compliance logging

**Monitoring:**
- Check memory usage
- Monitor query processing time
- Verify citation stability

### Phase 2: Entity Management (Week 2)
Enable entity-related features:

```bash
# Enable entity registry and coreference
export FINSOLVE_ENABLE_ENTITY_REGISTRY=true
export FINSOLVE_ENABLE_COREF_CANON=true
export FINSOLVE_ENABLE_CSV_NORMALIZATION=true
```

**Expected Benefits:**
- Consistent entity references
- Better name resolution
- Improved data formatting

**Monitoring:**
- Entity registry performance
- Memory usage for entity indexes
- Data consistency metrics

### Phase 3: Data Quality (Week 3)
Enable validation and quality features:

```bash
# Enable grounding validation and quality gates
export FINSOLVE_ENABLE_STRICT_GROUNDING=true
export FINSOLVE_ENABLE_QUALITY_GATES=true
export FINSOLVE_ENABLE_TABLE_RETRIEVER=true
```

**Expected Benefits:**
- Better answer accuracy
- Reduced hallucinations
- Improved structured data handling

**Monitoring:**
- Validation performance
- Answer quality metrics
- Table retrieval success rates

### Phase 4: Security & Policy (Week 4)
Enable security features:

```bash
# Enable policy enforcement and consent
export FINSOLVE_ENABLE_POLICY_ENFORCEMENT=true
export FINSOLVE_ENABLE_CONSENT_FLOW=true
export FINSOLVE_ENABLE_CONSENT_MODAL=true
```

**Expected Benefits:**
- Better data security
- RBAC enforcement
- Compliance improvements

**Monitoring:**
- Policy decision metrics
- Consent flow completion rates
- Security incident reports

### Phase 5: User Experience (Week 5)
Enable UI enhancements:

```bash
# Enable UI improvements
export FINSOLVE_ENABLE_SUBJECT_PIN_UI=true
export FINSOLVE_ENABLE_DISAMBIGUATION_CHIPS=true
export FINSOLVE_ENABLE_ANOMALY_DETECTION=true
```

**Expected Benefits:**
- Better user experience
- Clearer entity context
- Proactive issue detection

**Monitoring:**
- UI interaction metrics
- User satisfaction scores
- Error reduction rates

## Environment Configuration

### Development Environment
```bash
# Enable all features for testing
export FINSOLVE_ENABLE_CONVO_MEMORY=true
export FINSOLVE_ENABLE_QUERY_REWRITER=true
export FINSOLVE_ENABLE_COREF_CANON=true
export FINSOLVE_ENABLE_ENTITY_REGISTRY=true
export FINSOLVE_ENABLE_STRICT_GROUNDING=true
export FINSOLVE_ENABLE_STABLE_DOC_IDS=true
export FINSOLVE_ENABLE_POLICY_ENFORCEMENT=true
export FINSOLVE_ENABLE_CONSENT_FLOW=true
export FINSOLVE_ENABLE_AUDIT_LOGGING=true
export FINSOLVE_ENABLE_TABLE_RETRIEVER=true
export FINSOLVE_ENABLE_CSV_NORMALIZATION=true
export FINSOLVE_ENABLE_SUBJECT_PIN_UI=true
export FINSOLVE_ENABLE_DISAMBIGUATION_CHIPS=true
export FINSOLVE_ENABLE_CONSENT_MODAL=true
export FINSOLVE_ENABLE_QUALITY_GATES=true
export FINSOLVE_ENABLE_ANOMALY_DETECTION=true
```

### Staging Environment
```bash
# Enable features in phases
export FINSOLVE_ENABLE_CONVO_MEMORY=true
export FINSOLVE_ENABLE_QUERY_REWRITER=true
export FINSOLVE_ENABLE_STABLE_DOC_IDS=true
export FINSOLVE_ENABLE_AUDIT_LOGGING=true
export FINSOLVE_ENABLE_ENTITY_REGISTRY=true
export FINSOLVE_ENABLE_COREF_CANON=true
export FINSOLVE_ENABLE_CSV_NORMALIZATION=true
export FINSOLVE_ENABLE_STRICT_GROUNDING=true
export FINSOLVE_ENABLE_QUALITY_GATES=true
export FINSOLVE_ENABLE_TABLE_RETRIEVER=true
```

### Production Environment
```bash
# Start with low-risk features
export FINSOLVE_ENABLE_CONVO_MEMORY=true
export FINSOLVE_ENABLE_QUERY_REWRITER=true
export FINSOLVE_ENABLE_STABLE_DOC_IDS=true
export FINSOLVE_ENABLE_AUDIT_LOGGING=true
```

## Rollback Procedures

### Quick Rollback (All Features)
```bash
# Disable all new features
export FINSOLVE_ENABLE_CONVO_MEMORY=false
export FINSOLVE_ENABLE_QUERY_REWRITER=false
export FINSOLVE_ENABLE_COREF_CANON=false
export FINSOLVE_ENABLE_ENTITY_REGISTRY=false
export FINSOLVE_ENABLE_STRICT_GROUNDING=false
export FINSOLVE_ENABLE_STABLE_DOC_IDS=false
export FINSOLVE_ENABLE_POLICY_ENFORCEMENT=false
export FINSOLVE_ENABLE_CONSENT_FLOW=false
export FINSOLVE_ENABLE_AUDIT_LOGGING=false
export FINSOLVE_ENABLE_TABLE_RETRIEVER=false
export FINSOLVE_ENABLE_CSV_NORMALIZATION=false
export FINSOLVE_ENABLE_SUBJECT_PIN_UI=false
export FINSOLVE_ENABLE_DISAMBIGUATION_CHIPS=false
export FINSOLVE_ENABLE_CONSENT_MODAL=false
export FINSOLVE_ENABLE_QUALITY_GATES=false
export FINSOLVE_ENABLE_ANOMALY_DETECTION=false
```

### Selective Rollback
```bash
# Disable specific problematic features
export FINSOLVE_ENABLE_POLICY_ENFORCEMENT=false
export FINSOLVE_ENABLE_CONSENT_FLOW=false
```

### Database Rollback
If entity registry or table retriever data needs to be cleared:

```python
from src.backend.entities.registry import get_entity_registry
from src.backend.retrieval.table_retriever import get_table_retriever

# Clear entity registry
entity_registry = get_entity_registry()
entity_registry.clear_registry()

# Clear table retriever
table_retriever = get_table_retriever()
table_retriever.close()
```

## Performance Monitoring

### Key Metrics to Track

1. **Response Time**
   - Baseline: Measure before enabling features
   - Target: < 5% increase from baseline
   - Alert: > 10% increase

2. **Memory Usage**
   - Session memory: Monitor per-session memory growth
   - Entity registry: Track entity index size
   - Table retriever: Monitor database size

3. **Accuracy Metrics**
   - Citation accuracy: Measure citation relevance
   - Entity consistency: Track entity drift
   - Answer quality: Monitor user satisfaction

4. **Security Metrics**
   - Policy enforcement: Track access decisions
   - Consent completion: Monitor user consent rates
   - Audit logging: Verify log completeness

### Monitoring Commands

```bash
# Check feature flag status
python -c "from src.config.feature_flags import get_feature_flags; print(get_feature_flags().get_enabled_features())"

# Monitor session memory
python -c "from src.backend.memory.session_kv import get_session_memory; print(get_session_memory().get_session_stats())"

# Check entity registry
python -c "from src.backend.entities.registry import get_entity_registry; print(get_entity_registry().get_registry_stats())"

# Monitor policy engine
python -c "from src.backend.policy.engine import get_policy_engine; print(get_policy_engine().get_policy_summary())"
```

## Troubleshooting

### Common Issues

1. **Memory Usage High**
   - Reduce `max_facts_per_session` in session memory
   - Enable Redis persistence for session data
   - Implement session cleanup scheduling

2. **Response Time Slow**
   - Check if grounding validation is enabled
   - Monitor entity registry lookup performance
   - Verify table retriever database performance

3. **Policy Enforcement Errors**
   - Verify role and department mappings
   - Check policy rule configurations
   - Review audit logs for policy decisions

4. **Entity Resolution Issues**
   - Check entity registry data quality
   - Verify name normalization logic
   - Review fuzzy matching thresholds

### Debug Mode

Enable debug logging for troubleshooting:

```bash
export LOG_LEVEL=DEBUG
export FINSOLVE_DEBUG_MODE=true
```

## Testing

### Unit Tests
```bash
# Run unit tests for new modules
python -m pytest tests/unit/test_memory.py -v
python -m pytest tests/unit/test_entities.py -v
python -m pytest tests/unit/test_policy.py -v
python -m pytest tests/unit/test_grounding.py -v
```

### Integration Tests
```bash
# Run integration tests
python -m pytest tests/integration/test_rag_pipeline.py -v
python -m pytest tests/integration/test_policy_enforcement.py -v
```

### End-to-End Tests
```bash
# Run E2E chat tests
python -m pytest tests/test_chat_replays.py -v
```

## Support

For issues or questions during migration:

1. Check the logs for error messages
2. Review feature flag configuration
3. Verify environment variables
4. Check database connectivity
5. Review policy configurations

### Emergency Contacts

- **Technical Issues**: Check logs and rollback features
- **Performance Issues**: Disable high-impact features
- **Security Issues**: Disable policy enforcement immediately
- **Data Issues**: Clear entity registry and table data

## Conclusion

The new RAG pipeline improvements provide significant enhancements to conversation consistency, data security, and answer quality. By following this phased migration approach, you can safely enable features while maintaining system stability and performance.

Remember:
- Start with low-impact features
- Monitor performance closely
- Test thoroughly in staging
- Have rollback procedures ready
- Document any issues encountered

The feature flags ensure that you can always return to the previous behavior if needed, making this a safe and controlled migration process.
