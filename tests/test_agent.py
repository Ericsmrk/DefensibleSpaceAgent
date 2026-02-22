from src.agent import run_agent


def test_run_agent_returns_structured_output():
    out = run_agent("Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca")
    assert "plan" in out
    assert "tool_args" in out
    assert "validation" in out
    assert "execution" in out
    assert "final_response" in out


def test_run_agent_executes_with_fallbacks():
    out = run_agent("Assess my property")
    assert out["validation"]["passed"] is True
    assert out["execution"]["fuel_class"] in {
        "No Data",
        "High Vegetation (High Fuel Load)",
        "Moderate Vegetation",
        "Sparse Vegetation",
        "Minimal Vegetation",
    }
