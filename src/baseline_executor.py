from __future__ import annotations

from typing import Any, Dict, List, Optional

from .baseline_tools import TOOL_REGISTRY
from .llm_client import LLMClient
from .schemas import (
    BaselineOrchestratorResult,
    BaselineToolContext,
    ExecutionSpec,
    FinalBaselineReport,
    ToolResult,
    execution_spec_from_dict,
)


def _find_first_tool_result(step_outputs: Dict[int, ToolResult], tool_name: str) -> Optional[ToolResult]:
    for result in step_outputs.values():
        if result.tool_name == tool_name:
            return result
    return None


def execute_baseline_workflow(
    plan: Dict[str, Any],
    *,
    address: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    tool_args: Optional[Dict[str, Any]],
    llm_client: LLMClient,
) -> Dict[str, Any]:
    """
    Executor/orchestrator for the Baseline (Free Tier) workflow.

    Flow:
      planner JSON -> ExecutionSpec -> step execution via TOOL_REGISTRY -> synthesis -> structured result.
    """
    spec: ExecutionSpec = execution_spec_from_dict(plan)

    if spec.request_type != "baseline_free_tier":
        raise ValueError("execute_baseline_workflow called with non-baseline plan")

    if not spec.execution_ready:
        orchestrator_result = BaselineOrchestratorResult(
            status="not_execution_ready",
            plan=plan,
            step_outputs={},
            final_report=None,
        )
        return {
            "status": orchestrator_result.status,
            "plan": orchestrator_result.plan,
            "step_outputs": {},
            "final_report": None,
            "execution_summary": {},
        }

    # Prefer explicit address from tool_args when available, otherwise fall back to run_agent arguments.
    address_from_args = (tool_args or {}).get("address") if isinstance(tool_args, dict) else None
    address_final = (address_from_args or address or "").strip() or None

    ctx = BaselineToolContext(
        address=address_final,
        lat=lat,
        lng=lng,
        plan=plan,
        execution_spec=spec,
        constraints=spec.constraints or {},
    )

    step_outputs: Dict[int, ToolResult] = {}
    ctx.step_outputs = step_outputs
    completed: set[int] = set()

    # Execute steps in step_id order, enforcing dependencies and using the tool registry.
    for step in sorted(spec.steps, key=lambda s: s.step_id):
        if not step.required:
            completed.add(step.step_id)
            continue

        missing_dep = [d for d in step.depends_on if d not in completed]
        if missing_dep:
            raise RuntimeError(f"Plan dependency violation for step {step.step_id}: {missing_dep} not completed")

        tool_name = step.tool
        if not tool_name:
            completed.add(step.step_id)
            continue

        tool_fn = TOOL_REGISTRY.get(tool_name)
        if tool_fn is None:
            raise KeyError(f"No tool registered for name {tool_name!r}")

        if tool_name == "generate_baseline_report":
            result = tool_fn(ctx, llm_client)  # type: ignore[misc]
        else:
            result = tool_fn(ctx)

        step_outputs[step.step_id] = result
        completed.add(step.step_id)

        if not result.success and step.required:
            orchestrator_result = BaselineOrchestratorResult(
                status="failed",
                plan=plan,
                step_outputs=step_outputs,
                final_report=None,
            )
            execution_summary: Dict[str, Any] = {
                "tier": plan.get("request_type"),
                "address": ctx.address,
                "latitude": ctx.lat,
                "longitude": ctx.lng,
                "evidence": {
                    "geocode": ctx.location_metadata.get("geocode") or {},
                },
                "hazard_context": None,
                "terrain_context": None,
                "regional_vegetation_context": None,
                "mean_ndvi": None,
                "fuel_class": None,
            }
            return {
                "status": orchestrator_result.status,
                "plan": orchestrator_result.plan,
                "step_outputs": {str(k): v.to_dict() for k, v in step_outputs.items()},
                "final_report": None,
                "execution_summary": execution_summary,
            }

    # Extract the synthesized Baseline report text from the generate_baseline_report tool output.
    synth_result = _find_first_tool_result(step_outputs, "generate_baseline_report")
    report_text = ""
    if synth_result and isinstance(synth_result.data, dict):
        report_text = str(synth_result.data.get("report_text", "")).strip()

    final_report = FinalBaselineReport(
        tier="baseline_free_tier",
        text=report_text,
        sections={},
    )

    orchestrator_result = BaselineOrchestratorResult(
        status="completed",
        plan=plan,
        step_outputs=step_outputs,
        final_report=final_report,
    )

    hazard_res = _find_first_tool_result(step_outputs, "gather_hazard_context")
    terrain_res = _find_first_tool_result(step_outputs, "gather_terrain_context")
    veg_res = _find_first_tool_result(step_outputs, "gather_regional_vegetation_context")

    execution_summary: Dict[str, Any] = {
        "tier": plan.get("request_type"),
        "address": ctx.address,
        "latitude": ctx.lat,
        "longitude": ctx.lng,
        "evidence": {
            "geocode": ctx.location_metadata.get("geocode") or {},
        },
        "hazard_context": hazard_res.data if hazard_res and hazard_res.success else None,
        "terrain_context": terrain_res.data if terrain_res and terrain_res.success else None,
        "regional_vegetation_context": veg_res.data if veg_res and veg_res.success else None,
        "mean_ndvi": None,
        "fuel_class": None,
    }

    return {
        "status": orchestrator_result.status,
        "plan": orchestrator_result.plan,
        "step_outputs": {str(k): v.to_dict() for k, v in step_outputs.items()},
        "final_report": orchestrator_result.final_report.to_dict(),
        "execution_summary": execution_summary,
    }

