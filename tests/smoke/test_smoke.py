"""Gate G0: Smoke tests — all modules importable, no secrets in code."""

import importlib
import os
import re


class TestImports:
    def test_schemas_importable(self):
        import schemas
        assert schemas is not None

    def test_all_schema_modules_importable(self):
        modules = [
            "schemas.incident",
            "schemas.evidence",
            "schemas.rca",
            "schemas.confidence",
            "schemas.policy",
            "schemas.action",
            "schemas.verification",
        ]
        for mod in modules:
            m = importlib.import_module(mod)
            assert m is not None, f"Failed to import {mod}"

    def test_core_modules_importable(self):
        import core.config
        import core.logging
        assert core.config is not None
        assert core.logging is not None


class TestNoSecretsInCode:
    """Scan source files for hardcoded credentials."""

    SECRET_PATTERNS = [
        re.compile(r'(?i)(password|passwd|secret|api_key|apikey|token)\s*=\s*["\'][^"\']{4,}["\']'),
        re.compile(r'(?i)postgresql://[^:]+:[^@]{4,}@'),
        re.compile(r'(?i)redis://:[^@]{4,}@'),
        re.compile(r'AKIA[0-9A-Z]{16}'),  # AWS Access Key ID pattern
    ]

    ALLOWED_PATHS = {
        ".env.example",
        "deploy/migrations/alembic.ini",
    }

    def _get_source_files(self) -> list[str]:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        result = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "venv", "__pycache__", ".git"}]
            for fname in filenames:
                if fname.endswith(".py"):
                    result.append(os.path.join(dirpath, fname))
        return result

    def test_no_hardcoded_secrets_in_python_files(self):
        violations = []
        for fpath in self._get_source_files():
            # Test files intentionally contain fake secrets for testing sanitizers
            if "test_" in os.path.basename(fpath):
                continue
            try:
                content = open(fpath, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in self.SECRET_PATTERNS:
                if pattern.search(content):
                    violations.append(fpath)
                    break
        assert violations == [], f"Potential secrets found in: {violations}"
