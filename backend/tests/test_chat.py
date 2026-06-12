from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("DB_PASSWORD", "secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "cid")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "csecret")
os.environ.setdefault("GEMINI_API_KEY", "gkey")
os.environ.setdefault("BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("ENVIRONMENT", "development")


# Make backend/app importable.
# Expected location: backend/tests/test_chat_sql_validation.py
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


from app.api.chat_gemini import parse_sql_generation_response, validate_sql  # noqa: E402


# =============================================================================
# parse_sql_generation_response — valid payloads
# =============================================================================

@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            '{"can_answer": true, "reason": null, "sql": "SELECT id FROM repositories"}',
            (True, None, "SELECT id FROM repositories"),
        ),
        (
            (
                "```json\n"
                '{"can_answer": true, "reason": null, "sql": "SELECT id FROM repositories"}\n'
                "```"
            ),
            (True, None, "SELECT id FROM repositories"),
        ),
        (
            '{"can_answer": false, "reason": "Not enough data.", "sql": null}',
            (False, "Not enough data.", None),
        ),
        (
            # Trailing semicolon should be stripped.
            '{"can_answer": true, "reason": null, "sql": "SELECT id FROM repositories;"}',
            (True, None, "SELECT id FROM repositories"),
        ),
    ],
)
def test_parse_sql_generation_response_accepts_valid_payloads(
    raw: str,
    expected: tuple[bool, str | None, str | None],
) -> None:
    assert parse_sql_generation_response(raw) == expected


# =============================================================================
# parse_sql_generation_response — malformed payloads
# =============================================================================

@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",                                                        # Array instead of object.
        "{}",                                                        # Missing all keys.
        '{"can_answer": true, "reason": null}',                     # Missing sql.
        '{"can_answer": true, "reason": null, "sql": null}',        # can_answer=true but sql=null.
        '{"can_answer": "yes", "reason": null, "sql": null}',       # can_answer is a string.
        '{"can_answer": true, "reason": 123, "sql": "SELECT 1"}',   # reason is a number.
        '{"can_answer": true, "reason": null, "sql": 123}',         # sql is a number.
    ],
)
def test_parse_sql_generation_response_rejects_malformed_payloads(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        parse_sql_generation_response(raw)


# =============================================================================
# validate_sql — safe analytics queries should pass
# =============================================================================

@pytest.mark.parametrize(
    "sql",
    [
        # Basic select with explicit columns.
        """
        SELECT id, full_name
        FROM repositories
        LIMIT 10
        """,

        # JOIN + GROUP BY + ORDER BY alias.
        """
        SELECT r.full_name, COUNT(pr.id) AS pr_count
        FROM repositories r
        JOIN pull_requests pr ON pr.repo_id = r.id
        GROUP BY r.full_name
        ORDER BY pr_count DESC
        LIMIT 10
        """,

        # PRs grouped by author.
        """
        SELECT pr.author_login, COUNT(pr.id) AS pr_count
        FROM pull_requests pr
        GROUP BY pr.author_login
        ORDER BY pr_count DESC
        LIMIT 10
        """,

        # Aggregate — no LIMIT needed.
        """
        SELECT AVG(rv.risk_score) AS avg_risk_score
        FROM reviews rv
        """,

        # Date range filter.
        """
        SELECT pr.title, pr.author_login, pr.opened_at
        FROM pull_requests pr
        WHERE pr.opened_at >= NOW() - INTERVAL '30 days'
        ORDER BY pr.opened_at DESC
        LIMIT 20
        """,

        # Boolean filter.
        """
        SELECT pr.title, pr.has_migrations
        FROM pull_requests pr
        WHERE pr.has_migrations = TRUE
        LIMIT 20
        """,

        # Newly added review columns.
        """
        SELECT rv.summary, rv.risk_score, rv.created_at
        FROM reviews rv
        WHERE rv.summary IS NOT NULL
        ORDER BY rv.created_at DESC
        LIMIT 10
        """,

        # Deployment duration.
        """
        SELECT d.environment, AVG(d.deploy_duration) AS avg_deploy_duration
        FROM deployments d
        WHERE d.status = 'success'
        GROUP BY d.environment
        ORDER BY avg_deploy_duration DESC
        LIMIT 10
        """,

        # CTE / WITH query.
        """
        WITH repo_pr_counts AS (
            SELECT pr.repo_id, COUNT(pr.id) AS pr_count
            FROM pull_requests pr
            GROUP BY pr.repo_id
        )
        SELECT r.full_name, rpc.pr_count
        FROM repositories r
        JOIN repo_pr_counts rpc ON rpc.repo_id = r.id
        ORDER BY rpc.pr_count DESC
        LIMIT 10
        """,

        # UNION — both sides are read-only.
        """
        SELECT full_name AS label
        FROM repositories
        WHERE is_active = TRUE
        UNION
        SELECT author_login AS label
        FROM pull_requests
        LIMIT 20
        """,
    ],
)
def test_validate_sql_allows_safe_analytics_queries(sql: str) -> None:
    validate_sql(sql)


# =============================================================================
# validate_sql — COUNT(*) must pass
# =============================================================================
# Important: SELECT * should be blocked, but COUNT(*) must be allowed.
# If this test fails, the SELECT-star validator is too strict.
# Fix: in validate_no_select_star, skip stars whose parent is exp.Count.

def test_validate_sql_allows_count_star() -> None:
    sql = """
    SELECT COUNT(*) AS pr_count
    FROM pull_requests
    """
    validate_sql(sql)


# =============================================================================
# validate_sql — newly added safe columns must all pass
# =============================================================================

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT github_repo_id, created_at FROM repositories LIMIT 10",
        "SELECT github_pr_id, title, author_login FROM pull_requests LIMIT 10",
        "SELECT files_changed, has_migrations FROM pull_requests LIMIT 10",
        "SELECT summary, posted_to_github, completed_at FROM reviews LIMIT 10",
        "SELECT line_number, suggestion, created_at FROM review_issues LIMIT 10",
        "SELECT deploy_duration FROM deployments LIMIT 10",
    ],
)
def test_validate_sql_allows_new_safe_columns(sql: str) -> None:
    validate_sql(sql)


# =============================================================================
# validate_sql — forbidden queries must fail
# =============================================================================

@pytest.mark.parametrize(
    "sql, expected_message",
    [
        # ------------------------------------------------------------------
        # SELECT * variations
        # ------------------------------------------------------------------
        (
            "SELECT * FROM repositories",
            r"SELECT \* is not allowed",
        ),
        (
            "SELECT r.* FROM repositories r",
            r"SELECT \* is not allowed",
        ),
        (
            "SELECT * FROM users",
            r"SELECT \* is not allowed",
        ),

        # ------------------------------------------------------------------
        # Mutating / DDL statements
        # ------------------------------------------------------------------
        (
            "DELETE FROM repositories",
            "Only read-only SELECT queries are allowed",
        ),
        (
            "UPDATE repositories SET is_active = false",
            "Only read-only SELECT queries are allowed",
        ),
        (
            "INSERT INTO repositories(id) VALUES(gen_random_uuid())",
            "Only read-only SELECT queries are allowed",
        ),
        (
            "DROP TABLE repositories",
            "Only read-only SELECT queries are allowed",
        ),
        (
            "ALTER TABLE repositories ADD COLUMN x TEXT",
            "Only read-only SELECT queries are allowed",
        ),

        # ------------------------------------------------------------------
        # Sensitive columns (unqualified)
        # ------------------------------------------------------------------
        (
            "SELECT webhook_secret FROM repositories",
            "Unknown or disallowed column: webhook_secret",
        ),
        (
            "SELECT webhook_id FROM repositories",
            "Unknown or disallowed column: webhook_id",
        ),
        (
            "SELECT agent_trace FROM reviews",
            "Unknown or disallowed column: agent_trace",
        ),

        # ------------------------------------------------------------------
        # Sensitive columns (qualified with alias)
        # ------------------------------------------------------------------
        (
            "SELECT r.webhook_secret FROM repositories r",
            "Column 'webhook_secret' is not allowed on table 'repositories'",
        ),
        (
            "SELECT r.webhook_id FROM repositories r",
            "Column 'webhook_id' is not allowed on table 'repositories'",
        ),
        (
            "SELECT rv.agent_trace FROM reviews rv",
            "Column 'agent_trace' is not allowed on table 'reviews'",
        ),

        # ------------------------------------------------------------------
        # Disallowed tables
        # ------------------------------------------------------------------
        (
            "SELECT id FROM users",
            "Disallowed table referenced: users",
        ),

        # ------------------------------------------------------------------
        # Disallowed schema
        # ------------------------------------------------------------------
        (
            "SELECT id FROM private_schema.repositories",
            "Disallowed schema reference: private_schema",
        ),

        # ------------------------------------------------------------------
        # Multiple statements
        # ------------------------------------------------------------------
        (
            "SELECT id FROM repositories; DROP TABLE repositories",
            "Only one SQL statement is allowed",
        ),

        # ------------------------------------------------------------------
        # Forbidden functions
        # ------------------------------------------------------------------
        (
            "SELECT pg_sleep(10)",
            "Forbidden function call: pg_sleep",
        ),

        # ------------------------------------------------------------------
        # Unknown / invented columns
        # ------------------------------------------------------------------
        (
            "SELECT repo_name FROM repositories",
            "Unknown or disallowed column: repo_name",
        ),

        # ------------------------------------------------------------------
        # Column on wrong table
        # ------------------------------------------------------------------
        (
            "SELECT r.author_login FROM repositories r",
            "Column 'author_login' is not allowed on table 'repositories'",
        ),

        # ------------------------------------------------------------------
        # Unknown alias
        # ------------------------------------------------------------------
        (
            "SELECT x.full_name FROM repositories r",
            "Unknown table or alias: x",
        ),
    ],
)
def test_validate_sql_rejects_forbidden_queries(
    sql: str,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        validate_sql(sql)