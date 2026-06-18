"""
Run this script to verify your local environment is configured correctly before debugging.

    python scripts/check_env.py
"""
from __future__ import annotations

import sys


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def check_python_version() -> bool:
    print("\n--- Python ---")
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 12):
        _ok(f"Python {major}.{minor}")
        return True
    _fail(f"Python {major}.{minor} — requires 3.12+")
    return False


def check_env_file() -> bool:
    print("\n--- .env file ---")
    from pathlib import Path
    env_path = Path(".env")
    if not env_path.exists():
        _fail(".env not found — run `make env` or copy .env.example to .env")
        return False
    _ok(".env exists")

    content = env_path.read_text(encoding="utf-8")
    all_ok = True
    for key in ["DATABASE_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OPENAI_API_KEY"]:
        line = next((l for l in content.splitlines() if l.startswith(f"{key}=")), None)
        if line is None:
            _warn(f"{key} not set")
            all_ok = False
        elif "replace-me" in line:
            _warn(f"{key} is still set to 'replace-me'")
        else:
            _ok(f"{key} is set")
    return all_ok


def check_settings() -> bool:
    print("\n--- Settings / job_criteria.yml ---")
    try:
        from openclaw.core.config import get_settings
        s = get_settings()
        _ok(f"Settings loaded — TJM floor: {s.minimum_tjm}, remote_required: {s.remote_required}")
        _ok(f"Required keywords: {s.required_keywords}")
        _ok(f"Platform targets: {s.platform_targets}")
        return True
    except Exception as exc:
        _fail(f"Settings failed to load: {exc}")
        return False


def check_database() -> bool:
    print("\n--- Database ---")
    try:
        from openclaw.db.session import check_db_connection
        if check_db_connection():
            _ok("PostgreSQL reachable")
            return True
        _fail("PostgreSQL unreachable — run `make db-up` and wait for it to become healthy")
        return False
    except Exception as exc:
        _fail(f"DB check error: {exc}")
        return False


def check_tables() -> bool:
    print("\n--- Database tables ---")
    try:
        from sqlalchemy import inspect
        from openclaw.db.session import engine
        inspector = inspect(engine)
        expected = {"opportunities", "proposal_examples", "resumes", "proposal_drafts", "platform_accounts", "outcomes"}
        existing = set(inspector.get_table_names())
        missing = expected - existing
        if missing:
            _warn(f"Missing tables: {sorted(missing)} — run `make db-create-tables`")
            return False
        _ok(f"All expected tables exist: {sorted(expected)}")
        return True
    except Exception as exc:
        _fail(f"Table check error: {exc}")
        return False


def check_playwright() -> bool:
    print("\n--- Playwright ---")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _ok("Chromium launches successfully")
        return True
    except Exception as exc:
        _fail(f"Playwright/Chromium not ready: {exc}")
        _warn("Run: make playwright-install")
        return False


def main() -> None:
    print("=" * 50)
    print("  OpenClaw — local environment check")
    print("=" * 50)

    results = [
        check_python_version(),
        check_env_file(),
        check_settings(),
        check_database(),
        check_tables(),
        check_playwright(),
    ]

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"  All {total} checks passed. You are ready to debug.")
    else:
        print(f"  {passed}/{total} checks passed. Fix the items marked [FAIL] or [WARN] above.")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
