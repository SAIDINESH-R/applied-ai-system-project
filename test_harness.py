"""Scenario harness for PawPalAgent. Makes real Anthropic API calls — run manually.

    python3 test_harness.py
"""

from pawpal_agent import GuardrailChecker, PawPalAgent
from pawpal_system import Owner, Pet, Scheduler


def _setup_normal_day():
    owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _setup_overbooked_day():
    owner = Owner(name="Alex", available_minutes=10, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _setup_negative_duration():
    owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _setup_add_then_remove():
    owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _setup_malformed_time():
    owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _setup_guardrail_direct_test():
    owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
    owner.add_pet(Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0))
    return owner, Scheduler(owner=owner)


def _check_normal_day(response: str, trace: list) -> bool:
    no_warnings = not any(entry[0] == "guardrail_warning" for entry in trace)
    ran_generate_plan = any(entry[0] == "generate_plan" for entry in trace)
    return bool(response) and no_warnings and ran_generate_plan


def _check_overbooked_day(response: str, trace: list) -> bool:
    return any(entry[0] == "guardrail_warning" for entry in trace)


# Claude Sonnet 5 tends to catch an obviously-invalid negative duration itself
# and refuse to call add_task at all, so the guardrail's REJECTED path never
# fires. This scenario passes on EITHER outcome — a REJECTED trace entry (the
# guardrail caught it) or the response text mentioning the invalid duration
# (the LLM caught it) — since either is an acceptable way to catch the issue;
# it exists to observe *which* layer actually caught it, not to enforce one.
def _check_negative_duration(response: str, trace: list) -> bool:
    guardrail_caught = any(
        len(entry) == 3 and isinstance(entry[2], str) and entry[2].startswith("REJECTED:")
        for entry in trace
    )
    llm_caught = bool(response) and (
        "-15" in response or "negative" in response.lower()
    )
    return guardrail_caught or llm_caught


def _check_add_then_remove(response: str, trace: list) -> bool:
    tool_names = [entry[0] for entry in trace]
    return "add_task" in tool_names and "remove_task" in tool_names


def _check_malformed_time(response: str, trace: list) -> bool:
    return any(
        len(entry) == 3 and isinstance(entry[2], str) and entry[2].startswith("REJECTED:")
        for entry in trace
    )


# Bypasses agent.run() and the LLM entirely — calls GuardrailChecker.validate_input()
# directly to prove the rejection logic itself works, independent of whether an
# LLM ever produces a tool call that triggers it. Makes no API calls.
def _run_guardrail_direct_test(owner: Owner, scheduler: Scheduler) -> tuple:
    checker = GuardrailChecker(scheduler)
    args = {"duration_minutes": -15, "time": "25:99"}
    error = checker.validate_input("add_task", args)
    trace = [("add_task", args, f"REJECTED: {error}" if error else "NOT REJECTED")]
    return error, trace


def _check_guardrail_direct_test(response: str, trace: list) -> bool:
    return bool(response) and trace[0][2].startswith("REJECTED:")


SCENARIOS = [
    {
        "name": "normal_day",
        "setup": _setup_normal_day,
        "request": (
            "Add a 30 minute walk for Biscuit at 8am, high priority, category exercise. "
            "Then generate today's plan."
        ),
        "expected_check": _check_normal_day,
    },
    {
        "name": "overbooked_day",
        "setup": _setup_overbooked_day,
        "request": (
            "Add a 30 minute walk for Biscuit at 8am, high priority, category exercise. "
            "Then generate today's plan."
        ),
        "expected_check": _check_overbooked_day,
    },
    {
        "name": "negative_duration",
        "setup": _setup_negative_duration,
        "request": (
            "Add a task called Walk for Biscuit with a duration of -15 minutes, "
            "high priority, category exercise."
        ),
        "expected_check": _check_negative_duration,
    },
    {
        "name": "add_then_remove",
        "setup": _setup_add_then_remove,
        "request": (
            "Add a 20 minute grooming session called Groom for Biscuit, medium priority, "
            "category grooming. Then immediately remove that task from Biscuit."
        ),
        "expected_check": _check_add_then_remove,
    },
    {
        "name": "malformed_time",
        "setup": _setup_malformed_time,
        "request": (
            "Add a 30 minute walk called Walk for Biscuit at 25:99, high priority, "
            "category exercise."
        ),
        "expected_check": _check_malformed_time,
    },
    {
        "name": "guardrail_direct_test",
        "setup": _setup_guardrail_direct_test,
        "direct": _run_guardrail_direct_test,
        "expected_check": _check_guardrail_direct_test,
    },
]


def run_scenarios(scenarios: list) -> list:
    results = []
    for scenario in scenarios:
        owner, scheduler = scenario["setup"]()
        direct_runner = scenario.get("direct")
        try:
            if direct_runner is not None:
                # No agent, no API call — exercises the guardrail in isolation.
                response, trace = direct_runner(owner, scheduler)
            else:
                agent = PawPalAgent(owner=owner, scheduler=scheduler)
                response = agent.run(scenario["request"])
                trace = agent.trace
            passed = scenario["expected_check"](response, trace)
            error = None
        except Exception as exc:  # noqa: BLE001 - surface any failure as a failed scenario
            response = None
            trace = []
            passed = False
            error = repr(exc)

        results.append({
            "name": scenario["name"],
            "passed": passed,
            "response": response,
            "trace": trace,
            "error": error,
        })
    return results


def print_summary(results: list) -> None:
    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['name']}")

    print(f"\n{passed_count} out of {total} scenarios passed")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print("\n=== Failure details ===")
        for result in failures:
            print(f"\n--- {result['name']} ---")
            if result["error"] is not None:
                print(f"Exception: {result['error']}")
            print(f"Response: {result['response']}")
            print("Trace:")
            for entry in result["trace"]:
                print(f"  {entry}")


if __name__ == "__main__":
    results = run_scenarios(SCENARIOS)
    print_summary(results)
