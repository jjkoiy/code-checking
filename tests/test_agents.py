from __future__ import annotations

import json

from app.agents import (
    finding_aggregator,
    evidence_extractor,
    llm_review,
    rag_risk_review,
    report,
    security_scan,
    static_analysis,
    style_check,
    test_generation,
    test_impact,
)
from app.agents.diff_utils import iter_added_lines


def test_diff_utils_maps_added_lines_to_new_file_lines(risky_python_diff: str) -> None:
    added = list(iter_added_lines(risky_python_diff))

    assert added[0] == (
        "app/demo.py",
        2,
        "    query = f\"SELECT * FROM users WHERE name = '{user}'\"",
    )
    assert added[-1] == ("app/demo.py", 6, "    except Exception:")


def test_static_security_and_style_findings_include_file_and_line(risky_python_diff: str) -> None:
    changed_files = [{"file_path": "app/demo.py", "language": "python"}]

    static_findings = static_analysis.analyze(risky_python_diff, changed_files)
    security_findings = security_scan.scan(risky_python_diff, changed_files)
    style_findings = style_check.check(changed_files, risky_python_diff)

    assert any(
        finding["title"] == "SQL string concatenation / interpolation"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 2
        for finding in static_findings
    )
    assert any(
        finding["title"] == "Potential SQL injection via f-string"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 2
        for finding in security_findings
    )
    assert style_findings[0]["severity"] == "medium"
    assert style_findings[0]["category"] == "security"
    assert style_findings[0]["line_number"] == 3
    assert style_findings[0]["title"] == "Auth/security TODO left in code"
    assert style_findings[0]["evidence"] == "    # TODO tighten auth"


def test_static_security_and_style_scan_changed_file_content_without_diff() -> None:
    changed_files = [
        {
            "file_path": "app/demo.py",
            "language": "python",
            "content": "\n".join([
                "def handler(user):",
                "    # TODO tighten auth",
                "    query = f\"SELECT * FROM users WHERE name = '{user}'\"",
                "    return query",
            ]),
        }
    ]

    static_findings = static_analysis.analyze("", changed_files)
    security_findings = security_scan.scan("", changed_files)
    style_findings = style_check.check(changed_files, "")

    assert any(
        finding["title"] == "SQL string concatenation / interpolation"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 3
        for finding in static_findings
    )
    assert any(
        finding["title"] == "Potential SQL injection via f-string"
        and finding["file_path"] == "app/demo.py"
        and finding["line_number"] == 3
        for finding in security_findings
    )
    assert any(
        finding["title"] == "Auth/security TODO left in code"
        and finding["line_number"] == 2
        for finding in style_findings
    )


def test_static_analysis_ast_ignores_exception_text_in_comments() -> None:
    changed_files = [{
        "file_path": "app/demo.py",
        "language": "python",
        "content": "\n".join([
            "def handler():",
            "    # except Exception: this is documentation",
            "    return 1",
        ]),
    }]

    findings = static_analysis.analyze("", changed_files)

    assert not any(finding["title"] == "Broad exception caught" for finding in findings)


def test_static_analysis_ast_allows_open_context_manager() -> None:
    changed_files = [{
        "file_path": "app/demo.py",
        "language": "python",
        "content": "\n".join([
            "def read_file(path):",
            "    with open(path) as handle:",
            "        return handle.read()",
        ]),
    }]

    findings = static_analysis.analyze("", changed_files)

    assert not any(finding["title"] == "Open without context manager" for finding in findings)


def test_static_analysis_ast_keeps_diff_snippet_fallback() -> None:
    diff_text = """diff --git a/app/demo.py b/app/demo.py
--- a/app/demo.py
+++ b/app/demo.py
@@ -1 +1,2 @@
+    # except Exception in a comment should stay quiet once full files are used
+    except Exception:
"""

    findings = static_analysis.analyze(diff_text, [{"file_path": "app/demo.py", "language": "python"}])

    assert any(finding["title"] == "Broad exception caught" for finding in findings)


def test_llm_review_uses_local_mock_when_provider_is_mock(monkeypatch, risky_python_diff: str) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")

    findings = llm_review.review(
        diff_text=risky_python_diff,
        changed_files=[{"file_path": "app/auth.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert findings
    assert any(finding["agent_name"] == "llm_review_agent" for finding in findings)
    assert all(finding["file_path"] for finding in findings)
    assert all(finding["line_number"] is not None for finding in findings)
    assert all(finding["evidence"] for finding in findings)


def test_llm_review_uses_mock_when_external_llm_is_disabled(monkeypatch, risky_python_diff: str) -> None:
    def fail_call_llm(*args, **kwargs):
        raise AssertionError("call_llm should not be called when external LLM is disabled")

    monkeypatch.setattr(llm_review.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_review.settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_review.settings, "llm_external_enabled", False)
    monkeypatch.setattr(llm_review, "call_llm", fail_call_llm)

    findings = llm_review.review(
        diff_text=risky_python_diff,
        changed_files=[{"file_path": "app/auth.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert findings
    assert all(finding["agent_name"] == "llm_review_agent" for finding in findings)


def test_test_generation_skips_call_llm_when_external_llm_is_disabled(monkeypatch) -> None:
    def fail_call_llm(*args, **kwargs):
        raise AssertionError("call_llm should not be called when external LLM is disabled")

    monkeypatch.setattr(test_generation.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(test_generation.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(test_generation.settings, "llm_external_enabled", False)
    monkeypatch.setattr(test_generation, "call_llm", fail_call_llm)

    result = test_generation.generate(
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[],
        llm_findings=[],
        test_impact={
            "new_tests_needed": [{
                "file_path": "app/demo.py",
                "suggested_test_types": ["unit"],
                "reason": "Changed behavior needs regression coverage.",
            }],
        },
    )

    assert result["generated_tests"]
    assert result["generated_tests"][0]["executed"] is False
    assert "pytest.skip" not in result["generated_tests"][0]["code"]
    assert "Assertion direction:" in result["generated_tests"][0]["code"]


def test_test_generation_creates_draft_for_each_high_risk_finding(monkeypatch) -> None:
    monkeypatch.setattr(test_generation.settings, "llm_provider", "mock")
    monkeypatch.setattr(test_generation.settings, "llm_api_key", "")

    result = test_generation.generate(
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[
            {
                "id": "finding-1",
                "agent_name": "security_agent",
                "severity": "critical",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 3,
                "title": "Potential command injection",
                "description": "shell=True is dangerous.",
                "confidence": 0.9,
            },
            {
                "id": "finding-2",
                "agent_name": "static_analysis_agent",
                "severity": "high",
                "category": "bug",
                "file_path": "app/demo.py",
                "line_number": 4,
                "title": "High-risk regression",
                "description": "Important behavior changed.",
                "confidence": 0.8,
            },
        ],
        llm_findings=[],
        test_impact={},
    )

    finding_drafts = [
        test for test in result["generated_tests"]
        if test.get("source_finding_id") in {"finding-1", "finding-2"}
    ]
    assert len(finding_drafts) == 2
    assert all(test["generation_status"] == "draft" for test in finding_drafts)
    assert all("pytest.skip" not in test["code"] for test in finding_drafts)


def test_test_generation_uses_finding_specific_strategies(monkeypatch) -> None:
    monkeypatch.setattr(test_generation.settings, "llm_provider", "mock")
    monkeypatch.setattr(test_generation.settings, "llm_api_key", "")

    result = test_generation.generate(
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[
            {
                "id": "sql-1",
                "agent_name": "security_agent",
                "severity": "critical",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 3,
                "title": "Potential SQL injection via f-string",
                "description": "SQL query uses interpolation.",
                "suggestion": "Use parameterized queries.",
                "rule_family": "sql-injection",
                "confidence": 0.9,
            },
            {
                "id": "except-1",
                "agent_name": "static_analysis_agent",
                "severity": "medium",
                "category": "bug",
                "file_path": "app/demo.py",
                "line_number": 8,
                "title": "Overly broad exception catch with empty handling",
                "description": "Exception is swallowed.",
                "rule_family": "exception-handling",
                "confidence": 0.8,
            },
            {
                "id": "auth-1",
                "agent_name": "style_agent",
                "severity": "medium",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 10,
                "title": "Auth/security TODO left in code",
                "description": "TODO tighten auth.",
                "rule_family": "auth-todo",
                "confidence": 0.7,
            },
        ],
        llm_findings=[],
        test_impact={},
    )

    suggestions = "\n".join(
        item["risk_covered"] + "\n" + item["assertion_direction"]
        for item in result["test_plan"]
    )
    drafts = "\n".join(item["code"] for item in result["generated_tests"])
    assert "SQL injection payload" in suggestions or "payload" in suggestions
    assert "bound parameters" in suggestions
    assert "not silently swallowed" in suggestions
    assert "unauthenticated" in suggestions
    assert "insufficient-permission" in suggestions
    assert "pytest.skip" not in drafts


def test_llm_review_redacts_sensitive_values_before_external_call(monkeypatch) -> None:
    captured = {}

    def fake_call_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"parsed_json": {"findings": []}, "content": "{}", "usage": {}}

    monkeypatch.setattr(llm_review.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_review.settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_review.settings, "llm_external_enabled", True)
    monkeypatch.setattr(llm_review.settings, "llm_redaction_enabled", True)
    monkeypatch.setattr(llm_review, "call_llm", fake_call_llm)

    llm_review.review(
        diff_text="""diff --git a/app/demo.py b/app/demo.py
--- a/app/demo.py
+++ b/app/demo.py
@@ -1 +1,3 @@
+API_KEY = "fake-secret-value"
+password = "hunter2"
+def login(user): return user
""",
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"]},
    )

    assert "fake-secret-value" not in captured["user_prompt"]
    assert "hunter2" not in captured["user_prompt"]
    assert "[REDACTED_SECRET]" in captured["user_prompt"]


def test_llm_review_includes_compact_rag_context_for_external_call(monkeypatch) -> None:
    captured = {}

    def fake_call_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"parsed_json": {"findings": []}, "content": "{}", "usage": {}}

    monkeypatch.setattr(llm_review.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_review.settings, "llm_model", "deepseek-chat")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_review.settings, "llm_external_enabled", True)
    monkeypatch.setattr(llm_review.settings, "llm_redaction_enabled", False)
    monkeypatch.setattr(llm_review, "call_llm", fake_call_llm)

    llm_review.review(
        diff_text="""diff --git a/app/demo.py b/app/demo.py
--- a/app/demo.py
+++ b/app/demo.py
@@ -1 +1,2 @@
+def handler(request):
+    return request.args.get("name")
""",
        changed_files=[{"file_path": "app/demo.py", "language": "python"}],
        aggregated_findings=[],
        project_context={
            "relevant_rules": [{
                "id": "rule-1",
                "content": "Routes should delegate business logic to services.",
                "metadata": {"category": "architecture", "ignored": "drop-me"},
                "score": 0.8,
            }],
            "relevant_project_context": [{
                "id": "ctx-1",
                "content": "def existing_handler(): pass",
                "metadata": {
                    "repo_name": "owner/repo",
                    "file_path": "app/existing.py",
                    "content_hash": "abc123",
                },
            }],
            "relevant_test_examples": [{
                "id": "test-1",
                "content": "Use TestClient for route coverage.",
                "metadata": {"framework": "pytest"},
            }],
        },
    )

    prompt = json.loads(captured["user_prompt"])

    assert prompt["rag_context"]["relevant_rules"][0]["content"] == (
        "Routes should delegate business logic to services."
    )
    assert prompt["rag_context"]["relevant_rules"][0]["metadata"] == {
        "category": "architecture"
    }
    assert prompt["rag_context"]["relevant_project_context"][0]["metadata"] == {
        "repo_name": "owner/repo",
        "file_path": "app/existing.py",
        "content_hash": "abc123",
    }
    assert prompt["rag_context"]["relevant_test_examples"][0]["metadata"] == {
        "framework": "pytest"
    }


def test_plain_text_input_does_not_trigger_mock_llm_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")

    findings = llm_review.review(
        diff_text="please review this api input json and login idea",
        changed_files=[],
        aggregated_findings=[],
        project_context={"languages": [], "risk_hints": ["api", "input", "login"]},
    )

    assert findings == []


def test_mock_llm_does_not_emit_generic_keyword_review_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")
    diff_text = """diff --git a/app/routes.py b/app/routes.py
index 1111111..2222222 100644
--- a/app/routes.py
+++ b/app/routes.py
@@ -1 +1,4 @@
+def get_user_response(user_id):
+    response = {"user_id": user_id, "status_code": 200}
+    return response
"""

    findings = llm_review.review(
        diff_text=diff_text,
        changed_files=[{"file_path": "app/routes.py", "language": "python"}],
        aggregated_findings=[],
        project_context={"languages": ["python"]},
    )

    assert findings == []


def test_non_code_diff_does_not_trigger_code_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")
    docs_diff = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,1 +1,4 @@
 Project notes
+TODO: describe api input json
+password = "not-a-real-secret"
+login flow explanation
"""
    changed_files = [{"file_path": "README.md", "language": "markdown"}]

    assert static_analysis.analyze(docs_diff, changed_files) == []
    assert security_scan.scan(docs_diff, changed_files) == []
    assert style_check.check(changed_files, docs_diff) == []
    assert llm_review.review(docs_diff, changed_files, [], {"languages": ["markdown"]}) == []


def test_raw_code_snippet_with_file_heading_triggers_findings(monkeypatch) -> None:
    monkeypatch.setattr(llm_review.settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_review.settings, "llm_api_key", "")
    raw_code = """# app/demo.py

def handler(user):
    query = f"SELECT * FROM users WHERE name = '{user}'"
    # TODO tighten auth

    try:
        execute_sql(query)
    except Exception:
        pass
"""
    changed_files: list[dict] = []

    static_findings = static_analysis.analyze(raw_code, changed_files)
    security_findings = security_scan.scan(raw_code, changed_files)
    style_findings = style_check.check(changed_files, raw_code)
    llm_findings = llm_review.review(
        raw_code,
        changed_files,
        [],
        {"languages": ["python"], "risk_hints": ["auth"]},
    )

    assert any(finding["title"] == "SQL string concatenation / interpolation" for finding in static_findings)
    assert any(finding["title"] == "Potential SQL injection via f-string" for finding in security_findings)
    assert any(finding["title"] == "Auth/security TODO left in code" for finding in style_findings)
    assert llm_findings


def test_test_impact_keeps_per_file_suggested_types_independent(monkeypatch) -> None:
    monkeypatch.setattr(test_impact, "vector_search", lambda *args, **kwargs: {"documents": []})

    result = test_impact.analyze(
        changed_files=[
            {"file_path": "app/routers/reviews.py", "language": "python"},
            {"file_path": "README.md", "language": "markdown"},
        ],
        diff_text="diff --git a/README.md b/README.md\n+Documentation only\n",
    )

    by_file = {item["file_path"]: item for item in result["new_tests_needed"]}
    assert by_file["app/routers/reviews.py"]["suggested_test_types"] == ["integration", "unit"]
    assert "README.md" not in by_file


def test_test_impact_skips_non_code_files(monkeypatch) -> None:
    monkeypatch.setattr(test_impact, "vector_search", lambda *args, **kwargs: {"documents": []})

    result = test_impact.analyze(
        changed_files=[{"file_path": "README.md", "language": "markdown"}],
        diff_text="diff --git a/README.md b/README.md\n+Document the api login flow\n",
    )

    assert result["recommended_test_types"] == []
    assert result["new_tests_needed"] == []
    assert result["existing_tests_to_run"] == []


def test_security_scan_does_not_flag_subprocess_without_shell_true() -> None:
    raw_code = """# app/demo.py

import subprocess

def list_path(path):
    return subprocess.run(["ls", path], check=False)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert not any(finding["title"] == "Potential command injection" for finding in findings)


def test_security_scan_flags_subprocess_shell_true() -> None:
    raw_code = """# app/demo.py

import subprocess

def run_command(command):
    return subprocess.run(command, shell=True)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert any(finding["title"] == "Potential command injection" for finding in findings)


def test_security_scan_allows_yaml_safe_load() -> None:
    raw_code = """# app/demo.py

import yaml

def load_config(raw):
    return yaml.safe_load(raw)
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/demo.py", "language": "python"}],
    )

    assert not any(finding["title"] == "Insecure deserialization" for finding in findings)


def test_security_scan_does_not_treat_non_sql_query_f_string_as_sql_injection() -> None:
    raw_code = """# app/client.py

def search_url(term):
    query = f"https://example.com/search?q={term}"
    return query
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/client.py", "language": "python"}],
    )

    assert not any(
        finding["title"] in {
            "Potential SQL injection via f-string",
            "Variable named query/sql assigned to f-string",
        }
        for finding in findings
    )


def test_security_scan_skips_placeholder_secrets() -> None:
    raw_code = """# app/settings.py

API_KEY = "test-token"
SECRET = "change-me"
"""

    findings = security_scan.scan(
        raw_code,
        [{"file_path": "app/settings.py", "language": "python"}],
    )

    assert not any(finding["title"] == "Hardcoded secret or credential" for finding in findings)


def test_rag_risk_review_flags_admin_request_param(monkeypatch) -> None:
    risk_card = {
        "risk_id": "weak-auth-request-param",
        "title": "Admin privilege is controlled by request data",
        "severity": "high",
        "category": "security",
        "source_patterns": ["request.args", "request.json"],
        "sink_patterns": ["admin", "debug_token"],
        "evidence_requirements": "Show that admin privilege comes from request data.",
        "suggestion": "Use authenticated server-side role checks instead of request parameters.",
        "attack_scenario": "A user can send admin=true to reach privileged behavior.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "weak-auth",
                "content": __import__("json").dumps(risk_card),
                "metadata": {},
            }]
        },
    )
    diff_text = """diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1 +1,5 @@
+def admin_panel(request):
+    admin = request.args.get("admin") == "true"
+    if admin:
+        return {"debug_token": "secret"}
+    return {}
"""

    findings = rag_risk_review.review(
        diff_text,
        [{"file_path": "app/auth.py", "language": "python"}],
    )

    assert len(findings) == 1
    assert findings[0]["agent_name"] == "rag_risk_review_agent"
    assert findings[0]["rule_family"] == "weak-auth-request-param"
    assert findings[0]["severity"] == "high"
    assert findings[0]["file_path"] == "app/auth.py"
    assert "request.args" in findings[0]["evidence"]
    assert "debug_token" in findings[0]["evidence"]


def test_rag_risk_review_does_not_report_without_required_sink(monkeypatch) -> None:
    risk_card = {
        "risk_id": "client-controlled-payment-amount",
        "title": "Payment amount is trusted from client input",
        "severity": "critical",
        "category": "security",
        "source_patterns": ["request.json", "amount"],
        "sink_patterns": ["charge(", "pay("],
        "suggestion": "Load the amount from the server-side order record.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "payment",
                "content": __import__("json").dumps(risk_card),
                "metadata": {},
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/payments.py",
            "language": "python",
            "content": "def preview(request):\n    amount = request.json['amount']\n    return {'amount': amount}\n",
        }],
    )

    assert findings == []


def test_rag_risk_review_skips_path_traversal_when_safe_join_is_used(monkeypatch) -> None:
    risk_card = {
        "risk_id": "path-traversal",
        "title": "Request-controlled filename reaches file access",
        "severity": "high",
        "category": "security",
        "source_patterns": ["request.args", "filename"],
        "sink_patterns": ["open("],
        "suggestion": "Use safe path joining and boundary checks.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "path",
                "content": __import__("json").dumps(risk_card),
                "metadata": {},
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/download.py",
            "language": "python",
            "content": "\n".join([
                "def download(request):",
                "    filename = request.args.get('filename')",
                "    path = safe_join('/srv/files', filename)",
                "    return open(path).read()",
            ]),
        }],
    )

    assert findings == []


def test_rag_risk_review_uses_sanitizer_patterns_to_avoid_false_positive(monkeypatch) -> None:
    risk_card = {
        "risk_id": "path-traversal",
        "title": "Request-controlled filename reaches file access",
        "severity": "high",
        "category": "security",
        "source_patterns": ["request.args", "filename"],
        "sink_patterns": ["open("],
        "sanitizer_patterns": ["sanitize_filename("],
        "suggestion": "Sanitize and resolve paths under an allowed base directory.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "path",
                "content": json.dumps(risk_card),
                "metadata": {},
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/download.py",
            "language": "python",
            "content": "\n".join([
                "def download(request):",
                "    filename = sanitize_filename(request.args.get('filename'))",
                "    return open(filename).read()",
            ]),
        }],
    )

    assert findings == []


def test_rag_risk_review_does_not_let_unrelated_sanitizer_hide_unsafe_flow(monkeypatch) -> None:
    risk_card = {
        "risk_id": "path-traversal",
        "title": "Request-controlled filename reaches file access",
        "severity": "high",
        "category": "security",
        "source_patterns": ["request.args", "filename"],
        "sink_patterns": ["open("],
        "sanitizer_patterns": ["sanitize_filename("],
        "suggestion": "Sanitize and resolve paths under an allowed base directory.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "path",
                "content": json.dumps(risk_card),
                "metadata": {},
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/download.py",
            "language": "python",
            "content": "\n".join([
                "def download(request):",
                "    preview = sanitize_filename('example.txt')",
                "    filename = request.args.get('filename')",
                "    return open(filename).read()",
            ]),
        }],
    )

    assert len(findings) == 1
    assert findings[0]["rule_family"] == "path-traversal"
    assert "request.args" in findings[0]["evidence"]
    assert "open(filename)" in findings[0]["evidence"]


def test_rag_risk_review_attaches_rule_and_context_ids(monkeypatch) -> None:
    risk_card = {
        "risk_id": "weak-auth-request-param",
        "title": "Admin privilege is controlled by request data",
        "severity": "high",
        "category": "security",
        "source_patterns": ["request.args"],
        "sink_patterns": ["admin_panel"],
        "suggestion": "Use the current_user_role helper for server-side role checks.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "weak-auth-rule",
                "content": json.dumps(risk_card),
                "metadata": {},
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/auth.py",
            "language": "python",
            "content": "\n".join([
                "def admin_panel(request):",
                "    admin_panel_enabled = request.args.get('admin') == 'true'",
                "    return current_user_role(request.user) if admin_panel_enabled else None",
            ]),
        }],
        project_context={
            "relevant_project_context": [{
                "id": "ctx-role-helper",
                "content": "def current_user_role(user): return user.role",
                "metadata": {"symbol_name": "current_user_role"},
            }]
        },
    )

    assert findings
    assert findings[0]["rule_id"] == "weak-auth-rule"
    assert findings[0]["rule_family"] == "weak-auth-request-param"
    assert findings[0]["context_ids"] == ["ctx-role-helper"]


def test_rag_golden_payment_amount_source_to_sink(monkeypatch) -> None:
    risk_card = {
        "risk_id": "client-controlled-payment-amount",
        "title": "Payment amount is trusted from client input",
        "severity": "critical",
        "category": "security",
        "source_patterns": ["request.json", "amount"],
        "sink_patterns": ["charge("],
        "suggestion": "Load payable amount from the server-side order record.",
    }
    monkeypatch.setattr(
        rag_risk_review,
        "vector_search",
        lambda collection, query, top_k=8: {
            "documents": [{
                "id": "payment-rule",
                "content": json.dumps(risk_card),
                "metadata": {},
                "score": 0.9,
                "rank": 1,
            }]
        },
    )

    findings = rag_risk_review.review(
        "",
        [{
            "file_path": "app/payments.py",
            "language": "python",
            "content": "\n".join([
                "def checkout(request, order_id):",
                "    amount = request.json['amount']",
                "    return charge(amount, order_id)",
            ]),
        }],
    )
    aggregated = finding_aggregator.aggregate(findings)

    assert findings[0]["rule_id"] == "payment-rule"
    assert findings[0]["rule_family"] == "client-controlled-payment-amount"
    assert aggregated[0]["blocking"] is True


def test_rag_risk_review_uses_configured_top_k(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def fake_vector_search(collection, query, top_k=8):
        captured["top_k"] = top_k
        return {"documents": []}

    monkeypatch.setattr(rag_risk_review.settings, "rag_vector_top_k", 13)
    monkeypatch.setattr(rag_risk_review, "vector_search", fake_vector_search)

    rag_risk_review.review(
        "",
        [{
            "file_path": "app/auth.py",
            "language": "python",
            "content": "def handler(request):\n    return request.args.get('admin')\n",
        }],
    )

    assert captured["top_k"] == 13


def test_report_uses_plain_ok_text_for_empty_review() -> None:
    result = report.generate([], [], {}, {})

    assert "[OK] No issues found in this review." in result["markdown_report"]
    assert result["json_report"]["llm_mode"] == "mock"


def test_report_includes_metadata_and_review_scope() -> None:
    result = report.generate(
        [],
        [],
        {},
        {},
        metadata={
            "agent_count": 10,
            "duration_seconds": 0.12,
            "llm_mode": "mock",
            "pipeline_status": "completed",
            "rag": {
                "retrieval_mode": "hybrid",
                "embedding_provider": "hash",
                "document_count": 3,
                "skipped": False,
                "skip_reasons": [],
            },
        },
        review_scope={
            "file_count": 2,
            "languages": ["python"],
            "mode": "added_lines_only",
            "added_lines": 7,
            "has_reviewable_content": True,
        },
    )

    assert result["json_report"]["metadata"]["agent_count"] == 10
    assert result["json_report"]["metadata"]["rag"]["document_count"] == 3
    assert result["json_report"]["review_scope"]["file_count"] == 2
    assert "## Review Scope" in result["markdown_report"]


def test_report_distinguishes_no_reviewable_content() -> None:
    result = report.generate(
        [],
        [],
        {},
        {},
        review_scope={
            "file_count": 0,
            "languages": [],
            "mode": "added_lines_only",
            "added_lines": 0,
            "has_reviewable_content": False,
        },
    )

    assert "[WARN] No reviewable content was available" in result["markdown_report"]
    assert result["summary"].startswith("Review completed without reviewable content.")
    assert result["json_report"]["merge_recommendation"]["status"] == "caution"
    assert result["json_report"]["merge_recommendation"]["label"] == "No reviewable content"


def test_report_severity_counts_include_blocking_findings() -> None:
    result = report.generate(
        aggregated_findings=[
            {
                "severity": "high",
                "blocking": True,
                "title": "Blocking high",
                "category": "security",
                "confidence": 0.9,
            },
            {
                "severity": "high",
                "blocking": False,
                "title": "Non-blocking high",
                "category": "security",
                "confidence": 0.8,
            },
        ],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert "共发现 2 个问题：2 个高危。其中 1 个为阻塞问题。" in result["summary"]
    assert result["json_report"]["blocking_count"] == 1
    assert result["json_report"]["high_count"] == 2
    assert result["json_report"]["merge_recommendation"]["status"] == "block"
    assert "## Merge Recommendation" in result["markdown_report"]
    assert "## High-Risk Summary" in result["markdown_report"]


def test_report_merge_recommendation_allows_clean_review() -> None:
    result = report.generate(
        aggregated_findings=[],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["merge_recommendation"]["status"] == "pass"


def test_report_merge_recommendation_flags_medium_risk_as_caution() -> None:
    result = report.generate(
        aggregated_findings=[
            {
                "severity": "medium",
                "blocking": False,
                "title": "Regression coverage gap",
                "category": "reliability",
                "confidence": 0.7,
            },
        ],
        llm_findings=[],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["merge_recommendation"]["status"] == "caution"


def test_finding_aggregator_normalizes_and_drops_invalid_findings() -> None:
    warnings: list[dict] = []

    result = finding_aggregator.aggregate(
        [
            {
                "agent_name": "llm_review_agent",
                "severity": "HIGH",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 2,
                "title": "Potential injection",
                "description": "User input reaches a query.",
                "evidence": "query = f'SELECT {user}'",
                "suggestion": "Use parameters.",
                "confidence": "0.9",
            },
            {
                "agent_name": "llm_review_agent",
                "severity": "severe",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 3,
                "title": "Bad severity",
                "description": "This should be dropped.",
                "confidence": 0.9,
            },
            {
                "agent_name": "llm_review_agent",
                "severity": "medium",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 4,
                "description": "Missing title should be dropped.",
                "confidence": 0.8,
            },
        ],
        validation_warnings=warnings,
    )

    assert len(result) == 1
    assert result[0]["severity"] == "high"
    assert result[0]["confidence"] == 0.9
    assert result[0]["blocking"] is True
    assert len(warnings) == 2


def test_finding_aggregator_drops_non_actionable_llm_findings() -> None:
    warnings: list[dict] = []

    result = finding_aggregator.aggregate(
        [
            {
                "agent_name": "llm_review_agent",
                "severity": "medium",
                "category": "compatibility",
                "title": "API surface change needs targeted review",
                "description": "This changed line appears to affect the API contract.",
                "confidence": 0.5,
            }
        ],
        validation_warnings=warnings,
    )

    assert result == []
    assert warnings
    assert "non-actionable" in warnings[0]["error"]


def test_finding_aggregator_merges_same_line_cross_agent_duplicates() -> None:
    result = finding_aggregator.aggregate(
        [
            {
                "agent_name": "static_analysis_agent",
                "severity": "high",
                "category": "bug",
                "file_path": "app/demo.py",
                "line_number": 2,
                "title": "SQL string concatenation / interpolation",
                "description": "SQL query built with f-string interpolation is prone to SQL injection and syntax errors.",
                "evidence": "query = f\"SELECT * FROM users WHERE name = '{user}'\"",
                "suggestion": "Use parameterized queries.",
                "confidence": 0.75,
            },
            {
                "agent_name": "security_agent",
                "severity": "critical",
                "category": "security",
                "file_path": "app/demo.py",
                "line_number": 2,
                "title": "Potential SQL injection via f-string",
                "description": "SQL query built with f-string interpolation allows SQL injection attacks.",
                "evidence": "query = f\"SELECT * FROM users WHERE name = '{user}'\"",
                "suggestion": "Use parameterized queries: SQLAlchemy text() with bindparams, psycopg2 %s placeholders, or an ORM.",
                "confidence": 0.80,
            },
        ],
    )

    assert len(result) == 1
    assert result[0]["title"] == "Potential SQL injection via f-string"
    assert result[0]["category"] == "security"
    assert result[0]["severity"] == "critical"
    assert result[0]["blocking"] is True
    assert result[0]["source_agents"] == ["static_analysis_agent", "security_agent"]


def test_finding_aggregator_keeps_same_title_on_different_lines() -> None:
    result = finding_aggregator.aggregate(
        [
            {
                "agent_name": "style_agent",
                "severity": "low",
                "category": "maintainability",
                "file_path": "app/demo.py",
                "line_number": 2,
                "title": "TODO/FIXME left in code",
                "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
                "evidence": "# TODO first",
                "suggestion": "Address the item or convert it to a tracked ticket.",
                "confidence": 0.60,
            },
            {
                "agent_name": "style_agent",
                "severity": "low",
                "category": "maintainability",
                "file_path": "app/demo.py",
                "line_number": 8,
                "title": "TODO/FIXME left in code",
                "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
                "evidence": "# TODO second",
                "suggestion": "Address the item or convert it to a tracked ticket.",
                "confidence": 0.60,
            },
        ],
    )

    assert len(result) == 2


def test_evidence_extractor_preserves_diff_line_and_context() -> None:
    diff_text = """diff --git a/app/demo.py b/app/demo.py
index 1111111..2222222 100644
--- a/app/demo.py
+++ b/app/demo.py
@@ -1,3 +1,4 @@
 def handler():
+    print("debug")
     return "ok"
"""

    evidence = evidence_extractor.extract_evidence(
        diff_text,
        [{"file_path": "app/demo.py", "language": "python"}],
        "app/demo.py",
        2,
        context_lines=1,
    )

    assert evidence == 'def handler():\n    print("debug")\n    return "ok"'


def test_evidence_extractor_preserves_raw_content_block() -> None:
    changed_files = [{
        "file_path": "app/demo.py",
        "language": "python",
        "content": "def handler():\n    try:\n        risky()\n    except Exception:\n        pass\n",
    }]

    evidence = evidence_extractor.extract_evidence("", changed_files, "app/demo.py", 2, 5)

    assert evidence == "    try:\n        risky()\n    except Exception:\n        pass"


def test_report_consumes_only_final_normalized_findings() -> None:
    result = report.generate(
        aggregated_findings=[],
        llm_findings=[
            {
                "agent_name": "llm_review_agent",
                "severity": "critical",
                "category": "security",
                "title": "Raw LLM finding",
                "description": "This raw output was not normalized.",
                "confidence": 1.0,
            }
        ],
        test_generation_result={},
        validation_result={},
    )

    assert result["json_report"]["total_findings"] == 0
    assert "Raw LLM finding" not in result["markdown_report"]
