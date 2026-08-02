# PawPal+ Agent

## Title and Summary

PawPal+ Agent is a Claude-powered layer on top of PawPal+, a pet-care task scheduler. Instead of only driving the scheduler through a CLI or Streamlit form, `PawPalAgent` lets a user describe what they want in plain English ("add a 30 minute walk for Biscuit at 9am, high priority, then generate today's plan") and has Claude call the existing scheduler's real methods as tools — adding/removing tasks, generating a plan, checking for overbooking or conflicts, and explaining the result — with a guardrail layer validating both the inputs Claude sends and the outputs the scheduler produces along the way.

## Original Project

`pawpal_system.py` is the Module 1–3 base for PawPal+: a deterministic pet-care task scheduler built from four classes — `Owner`, `Pet`, `Task`, and `Scheduler`. Its original goal was to let an owner register pets and care tasks (walks, feeding, meds, grooming), then generate a daily schedule that fits within the owner's available minutes, sorted by priority, preferred time, and duration. `Scheduler` also detects overbooking and time-slot conflicts and produces a human-readable explanation of the generated plan — none of this original logic changed to support the agent; the agent only calls it.

## New AI Feature: Agentic Workflow

`PawPalAgent` (`pawpal_agent.py`) wraps `Scheduler` and `Pet` methods as LLM-callable tools via the Claude API (`claude-sonnet-5`). A user's natural-language request is sent to Claude along with a `TOOLS` list describing `add_task`, `remove_task`, `generate_plan`, `is_overbooked`, `conflicts`, `next_available_slot`, and `explain`; when Claude responds with a tool call, `PawPalAgent` looks up the real `Pet`/`Task` objects and invokes the actual `Scheduler`/`Pet` method — it never lets the model fabricate scheduling results itself. A `GuardrailChecker` validates tool-call arguments before execution (rejecting negative durations and malformed time strings) and validates the scheduler's output after `generate_plan` (flagging overbooking and conflicts), logging everything to `self.trace` for inspection.

## Architecture Overview

See [diagrams/architecture.mmd](diagrams/architecture.mmd) for the full flowchart. At a high level: a user request enters `PawPalAgent.run()`, which sends it to the Claude API; if Claude returns a tool call, the arguments pass through `GuardrailChecker.validate_input()` — on rejection, an error goes straight back to Claude as a tool result, on success the real `Scheduler`/`Pet` method runs. When that method is `generate_plan`, its output additionally passes through `GuardrailChecker.validate_output()` (which checks `is_overbooked()` and `conflicts()` and logs any warnings). Every step — rejections, warnings, and normal results — is appended to the trace, and the tool result is sent back to Claude, looping until Claude returns a final text response with no further tool calls.

## Setup Instructions

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set your Anthropic API key (required for the agent; not needed for pawpal_system.py alone)
export ANTHROPIC_API_KEY="your-api-key-here"  # Windows: set ANTHROPIC_API_KEY=your-api-key-here
```

Running the pieces:

```bash
# Streamlit UI for the original deterministic scheduler
streamlit run app.py

# CLI demo of the deterministic scheduler + JSON persistence
python main.py

# Single scripted request through PawPalAgent (prints final response + trace)
python test_agent.py

# 6-scenario reliability/evaluation harness for PawPalAgent (makes real API calls)
python test_harness.py
```

## Sample Interactions

Real output from `python test_agent.py`, requesting: *"Add a 30 minute walk for Biscuit at 9am, high priority, category exercise, then generate today's plan and explain it"*

```
=== Final response ===
Done! Here's a summary of what I set up:
**Task added:** A 30-minute Walk for Biscuit (HIGH priority, exercise category).
**Today's plan:**
- **08:00** — [Biscuit] Walk (30 min) [HIGH]
**Total scheduled:** 30 min out of 120 available minutes — so you've got plenty of room to spare, with no conflicts.
One thing to note: you requested the walk at **9:00 AM**, but the generated plan scheduled it at **08:00** (the default start time). If you'd like it firmly at 9:00 AM, let me know and I can re-add it with that time locked in.

=== Trace ===
('add_task', {'pet_name': 'Biscuit', 'name': 'Walk', 'duration_minutes': 30, 'priority': 'HIGH', 'category': 'exercise', 'time': '09:00'}, "Added task 'Walk' to Biscuit.")
('generate_plan', {}, '{"plan": ["08:00 Walk"], "warnings": []}')
('explain', {}, "Daily plan for Alex's pets (Biscuit):\n  Available: 120 min\n\n  08:00 — [Biscuit] Walk (30 min) [HIGH]\n\n  Total scheduled: 30 min")
```

Notice the agent itself caught and flagged the `Task.time` limitation (see Known Limitations below) in its own response.

Real output from the `normal_day` scenario in `test_harness.py`, requesting: *"Add a 30 minute walk for Biscuit at 8am, high priority, category exercise. Then generate today's plan."*

```
Done! Here's the update:
1. **Task added**: "Walk" for Biscuit — 30 minutes, 8:00 AM, HIGH priority, exercise category.
2. **Today's plan generated**: The plan currently contains just this one task:
   - **08:00 – Walk** (Biscuit)
No conflicts or warnings were found. Let me know if you'd like to add tasks for other pets or check if the schedule is overbooked.

Trace:
  ('add_task', {'pet_name': 'Biscuit', 'name': 'Walk', 'duration_minutes': 30, 'priority': 'HIGH', 'category': 'exercise', 'time': '08:00'}, "Added task 'Walk' to Biscuit.")
  ('generate_plan', {}, '{"plan": ["08:00 Walk"], "warnings": []}')
```

Real output from the `add_then_remove` scenario in `test_harness.py`, requesting: *"Add a 20 minute grooming session called Groom for Biscuit, medium priority, category grooming. Then immediately remove that task from Biscuit."*

```
Done! I added the 20-minute "Groom" task (medium priority, grooming category) to Biscuit's task list, then immediately removed it as requested. Biscuit's task list is now back to how it was before.

Trace:
  ('add_task', {'pet_name': 'Biscuit', 'name': 'Groom', 'duration_minutes': 20, 'priority': 'MEDIUM', 'category': 'grooming'}, "Added task 'Groom' to Biscuit.")
  ('remove_task', {'task_name': 'Groom', 'pet_name': 'Biscuit'}, "Removed task 'Groom' from Biscuit.")
```

## Reliability/Evaluation Results

`test_harness.py` runs 6 scenarios against a fresh `PawPalAgent` each: a normal day, an overbooked day, a negative-duration request, an add-then-remove request, a malformed-time request, and a direct (no-API-call) unit-style test of `GuardrailChecker.validate_input()`. From a real run:

```
[PASS] normal_day
[PASS] overbooked_day
[PASS] negative_duration
[PASS] add_then_remove
[FAIL] malformed_time
[PASS] guardrail_direct_test

5 out of 6 scenarios passed
```

The one failure, `malformed_time`, was not a bug: Claude Sonnet 5 pre-filters obviously invalid input (like a `25:99` time) before ever calling a tool, so `GuardrailChecker.validate_input`'s time-format check never got exercised through natural conversation. `guardrail_direct_test` independently confirmed the guardrail's rejection logic itself is correct by calling `validate_input()` directly, bypassing the LLM entirely. Full writeup: `model_card.md` → "Testing Surprises".

## Design Decisions

- **Agentic workflow over RAG:** the task is about *taking actions* (adding/removing tasks, generating a plan) against a small, well-defined set of operations — not retrieving or grounding answers in a document corpus, which is what RAG is for. Tool-calling maps naturally onto "call this specific scheduling method with these arguments."
- **Tools map 1:1 to existing `Scheduler` methods:** `add_task`, `remove_task`, `generate_plan`, `is_overbooked`, `conflicts`, `next_available_slot`, and `explain` are exposed exactly as they exist in `pawpal_system.py`, rather than as a new higher-level API. This keeps the scheduling logic itself untouched and trusted — the agent is a thin natural-language front end, not a reimplementation.
- **`GuardrailChecker` is separate from `PawPalAgent`:** validation logic (input rejection, output warnings) is independently testable and reasoned about without needing a live model or a `PawPalAgent` instance at all — see `guardrail_direct_test` in `test_harness.py`, which exercises `GuardrailChecker` with zero API calls.

## Known Limitations

`Task.time` only affects sort order in `generate_plan()`, not actual slot placement — see `ai_interactions.md` → "Known Limitation: Task time not honored in scheduling" and `model_card.md` for the full reflection.

## Reflection

See `model_card.md` for the full reflection, including system limitations, potential misuse and safeguards, testing surprises, and AI collaboration notes.
