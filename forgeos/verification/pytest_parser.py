import json
import os
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class FailureRecord(BaseModel):
    """Normalized object representing a specifically failed test."""
    test_name: str
    status: str
    file: str
    exception_type: str
    assertion_summary: str
    expected: str = ""
    actual: str = ""
    traceback_summary: str
    failure_class_hint: str = "unknown"

class SessionSummary(BaseModel):
    """High-level snapshot of the entire verification run."""
    collected_tests: int = 0
    executed_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    zero_items_collected: bool = False
    run_status: str = "failed"
    root_failure_modes: List[str] = []

class LLMTestPayload(BaseModel):
    """The compressed, LLM-facing struct replacing raw pytest standard output."""
    summary: SessionSummary
    failures: List[FailureRecord]
    
    def to_markdown(self) -> str:
        """Compresses the strict records into a densely readable prompt string."""
        if self.summary.zero_items_collected:
            return "CRITICAL VERIFICATION DEFICIT: Pytest ran but collected ZERO tests. The test runner is disconnected from the codebase or syntax errors are preventing test discovery."
            
        md = f"### Verification Session Summary\n"
        md += f"- **Status**: {self.summary.run_status.upper()}\n"
        md += f"- **Executed**: {self.summary.executed_tests} ({self.summary.passed_tests} Passed, **{self.summary.failed_tests} Failed**, {self.summary.skipped_tests} Skipped)\n\n"
        
        if self.summary.failed_tests == 0:
            md += "✅ All tests passed successfully."
            return md
            
        md += "### Failure Details (LLM Condensed View)\n"
        for idx, f in enumerate(self.failures):
            md += f"\n#### {idx+1}. {f.test_name}\n"
            md += f"- **File**: `{f.file}`\n"
            md += f"- **Exception**: `{f.exception_type}`\n"
            md += f"- **Assertion Summary**: {f.assertion_summary}\n"
            if f.expected and f.actual:
                md += f"  - **Expected**: `{f.expected}`\n"
                md += f"  - **Actual**: `{f.actual}`\n"
            md += f"- **Traceback Snippet**: {f.traceback_summary}\n"
            
        return md

class PytestAnalyzer:
    """
    Epic 52: Analyzes pytest output to extract precise, objective execution metrics.
    Prefers reading from `--json-report` (.report.json), falls back to raw text parsing.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.json_report_path = os.path.join(workspace_path, ".report.json")
        
    def _extract_expected_actual(self, crash_message: str) -> tuple[str, str]:
        """Tries to parse pytest representation of equality assertions."""
        expected, actual = "", ""
        if "assert " in crash_message and " == " in crash_message:
            # Simple heuristic for 'assert [actual] == [expected]'
            try:
                parts = crash_message.split("assert ")[1].split(" == ")
                actual = parts[0].strip()
                expected_part = parts[1].split("\n")[0].strip()
                expected = expected_part
            except Exception:
                pass
        return expected, actual

    def parse_json_report(self) -> Optional[LLMTestPayload]:
        """Reads and structures the official `pytest-json-report` output."""
        if not os.path.exists(self.json_report_path):
            return None
            
        try:
            with open(self.json_report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            summary = data.get("summary", {})
            collected = summary.get("collected", 0)
            
            sess = SessionSummary(
                collected_tests=collected,
                passed_tests=summary.get("passed", 0),
                failed_tests=summary.get("failed", 0),
                skipped_tests=summary.get("skipped", 0) + summary.get("xfailed", 0),
                run_status="passed" if data.get("exitcode", 1) == 0 else "failed",
                zero_items_collected=(collected == 0)
            )
            sess.executed_tests = sess.passed_tests + sess.failed_tests + sess.skipped_tests
            
            failures = []
            for test in data.get("tests", []):
                if test.get("outcome") == "failed":
                    call = test.get("call", {})
                    crash = call.get("crash", {})
                    longrepr = call.get("longrepr", "")
                    
                    exc_type = crash.get("message", "UnknownError").split(":")[0] if crash.get("message") else "UnknownError"
                    assert_msg = crash.get("message", "No message provided")
                    
                    exp, act = self._extract_expected_actual(longrepr)
                    
                    # Compress the traceback to the last 3 meaningful lines
                    tb_lines = longrepr.split("\n")
                    tb_snippet = " | ".join(tb_lines[-5:]) if len(tb_lines) >= 5 else longrepr.replace("\n", " | ")
                    
                    failures.append(FailureRecord(
                        test_name=test.get("nodeid", "unknown"),
                        status="failed",
                        file=crash.get("path", test.get("nodeid").split("::")[0]),
                        exception_type=exc_type,
                        assertion_summary=assert_msg.strip(),
                        expected=exp,
                        actual=act,
                        traceback_summary=tb_snippet[:300] + "..." if len(tb_snippet) > 300 else tb_snippet
                    ))
                    
            return LLMTestPayload(summary=sess, failures=failures)
            
        except Exception as e:
            print(f"Failed to parse Pytest JSON report: {e}")
            return None

    def analyze(self, raw_stdout: str) -> LLMTestPayload:
        """
        Main entrypoint. Tries JSON, then falls back to extracting failure payloads directly from raw stdout.
        """
        payload = self.parse_json_report()
        if payload:
            return payload
            
        # --- Fallback text parser (WIP) ---
        return self._fallback_text_parser(raw_stdout)
        
    def _fallback_text_parser(self, stdout: str) -> LLMTestPayload:
        """Fallback Regex engine when JSON is not available (e.g. repo strictly forces version lock)."""
        sess = SessionSummary(run_status="failed")
        failures = []
        
        if "collected 0 items" in stdout or "no tests ran" in stdout.lower():
            sess.zero_items_collected = True
            return LLMTestPayload(summary=sess, failures=[])
            
        # Basic failure counting heuristic
        fail_match = re.search(r'(\d+) failed', stdout)
        pass_match = re.search(r'(\d+) passed', stdout)
        if fail_match: sess.failed_tests = int(fail_match.group(1))
        if pass_match: sess.passed_tests = int(pass_match.group(1))
        sess.executed_tests = sess.failed_tests + sess.passed_tests
        sess.run_status = "passed" if sess.failed_tests == 0 and sess.passed_tests > 0 else "failed"
        
        # In Fallback mode, we just grab the raw text but summarize it. 
        # (A fully strict text parser for pytest is notoriously brittle, hence why we rely on JSON primarily)
        if sess.failed_tests > 0:
            failures.append(FailureRecord(
                test_name="fallback_parser_aggregate",
                status="failed",
                file="unknown",
                exception_type="MultipleErrors",
                assertion_summary=f"Found {sess.failed_tests} failing tests in raw text output.",
                traceback_summary="[JSON report missing. Please install pytest-json-report for exact granular stack traces.]"
            ))
            
        return LLMTestPayload(summary=sess, failures=failures)
