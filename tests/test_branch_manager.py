"""
Tests for forgeos.engine.branch_manager — the should_race() eligibility function.
These tests validate that should_race() correctly triggers branch racing
for the keywords described in GitHub issue #1.
"""
import pytest
from forgeos.engine.branch_manager import should_race


class FakeCtx:
    """Minimal ExecutionContext stub for testing should_race()."""
    def __init__(self, issue_text: str = "", racing_enabled: bool = True, retries: int = 0, plan: str = "x" * 400):
        self.issue_text = issue_text
        self.racing_enabled = racing_enabled
        self.retries = retries
        self.plan = plan


class TestShouldRaceKeywords:
    """Tests for keyword-based eligibility."""

    def test_async_triggers_race(self):
        assert should_race(FakeCtx("Fix async handling in WebSocket")) is True

    def test_timeout_triggers_race(self):
        # 'timeout' is already in TRIGGER_KEYWORDS — this should pass
        assert should_race(FakeCtx("Connection timeout after 30s under load")) is True

    def test_flaky_triggers_race(self):
        # 'flaky' is NOT yet in TRIGGER_KEYWORDS — ForgeOS must add it (issue #1)
        assert should_race(FakeCtx("intermittently flaky test on CI")) is True

    def test_deadlock_triggers_race(self):
        assert should_race(FakeCtx("Thread deadlock in connection pool")) is True

    def test_concurrent_triggers_race(self):
        assert should_race(FakeCtx("Concurrent cache writes cause corruption")) is True

    def test_integration_triggers_race(self):
        assert should_race(FakeCtx("Integration with external API fails")) is True

    def test_race_condition_triggers_race(self):
        assert should_race(FakeCtx("Race condition in file locking code")) is True


class TestShouldRaceNegative:
    """Tests for cases that should NOT trigger racing."""

    def test_racing_disabled_blocks(self):
        ctx = FakeCtx("async timeout deadlock", racing_enabled=False)
        assert should_race(ctx) is False

    def test_simple_typo_no_race(self):
        # No keywords, no retries, long plan → no race
        ctx = FakeCtx(issue_text="Fix typo in README", retries=0, plan="x" * 600)
        assert should_race(ctx) is False

    def test_empty_issue_no_race_unless_short_plan(self):
        ctx = FakeCtx(issue_text="", retries=0, plan="x" * 600)
        assert should_race(ctx) is False


class TestShouldRaceRetries:
    """Retries > 0 should always trigger race."""

    def test_retry_triggers_race(self):
        ctx = FakeCtx(issue_text="Fix minor bug", retries=1, plan="x" * 600)
        assert should_race(ctx) is True
