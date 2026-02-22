from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
