from __future__ import annotations

from app.agents import llm_review, security_scan, static_analysis, style_check, test_impact
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
    assert style_findings == [
        {
            "agent_name": "style_agent",
            "severity": "low",
            "category": "maintainability",
            "file_path": "app/demo.py",
            "line_number": 3,
            "title": "TODO/FIXME left in code",
            "description": "Unresolved TODO or FIXME comment may indicate incomplete work.",
            "evidence": "# TODO tighten auth",
            "suggestion": "Address the item or convert it to a tracked ticket.",
            "confidence": 0.60,
        }
    ]


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
    assert by_file["README.md"]["suggested_test_types"] == ["unit"]
