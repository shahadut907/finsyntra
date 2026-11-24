# Enterprise RAG Makefile
.PHONY: help test migrate reconcile benchmark clean worker backfill rollout rollback

# Variables
PYTHON := python3
ALEMBIC := alembic
PYTEST := pytest
DATABASE_URL ?= postgresql://postgres:password@localhost:5432/finsolve
TEST_DATABASE_URL ?= postgresql://postgres:password@localhost:5432/test_finsolve
REDIS_URL ?= redis://localhost:6379/0

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "Enterprise RAG Management Commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# Database Management
migrate: ## Run database migrations
	@echo "$(YELLOW)Running database migrations...$(NC)"
	$(ALEMBIC) upgrade head
	@echo "$(GREEN)✅ Migrations complete$(NC)"

migrate-rollback: ## Rollback last migration
	@echo "$(YELLOW)Rolling back last migration...$(NC)"
	$(ALEMBIC) downgrade -1
	@echo "$(GREEN)✅ Rollback complete$(NC)"

backfill: ## Backfill lifecycle metadata
	@echo "$(YELLOW)Running metadata backfill...$(NC)"
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) scripts/backfill_metadata.py --batch-size 500
	@echo "$(GREEN)✅ Backfill complete$(NC)"

backfill-dry: ## Preview backfill changes
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) scripts/backfill_metadata.py --dry-run

# Vector Store Management
reconcile: ## Run vector reconciliation
	@echo "$(YELLOW)Running vector reconciliation...$(NC)"
	DATABASE_URL=$(DATABASE_URL) ENABLE_RECONCILIATION=true $(PYTHON) scripts/reconcile_vectors.py
	@echo "$(GREEN)✅ Reconciliation complete$(NC)"

reconcile-dry: ## Preview reconciliation changes
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) scripts/reconcile_vectors.py --dry-run

reconcile-force: ## Force reconciliation (bypass flags)
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) scripts/reconcile_vectors.py --force

clean-backups: ## Remove backup folders
	@echo "$(YELLOW)🗑️  Removing backup folders...$(NC)"
	@find ./src/data/embeddings -name '*BACKUP*' -type d -exec rm -rf {} + 2>/dev/null || true
	@find ./src/data/embeddings -name '*backup*' -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✅ Backup folders removed$(NC)"

diagnose: ## Run vector store diagnostics
	$(PYTHON) scripts/diagnose_vectors.py

# Worker Management
worker: ## Start deletion worker
	@echo "$(YELLOW)Starting deletion worker...$(NC)"
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) ENABLE_DELETION_WORKER=true \
		$(PYTHON) -m src.backend.workers.vector_deletion_worker

worker-status: ## Check worker status
	@ps aux | grep -v grep | grep vector_deletion_worker || echo "Worker not running"

# Testing
test: ## Run test suite (legacy mode)
	@echo "$(YELLOW)Running tests with flags OFF (legacy mode)...$(NC)"
	STRICT_MODE=false TENANT_SCOPING_ON=false ENABLE_DELETION_WORKER=false \
		TEST_DATABASE_URL=$(TEST_DATABASE_URL) \
		$(PYTEST) tests/test_enterprise_rag.py -v

test-strict: ## Run tests with strict mode
	@echo "$(YELLOW)Running tests with flags ON (strict mode)...$(NC)"
	STRICT_MODE=true TENANT_SCOPING_ON=true ENABLE_DELETION_WORKER=true \
		TEST_DATABASE_URL=$(TEST_DATABASE_URL) \
		$(PYTEST) tests/test_enterprise_rag.py -v

test-all: test test-strict ## Run all tests (legacy + strict)

benchmark: ## Run performance benchmarks
	@echo "$(YELLOW)Running performance benchmarks...$(NC)"
	STRICT_MODE=true TENANT_SCOPING_ON=true \
		TEST_DATABASE_URL=$(TEST_DATABASE_URL) \
		$(PYTEST) tests/test_enterprise_rag.py::TestEnterpriseRAG::test_scale_p95_latency -v

test-regression: ## Run regression tests only
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) \
		$(PYTEST) tests/test_enterprise_rag.py -k "legacy" -v

# CI/CD Targets
ci-setup: ## Setup CI environment
	pip install -r requirements.txt
	pip install pytest pytest-cov pytest-benchmark pytest-asyncio

ci-test: migrate ## Run CI test suite
	STRICT_MODE=false $(MAKE) test
	STRICT_MODE=true $(MAKE) test-strict
	$(MAKE) test-regression

ci-benchmark: ## Run CI benchmarks
	$(MAKE) benchmark

# Deployment & Rollout
deploy-stage-1: ## Stage 1: Deploy with flags OFF
	@echo "$(YELLOW)🚀 Stage 1: Deploying with flags OFF...$(NC)"
	@echo "STRICT_MODE=false" >> .env
	@echo "TENANT_SCOPING_ON=false" >> .env
	@echo "ENABLE_DELETION_WORKER=false" >> .env
	@echo "ENABLE_RECONCILIATION=false" >> .env
	$(MAKE) migrate
	$(MAKE) backfill-dry
	@echo "$(GREEN)✅ Stage 1 complete - System running in compatibility mode$(NC)"

deploy-stage-2: ## Stage 2: Enable deletion worker
	@echo "$(YELLOW)🚀 Stage 2: Enabling deletion worker...$(NC)"
	@echo "ENABLE_DELETION_WORKER=true" >> .env
	$(MAKE) worker &
	@echo "$(GREEN)✅ Stage 2 complete - Deletion worker enabled$(NC)"

deploy-stage-3: ## Stage 3: Enable strict mode (10%)
	@echo "$(YELLOW)🚀 Stage 3: Enabling strict mode for canary (10%)...$(NC)"
	@echo "STRICT_MODE=true" >> .env
	@echo "$(GREEN)✅ Stage 3 complete - Strict mode enabled for canary$(NC)"

deploy-stage-4: ## Stage 4: Enable tenant scoping
	@echo "$(YELLOW)🚀 Stage 4: Enabling tenant scoping...$(NC)"
	@echo "TENANT_SCOPING_ON=true" >> .env
	@echo "ENABLE_RECONCILIATION=true" >> .env
	$(MAKE) reconcile
	@echo "$(GREEN)✅ Stage 4 complete - Full enterprise features enabled$(NC)"

rollback: ## Emergency rollback
	@echo "$(RED)⚠️  EMERGENCY ROLLBACK$(NC)"
	@echo "STRICT_MODE=false" > .env.rollback
	@echo "TENANT_SCOPING_ON=false" >> .env.rollback
	@echo "ENABLE_DELETION_WORKER=false" >> .env.rollback
	@echo "ENABLE_RECONCILIATION=false" >> .env.rollback
	@mv .env .env.backup
	@mv .env.rollback .env
	@pkill -f vector_deletion_worker || true
	@echo "$(GREEN)✅ Rollback complete - System in legacy mode$(NC)"

# Monitoring
monitor: ## Monitor system metrics
	@echo "$(YELLOW)System Metrics:$(NC)"
	@echo -n "Vector drift: "
	@DATABASE_URL=$(DATABASE_URL) $(PYTHON) -c "from scripts.reconcile_vectors import *; import asyncio; r = EnterpriseReconciler('$(DATABASE_URL)', dry_run=True); asyncio.run(r.run())" 2>/dev/null | grep "Final drift" || echo "Unknown"
	@echo -n "Pending deletion jobs: "
	@psql $(DATABASE_URL) -t -c "SELECT COUNT(*) FROM vector_deletion_jobs WHERE status='pending'" 2>/dev/null || echo "Unknown"
	@echo -n "Worker status: "
	@$(MAKE) worker-status

health: ## Check system health
	@echo "$(YELLOW)System Health Check:$(NC)"
	@curl -s http://localhost:8000/health | python -m json.tool || echo "API not responding"

# Development
dev-setup: ## Setup development environment
	pip install -r requirements-dev.txt
	pre-commit install
	$(MAKE) migrate
	$(MAKE) clean-backups

dev-reset: ## Reset development database
	@echo "$(RED)⚠️  This will delete all data!$(NC)"
	@read -p "Continue? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	psql $(DATABASE_URL) -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) migrate
	@echo "$(GREEN)✅ Database reset complete$(NC)"

# Docker Support
docker-up: ## Start dependencies (Postgres, Redis)
	docker-compose up -d postgres redis

docker-down: ## Stop dependencies
	docker-compose down

docker-logs: ## View dependency logs
	docker-compose logs -f

# Utilities
check-flags: ## Display current feature flags
	@echo "$(YELLOW)Current Feature Flags:$(NC)"
	@echo "STRICT_MODE: $${STRICT_MODE:-false}"
	@echo "TENANT_SCOPING_ON: $${TENANT_SCOPING_ON:-false}"
	@echo "ENABLE_DELETION_WORKER: $${ENABLE_DELETION_WORKER:-false}"
	@echo "ENABLE_RECONCILIATION: $${ENABLE_RECONCILIATION:-false}"
	@echo "BLOCK_BACKUP_FOLDERS: $${BLOCK_BACKUP_FOLDERS:-true}"
	@echo "$(CYAN)Collection/Cache Flags:$(NC)"
	@echo "CANONICAL_COLLECTION_ENFORCED: $${CANONICAL_COLLECTION_ENFORCED:-false}"
	@echo "ENABLE_CROSS_PROCESS_CACHE_SYNC: $${ENABLE_CROSS_PROCESS_CACHE_SYNC:-false}"
	@echo "ENABLE_UPLOAD_LOGGING: $${ENABLE_UPLOAD_LOGGING:-false}"

validate: ## Validate deployment readiness
	@echo "$(YELLOW)Validating deployment readiness...$(NC)"
	@$(MAKE) test-regression
	@$(MAKE) reconcile-dry
	@$(MAKE) check-flags
	@echo "$(GREEN)✅ System ready for deployment$(NC)"

test-flags: ## Test flag-gated features
	@echo "$(YELLOW)Testing flag-gated features...$(NC)"
	@python -m pytest tests/test_collection_cache_fixes.py -v
	@echo "$(GREEN)✅ Flag tests passed$(NC)"

validate-flags: ## Validate flag configuration and behavior
	@echo "$(YELLOW)Validating flag configuration...$(NC)"
	@$(MAKE) check-flags
	@python -c "from src.config.settings import settings; print('✅ Settings loaded successfully')"
	@python -c "from src.backend.services.cache_manager import cache_manager; print('✅ Cache manager initialized')"
	@python -c "from src.backend.services.vector_store import VectorStore; vs = VectorStore(); print(f'✅ Collection: {vs.collection_name}')"
	@echo "$(GREEN)✅ Flag validation complete$(NC)"

dry-run-upload: ## Simulate upload flow for testing
	@echo "$(YELLOW)Dry run upload simulation...$(NC)"
	@python -c "
import os, sys; 
sys.path.append('src');
from src.backend.services.vector_store import VectorStore;
vs = VectorStore();
print(f'Target collection: {vs.collection_name}');
print(f'Target path: {vs.persist_directory}');
print('✅ Upload target resolved')
"

.DEFAULT_GOAL := help
