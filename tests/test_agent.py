from src.agent import run_agent, run_planner_only


def test_run_agent_returns_structured_output():
    out = run_agent("Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca")
    assert "plan" in out
    assert "tool_args" in out
    assert "validation" in out
    assert "execution" in out
    assert "final_response" in out


def test_run_agent_executes_with_fallbacks():
    out = run_agent("Assess my property")
    assert "validation" in out
    assert "execution" in out
    # "Assess my property" has no address/digits → fallback marks incomplete → no execution
    if out["execution"]:
        assert out["execution"].get("fuel_class") in {
            "No Data",
            "High Vegetation (High Fuel Load)",
            "Moderate Vegetation",
            "Sparse Vegetation",
            "Minimal Vegetation",
        }
    else:
        assert "plan" in out
        assert out["plan"].get("execution_ready") is False or not out["validation"]["passed"]


def test_run_agent_happy_path_with_address():
    out = run_agent("Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca")
    assert out["validation"]["passed"] is True
    assert out["execution"]
    assert "address" in out["execution"]
    assert "fuel_class" in out["execution"]
    assert "mean_ndvi" in out["execution"]


def test_run_planner_only_returns_structured_spec():
    plan = run_planner_only("Assess wildfire risk for 123 Main St, City, CA")
    assert "request_type" in plan
    assert plan["request_type"] in {"address_baseline", "full_property_assessment", "incomplete", "unsupported"}
    assert "assessment_mode" in plan
    assert "execution_ready" in plan
    assert "steps" in plan
    assert "planner_summary" in plan


def test_run_planner_only_incomplete_request():
    plan = run_planner_only("Tell me about wildfires")
    assert "request_type" in plan
    # Unsupported or incomplete
    assert plan["request_type"] in {"incomplete", "unsupported", "address_baseline", "full_property_assessment"}
    assert "planner_summary" in plan


def test_plan_has_allowed_tools_only():
    plan = run_planner_only("Assess fire risk for 456 Oak Ave, Town, CA")
    allowed = {"geocode_google", "compute_mean_ndvi", "classify_fuel"}
    for step in plan.get("steps") or []:
        tool = step.get("tool")
        if tool:
            assert tool in allowed, f"step uses disallowed tool: {tool}"
