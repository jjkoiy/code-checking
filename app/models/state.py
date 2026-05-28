from __future__ import annotations

from typing import TypedDict, List, Dict, Any, Optional


class Finding(TypedDict, total=False):
    id: Optional[str]
    agent_name: str
    severity: str
    category: str
    file_path: Optional[str]
    line_number: Optional[int]
    line_start: Optional[int]
    line_end: Optional[int]
    title: str
    description: str
    evidence: str
    suggestion: str
    confidence: float
    blocking: Optional[bool]
    rule_family: Optional[str]
    rule_id: Optional[str]
    context_ids: List[str]
    certainty: Optional[str]
    attack_scenario: Optional[str]
    source_agents: List[str]


class ReviewState(TypedDict, total=False):
    task_id: str
    status: str
    current_stage: str
    on_stage_start: Any
    on_stage_end: Any
    pipeline_started_at: float

    source_type: str
    repo_path: Optional[str]
    repo_name: Optional[str]
    base_ref: Optional[str]
    head_ref: Optional[str]

    diff_text: str
    changed_files: List[Dict[str, Any]]
    project_context: Dict[str, Any]

    static_findings: List[Finding]
    style_findings: List[Finding]
    security_findings: List[Finding]
    rag_risk_findings: List[Finding]
    test_impact: Dict[str, Any]

    aggregated_findings: List[Finding]
    llm_findings: List[Finding]
    llm_mode: str

    test_generation_result: Dict[str, Any]
    validation_result: Dict[str, Any]
    validation_warnings: List[Dict[str, Any]]

    final_report: Dict[str, Any]

    retry_count: Dict[str, int]
    errors: List[Dict[str, Any]]
