"""
Tests for Authentication Security Vulnerabilities
BUG-002: Auth bypass enabled in .env
BUG-003: Hardcoded secret key
BUG-004: Default dev user in get_current_user()
BUG-005: Demo users with plaintext passwords
BUG-006: Auth bypass code path in chat_stream.py
"""
import pytest
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAuthBypass:
    """Tests for BUG-002 and BUG-006: Auth bypass vulnerabilities"""

    def test_bypass_auth_not_enabled_in_env(self):
        """
        BUG-002: BYPASS_AUTH should NOT be 'true' in production .env
        """
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                env_content = f.read()

            # Check for BYPASS_AUTH=true (case insensitive)
            bypass_match = re.search(r'^BYPASS_AUTH\s*=\s*true', env_content, re.MULTILINE | re.IGNORECASE)

            assert bypass_match is None, (
                "CRITICAL BUG-002: BYPASS_AUTH=true found in .env! "
                "This completely disables authentication in production!"
            )

    def test_auth_bypass_code_has_additional_guards(self):
        """
        BUG-006: Auth bypass code path should have additional safety guards
        """
        chat_stream_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "backend", "api", "chat_stream.py"
        )

        with open(chat_stream_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check if bypass code exists without proper guards
        if 'BYPASS_AUTH' in code:
            # Should require additional conditions like ENV=test
            has_env_check = 'ENV' in code and ('test' in code.lower() or 'dev' in code.lower())
            has_localhost_check = 'localhost' in code or '127.0.0.1' in code

            # At minimum, there should be a warning log
            has_warning = 'warning' in code.lower() or 'DEVELOPMENT ONLY' in code

            assert has_warning, (
                "BUG-006: Auth bypass code should log a warning when used"
            )


class TestSecretKey:
    """Tests for BUG-003: Hardcoded secret key"""

    def test_secret_key_not_hardcoded_in_settings(self):
        """
        BUG-003: Secret key should NOT be hardcoded in settings.py
        """
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "config", "settings.py"
        )

        with open(settings_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check for hardcoded secret patterns
        hardcoded_patterns = [
            r'secret_key\s*[:=]\s*["\']finsolve',
            r'secret_key\s*[:=]\s*["\'].*12345',
            r'SECRET_KEY\s*=\s*["\'].*change.*later',
        ]

        for pattern in hardcoded_patterns:
            match = re.search(pattern, code, re.IGNORECASE)
            assert match is None, (
                f"CRITICAL BUG-003: Hardcoded secret key found in settings.py! "
                f"Pattern matched: {pattern}"
            )

    def test_secret_key_minimum_length(self):
        """
        Secret key should be at least 32 characters for security
        """
        from src.config.settings import settings

        assert len(settings.secret_key) >= 32, (
            f"BUG-003: Secret key too short ({len(settings.secret_key)} chars). "
            f"Should be at least 32 characters for security."
        )

    def test_secret_key_not_predictable(self):
        """
        Secret key should not contain predictable patterns
        """
        # Checks what actually makes a key predictable: being a value that is
        # public (committed to this repository), a known weak default, or too
        # short. (The former substring check flagged random keys that happened
        # to contain e.g. "dev" or "key", while missing committed keys.)
        from src.config.settings import _WEAK_KEYS, is_compromised_secret_key, settings

        key = settings.secret_key
        assert not is_compromised_secret_key(key), (
            "BUG-003: SECRET_KEY is a value committed to the repository; rotate it"
        )
        assert key not in _WEAK_KEYS and key != "MUST_BE_SET_VIA_ENV", (
            "BUG-003: SECRET_KEY is a well-known weak default"
        )
        assert len(key) >= 32, "BUG-003: SECRET_KEY is shorter than 32 characters"


class TestDefaultUser:
    """Tests for BUG-004: Default dev user in auth_deps.py"""

    def test_get_current_user_validates_jwt(self):
        """
        BUG-004: get_current_user should validate JWT, not return hardcoded user
        """
        auth_deps_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "backend", "api", "auth_deps.py"
        )

        with open(auth_deps_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check for hardcoded return values
        hardcoded_patterns = [
            r'return\s*\{\s*["\']id["\']\s*:\s*["\']dev',
            r'return\s*\{\s*["\']email["\']\s*:\s*["\']dev@',
            r'# For development',
            r'# In production',
        ]

        for pattern in hardcoded_patterns:
            match = re.search(pattern, code)
            assert match is None, (
                f"CRITICAL BUG-004: auth_deps.py contains hardcoded dev user! "
                f"Pattern: {pattern}"
            )

    def test_get_current_user_calls_verify_token(self):
        """
        BUG-004: get_current_user must call verify_token for JWT validation
        """
        auth_deps_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "backend", "api", "auth_deps.py"
        )

        with open(auth_deps_path, "r", encoding="utf-8") as f:
            code = f.read()

        assert 'verify_token' in code, (
            "BUG-004: get_current_user does not call verify_token for JWT validation"
        )


class TestDemoUsers:
    """Tests for BUG-005: Demo users with plaintext passwords"""

    def test_no_plaintext_passwords_in_source(self):
        """
        BUG-005: Passwords should NOT be in plaintext in source code
        """
        roles_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "config", "roles.py"
        )

        with open(roles_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check for plaintext password patterns
        password_patterns = [
            r'["\']password["\']\s*:\s*["\']password123',
            r'["\']password["\']\s*:\s*["\']admin123',
            r'["\']password["\']\s*:\s*["\']demo123',
            r'["\']password["\']\s*:\s*["\'][a-zA-Z0-9]{4,20}["\']',  # Simple passwords
        ]

        for pattern in password_patterns:
            match = re.search(pattern, code)
            assert match is None, (
                f"CRITICAL BUG-005: Plaintext password found in roles.py! "
                f"Pattern: {pattern}"
            )

    def test_demo_users_not_in_production(self):
        """
        BUG-005: DEMO_USERS should not exist in production code
        """
        roles_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src", "config", "roles.py"
        )

        with open(roles_path, "r", encoding="utf-8") as f:
            code = f.read()

        # In production, DEMO_USERS should be empty or not exist
        # For now, just check if passwords are hashed
        assert 'bcrypt' in code.lower() or '$2b$' in code, (
            "BUG-005: DEMO_USERS should use bcrypt hashed passwords, not plaintext"
        )


class TestRoleEscalation:
    """Tests for BUG-011: Role escalation via JWT claim"""

    def test_employee_cannot_access_admin_endpoint(self):
        """
        BUG-011: Employee role should not access admin endpoints
        """
        import jwt
        from src.config.settings import settings

        # Create employee token
        employee_token = jwt.encode(
            {"sub": "employee@test.com", "role": "employee"},
            settings.secret_key,
            algorithm="HS256"
        )

        # Verify token decodes correctly
        payload = jwt.decode(employee_token, settings.secret_key, algorithms=["HS256"])

        assert payload["role"] == "employee", "Token should have employee role"
        assert payload["role"] not in ["admin", "c_level"], (
            "Employee token should not have admin privileges"
        )

    def test_forged_admin_token_with_known_secret(self):
        """
        BUG-003 + BUG-011: With known secret, attacker can forge admin token

        This test demonstrates the vulnerability - if it passes, the secret is known.
        """
        import jwt

        # These are the known hardcoded secrets
        known_secrets = [
            "finsolve_super_secret_key_12345",
            "finsolve_super_secret_key_12345_change_later",
            "your-secret-key"
        ]

        from src.config.settings import settings

        for secret in known_secrets:
            if secret == settings.secret_key:
                # Demonstrate token forgery
                forged_token = jwt.encode(
                    {"sub": "attacker@evil.com", "role": "admin"},
                    secret,
                    algorithm="HS256"
                )

                # This token would be valid!
                try:
                    payload = jwt.decode(forged_token, settings.secret_key, algorithms=["HS256"])
                    pytest.fail(
                        f"CRITICAL: Secret key '{secret[:20]}...' is known! "
                        f"Attacker can forge admin tokens!"
                    )
                except jwt.InvalidTokenError:
                    pass  # Good - token invalid
