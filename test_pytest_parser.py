import os
import json
from forgeos.verification.pytest_parser import PytestAnalyzer

# Create mock environment
os.makedirs("/tmp/mock_pytest_run", exist_ok=True)
mock_json = {
    "summary": {"collected": 20, "passed": 18, "failed": 2, "skipped": 0},
    "exitcode": 1,
    "tests": [
        {
            "nodeid": "tests/test_auth.py::test_empty_token",
            "outcome": "failed",
            "call": {
                "crash": {
                    "path": "tests/test_auth.py",
                    "lineno": 45,
                    "message": "AssertionError: Expected 401, got 200"
                },
                "longrepr": "def test_empty_token():\n    res = auth.validate('')\n>   assert res.status_code == 401\nE   assert 200 == 401"
            }
        },
        {
            "nodeid": "tests/test_auth.py::test_missing_header",
            "outcome": "failed",
            "call": {
                "crash": {
                    "path": "tests/test_auth.py",
                    "lineno": 50,
                    "message": "KeyError: 'Authorization'"
                },
                "longrepr": "def test_missing_header():\n    res = auth.validate_headers({})\n>   token = res['Authorization']\nE   KeyError: 'Authorization'"
            }
        }
    ]
}

with open("/tmp/mock_pytest_run/.report.json", "w") as f:
    json.dump(mock_json, f)

print("=== MOCK REPORT GENERATED ===")
analyzer = PytestAnalyzer("/tmp/mock_pytest_run")
payload = analyzer.analyze("raw text fallback here")

print("\n=== EXTRACTED PAYLOAD MARKDOWN FOR CRITIC ===\n")
print(payload.to_markdown())

# Cleanup
os.remove("/tmp/mock_pytest_run/.report.json")
