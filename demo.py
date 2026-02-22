import json

from src.agent import run_agent


EXAMPLES = [
    "Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca",
    "Assess my home at 48978 River Park Rd, Oakhurst, CA and give mitigation actions",
    "Assess 123 Main Street and explain uncertainty if data quality is limited",
]


if __name__ == "__main__":
    for idx, request in enumerate(EXAMPLES, start=1):
        result = run_agent(request)
        print(f"\n=== Example {idx} ===")
        print(f"Request: {request}")
        print(json.dumps(result, indent=2))
