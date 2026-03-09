from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# --- Internal execution spec (planner output) ---

@dataclass
class LocationStrategy:
    use_provided_coordinates: bool = False
    needs_geocoding: bool = True


@dataclass
class DateWindow:
    start: str = "2024-06-01"
    end: str = "2024-09-30"


@dataclass
class PlanConstraints:
    buffer_m: int = 120
    cloud_pct: int = 20
    date_window: Optional[DateWindow] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"buffer_m": self.buffer_m, "cloud_pct": self.cloud_pct}
        if self.date_window:
            d["date_window"] = {
                "start": self.date_window.start,
                "end": self.date_window.end,
            }
        return d


@dataclass
class ExecutionStep:
    step_id: int
    objective: str
    tool: Optional[str] = None
    depends_on: List[int] = field(default_factory=list)
    required: bool = True


@dataclass
class ExecutionSpec:
    """Structured internal planner output: machine-readable execution plan."""

    request_type: str  # baseline_free_tier | full_paid_tier | incomplete | unsupported
    assessment_mode: str  # address_level_baseline | property_level_environmental_assessment | incomplete_request | unsupported_request
    domain: str = "wildfire_defensible_space"
    user_goal: str = ""
    execution_ready: bool = True
    missing_requirements: List[str] = field(default_factory=list)
    location_strategy: Optional[Dict[str, Any]] = None
    analysis_modules: List[str] = field(default_factory=list)
    steps: List[ExecutionStep] = field(default_factory=list)
    constraints: Optional[Dict[str, Any]] = None
    recommended_next_action: str = ""
    planner_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_type": self.request_type,
            "assessment_mode": self.assessment_mode,
            "domain": self.domain,
            "user_goal": self.user_goal,
            "execution_ready": self.execution_ready,
            "missing_requirements": self.missing_requirements,
            "location_strategy": self.location_strategy or {},
            "analysis_modules": self.analysis_modules,
            "steps": [
                {
                    "step_id": s.step_id,
                    "objective": s.objective,
                    "tool": s.tool,
                    "depends_on": s.depends_on,
                    "required": s.required,
                }
                for s in self.steps
            ],
            "constraints": self.constraints or {},
            "recommended_next_action": self.recommended_next_action,
            "planner_summary": self.planner_summary,
        }


@dataclass
class ToolResult:
    """Standardized tool output schema used by the Baseline executor."""

    tool_name: str
    success: bool
    data: Dict[str, Any]
    sources: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "data": self.data,
            "sources": self.sources,
            "limitations": self.limitations,
        }


@dataclass
class BaselineSynthesisSections:
    """Sections of the structured Baseline synthesis output."""

    california_scope_validation: str
    fire_hazard_context: str
    terrain_context: str
    regional_vegetation_context: str
    limitations: str


@dataclass
class BaselineSynthesisEvidence:
    """Short fact strings used as evidence for each section."""

    california_scope_validation: List[str] = field(default_factory=list)
    fire_hazard_context: List[str] = field(default_factory=list)
    terrain_context: List[str] = field(default_factory=list)
    regional_vegetation_context: List[str] = field(default_factory=list)


@dataclass
class FinalBaselineReport:
    """
    Structured representation of the synthesized Baseline report.

    This is the primary artifact for Baseline presentation and should match the JSON
    contract expected by the UI.
    """

    report_title: str
    summary: str
    sections: BaselineSynthesisSections
    evidence_used: BaselineSynthesisEvidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_title": self.report_title,
            "summary": self.summary,
            "sections": {
                "california_scope_validation": self.sections.california_scope_validation,
                "fire_hazard_context": self.sections.fire_hazard_context,
                "terrain_context": self.sections.terrain_context,
                "regional_vegetation_context": self.sections.regional_vegetation_context,
                "limitations": self.sections.limitations,
            },
            "evidence_used": {
                "california_scope_validation": self.evidence_used.california_scope_validation,
                "fire_hazard_context": self.evidence_used.fire_hazard_context,
                "terrain_context": self.evidence_used.terrain_context,
                "regional_vegetation_context": self.evidence_used.regional_vegetation_context,
            },
        }


@dataclass
class BaselineToolContext:
    """
    Shared context object passed into Baseline tools.

    Tools may read and update this as the executor runs through the plan.
    """

    address: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    plan: Dict[str, Any]
    execution_spec: ExecutionSpec
    constraints: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[int, ToolResult] = field(default_factory=dict)
    location_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BaselineOrchestratorResult:
    """High-level result object returned by the Baseline executor/orchestrator."""

    status: str
    plan: Dict[str, Any]
    step_outputs: Dict[int, ToolResult]
    final_report: Optional[FinalBaselineReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "plan": self.plan,
            "step_outputs": {str(k): v.to_dict() for k, v in self.step_outputs.items()},
            "final_report": self.final_report.to_dict() if self.final_report else None,
        }


# --- Legacy / shared (kept for compatibility) ---

@dataclass
class PlanStep:
    step_id: str
    objective: str
    tool: Optional[str] = None
    constraints: List[str] = field(default_factory=list)


@dataclass
class Plan:
    domain: str
    user_goal: str
    steps: List[PlanStep]


@dataclass
class ToolArgs:
    address: str
    buffer_m: int = 100
    start: str = "2024-06-01"
    end: str = "2024-09-01"
    cloud_pct: int = 20


@dataclass
class ExecutionResult:
    address: str
    latitude: Optional[float]
    longitude: Optional[float]
    mean_ndvi: Optional[float]
    fuel_class: str
    confidence: str
    evidence: Dict[str, Any]


@dataclass
class ValidationReport:
    passed: bool
    reasons: List[str]


@dataclass
class AgentOutput:
    plan: Dict[str, Any]
    tool_args: Dict[str, Any]
    validation: Dict[str, Any]
    execution: Dict[str, Any]
    final_response: str


def execution_spec_from_dict(d: Dict[str, Any]) -> ExecutionSpec:
    """Build ExecutionSpec from planner JSON (e.g. LLM output). Tolerates missing/extra keys."""
    steps_raw = d.get("steps") or []
    steps = []
    for s in steps_raw:
        if isinstance(s, dict):
            steps.append(
                ExecutionStep(
                    step_id=int(s.get("step_id", 0)),
                    objective=str(s.get("objective", "")),
                    tool=s.get("tool"),
                    depends_on=[int(x) for x in (s.get("depends_on") or [])],
                    required=s.get("required", True),
                )
            )
    loc = d.get("location_strategy")
    if not isinstance(loc, dict):
        loc = {}
    return ExecutionSpec(
        request_type=str(d.get("request_type", "incomplete")),
        assessment_mode=str(d.get("assessment_mode", "incomplete_request")),
        domain=str(d.get("domain", "wildfire_defensible_space")),
        user_goal=str(d.get("user_goal", "")),
        execution_ready=bool(d.get("execution_ready", True)),
        missing_requirements=list(d.get("missing_requirements") or []),
        location_strategy=loc if loc else None,
        analysis_modules=list(d.get("analysis_modules") or []),
        steps=steps,
        constraints=d.get("constraints") if isinstance(d.get("constraints"), dict) else None,
        recommended_next_action=str(d.get("recommended_next_action", "")),
        planner_summary=str(d.get("planner_summary", "")),
    )
