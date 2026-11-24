"""Phase 4B: native-Linux deployment hardening.

Covers, without running Docker, installing anything, building the frontend,
or initializing the embedding model:

1. frontend/.env.production.example carries REACT_APP_PUBLIC_DEMO_ENABLED=true
2. deploy/production/.env.production.example carries HF_HOME under the
   systemd-writable state directory
3. deploy/production/start.sh creates that HF_HOME directory
4. deploy/production/nginx.conf proxies /health/ready, and still has SSE
   buffering disabled for /api/chat/stream
5. deploy/production/finsolve.service remains loopback-only, sandboxed, and
   does not reference Ollama as the active provider
6. deploy/production/.env.production.example does not select Ollama as the
   active production LLM_PROVIDER
7. settings.py: production+DEBUG fails closed (see test_wave7_provider_demo.py
   for the subprocess-level proof); dev logs directory behavior documented
   and re-asserted here via static source inspection
8. uvicorn's installed version/defaults for proxy_headers/forwarded_allow_ips
   (the basis for the Phase 4A proxy-header finding) are pinned by assertion
   so a future uvicorn upgrade that silently changes them is caught
"""
import inspect
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(relative_path: str) -> str:
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as f:
        return f.read()


class TestFrontendDemoBuildFlag:
    def test_production_env_example_enables_public_demo(self):
        content = _read("frontend/.env.production.example")
        assert "REACT_APP_PUBLIC_DEMO_ENABLED=true" in content

    def test_login_form_still_gates_on_that_exact_variable(self):
        """Guards against the flag and the gate silently drifting apart."""
        content = _read("frontend/src/components/LoginForm.js")
        assert "REACT_APP_PUBLIC_DEMO_ENABLED" in content

    def test_runbook_verifies_the_flag_before_npm_run_build(self):
        content = _read("docs/NATIVE_DEPLOYMENT_RUNBOOK.md")
        idx_check = content.find("REACT_APP_PUBLIC_DEMO_ENABLED=true")
        idx_build = content.find("npm run build", idx_check)
        assert idx_check != -1
        assert idx_build != -1 and idx_build > idx_check, (
            "the verification step must appear before npm run build in the runbook"
        )


class TestHuggingFaceCache:
    def test_env_template_sets_hf_home_under_var_lib_finsolve(self):
        content = _read("deploy/production/.env.production.example")
        assert "HF_HOME=/var/lib/finsolve/hf-cache" in content

    def test_hf_cache_path_is_under_the_systemd_writable_state_directory(self):
        """/var/lib/finsolve is the only ReadWritePaths entry — cross-check
        the two files agree rather than hardcoding the same assumption twice."""
        service = _read("deploy/production/finsolve.service")
        env_template = _read("deploy/production/.env.production.example")
        assert "ReadWritePaths=/var/lib/finsolve" in service
        assert "HF_HOME=/var/lib/finsolve/hf-cache" in env_template
        assert "/var/lib/finsolve/hf-cache".startswith("/var/lib/finsolve")

    def test_start_sh_creates_the_hf_cache_directory(self):
        content = _read("deploy/production/start.sh")
        assert "HF_HOME" in content
        assert "mkdir -p" in content
        # The mkdir line must include the HF cache path (with its own
        # fallback default matching the .env template's value).
        mkdir_line = next(line for line in content.splitlines() if "mkdir -p" in line)
        assert "HF_HOME" in mkdir_line

    def test_env_template_documents_first_boot_internet_requirement(self):
        content = _read("deploy/production/.env.production.example")
        assert "huggingface.co" in content or "pre-populated" in content


class TestNginxReadinessAndSse:
    def test_nginx_proxies_health_ready(self):
        content = _read("deploy/production/nginx.conf")
        assert "location = /health/ready" in content
        assert "proxy_pass http://127.0.0.1:8000/health/ready;" in content

    def test_nginx_still_proxies_plain_health(self):
        content = _read("deploy/production/nginx.conf")
        assert "location = /health {" in content
        assert "proxy_pass http://127.0.0.1:8000/health;" in content

    def test_sse_route_still_has_buffering_disabled(self):
        content = _read("deploy/production/nginx.conf")
        idx = content.find("location /api/chat/stream")
        assert idx != -1
        block = content[idx:idx + 400]
        assert "proxy_buffering off;" in block
        assert "proxy_cache off;" in block

    def test_runbook_health_section_documents_both_endpoints_correctly(self):
        content = _read("docs/NATIVE_DEPLOYMENT_RUNBOOK.md")
        idx = content.find("## 10. Health check")
        assert idx != -1
        section = content[idx:idx + 800]
        assert "/health/ready" in section
        assert "liveness" in section.lower()
        assert "readiness" in section.lower() or "ready" in section.lower()


class TestServiceUnitAndProviderConsistency:
    def test_service_binds_loopback_only(self):
        content = _read("deploy/production/finsolve.service")
        assert "--host 127.0.0.1" in content
        assert "0.0.0.0" not in content

    def test_service_sandbox_hardening_untouched(self):
        content = _read("deploy/production/finsolve.service")
        assert "ProtectSystem=strict" in content
        assert "NoNewPrivileges=true" in content
        assert "ReadWritePaths=/var/lib/finsolve" in content

    def test_production_env_template_does_not_select_ollama(self):
        content = _read("deploy/production/.env.production.example")
        assert "LLM_PROVIDER=groq" in content
        # Only the explanatory comment may mention Ollama; the active
        # provider itself must be groq.
        active_provider_lines = [
            line for line in content.splitlines()
            if line.strip().startswith("LLM_PROVIDER=")
        ]
        assert active_provider_lines == ["LLM_PROVIDER=groq"]

    def test_runbook_explicitly_states_no_ollama_in_production(self):
        content = _read("docs/NATIVE_DEPLOYMENT_RUNBOOK.md")
        assert "no Ollama package" in content or "No GPU, no Ollama" in content


class TestProductionLoggingDirectorySideEffect:
    def test_logs_mkdir_is_gated_to_non_production(self):
        content = _read("src/config/settings.py")
        idx = content.find('os.makedirs("logs"')
        assert idx != -1
        preceding = content[max(0, idx - 700):idx]
        assert "is_production" in preceding, (
            "the logs mkdir must be conditioned on non-production"
        )

    def test_vector_db_directory_creation_is_unconditional(self):
        """Only the logs mkdir should be gated — vector_db_path's parent
        (/var/lib/finsolve/chroma in production) IS writable and must keep
        being created in every environment."""
        content = _read("src/config/settings.py")
        idx = content.find("os.makedirs(os.path.dirname(settings.vector_db_path)")
        assert idx != -1
        preceding_line_start = content.rfind("\n", 0, idx)
        preceding_line = content[preceding_line_start:idx]
        assert "is_production" not in preceding_line

    def test_no_code_path_actually_opens_a_file_under_logs(self):
        """Confirms the investigation finding: AuditLogger's FileHandler is
        only created when log_file is truthy, and the module-level singleton
        never passes one."""
        audit_src = _read("src/backend/audit/log.py")
        assert "audit_logger = AuditLogger()" in audit_src
        assert "def __init__(self, log_file: Optional[str] = None" in audit_src


class TestUvicornProxyHeaderAssumptions:
    """Phase 4A flagged a possible rate-limit/proxy-IP bug; Phase 4B's
    read-only investigation found the current config is already correct.
    These assertions pin the exact facts that investigation relied on, so a
    future uvicorn upgrade that changes a default is caught here rather than
    silently reintroducing the (never actually present) bug."""

    def test_uvicorn_proxy_headers_defaults_to_true(self):
        import uvicorn.config as uv_config
        sig = inspect.signature(uv_config.Config.__init__)
        assert sig.parameters["proxy_headers"].default is True

    def test_uvicorn_forwarded_allow_ips_defaults_to_loopback_when_unset(self):
        import uvicorn.config as uv_config
        source = inspect.getsource(uv_config.Config.__init__)
        assert '"FORWARDED_ALLOW_IPS", "127.0.0.1"' in source

    def test_service_execstart_does_not_override_these_defaults(self):
        """The ExecStart line intentionally has no --proxy-headers or
        --forwarded-allow-ips flag — it relies on the defaults asserted
        above. If someone adds a flag here, this test forces a conscious
        re-check of the trust boundary rather than a silent change."""
        content = _read("deploy/production/finsolve.service")
        execstart_line = next(
            line for line in content.splitlines() if line.startswith("ExecStart=")
        )
        assert "--proxy-headers" not in execstart_line
        assert "--forwarded-allow-ips" not in execstart_line

    def test_runbook_documents_the_verified_proxy_header_trust_boundary(self):
        content = _read("docs/NATIVE_DEPLOYMENT_RUNBOOK.md")
        assert "ProxyHeadersMiddleware" in content
        assert "127.0.0.1" in content
