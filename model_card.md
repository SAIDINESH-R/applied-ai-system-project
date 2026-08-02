# PawPal+ Agent — Model Card

Covers `pawpal_agent.py` (`PawPalAgent`, `GuardrailChecker`) — the Claude-powered layer on top of `pawpal_system.py`'s deterministic scheduling logic. For raw request/response traces, see `ai_interactions.md`; for the automated scenario suite, see `test_harness.py`.

---

## System Limitations and Biases

- **`Task.time` doesn't drive actual scheduling.** `Scheduler.generate_plan()` uses `Task.time` only as a sort key; real slot assignment walks sequentially from `owner.day_start_hour`. An agent can (and did) report a task as scheduled at its requested time when it was actually placed elsewhere. Full writeup: `ai_interactions.md` → "Known Limitation: Task time not honored in scheduling".
- **Greedy, priority-first scheduling.** `generate_plan()` fills the day by priority → time → duration and simply skips tasks that don't fit — it never repacks or partially reorders to fit more in. Low-priority tasks are the first to silently drop on an overbooked day.
- **No cross-pet fairness.** Tasks are pooled and sorted globally, so a pet with several high-priority tasks can crowd out every task for another pet with no signal to the owner beyond the "skipped" list in `explain()`.
- **Guardrail coverage is narrow by design.** `GuardrailChecker.validate_input()` only checks `duration_minutes` (non-negative) and `time` (HH:MM format) — it does not validate `pet_name` existence (handled separately, informally, in `_execute_tool`'s `_find_pet` lookup), `category`/`priority` enum values, or duplicate task names.
- **Single-tenant assumption.** `PawPalAgent` holds one `Owner`/`Scheduler` pair per instance with no per-user isolation — not designed for multi-user or concurrent-session use as-is.

---

## Future Improvements

- **Make `Task.time` actually drive slot placement in `generate_plan()`.** Currently `time` only breaks sort-order ties; the greedy slot walk starting at `owner.day_start_hour` ignores it entirely (see "`Task.time` doesn't drive actual scheduling" above). The fix would place each task at its requested time when possible, falling back to the next open slot only on a real conflict.
- **Add an upper bound check on `duration_minutes` in `GuardrailChecker.validate_input()`.** It currently rejects negative values only; a 100,000-minute task is accepted as-is (see Potential Misuse and Safeguards below).
- **Add a confirmation / human-in-the-loop step before `remove_task` executes.** This is the most significant safeguard gap: `remove_task` is irreversible and currently runs the moment the LLM calls it, with no `always_ask`-style pause for user approval.
- **Validate `pet_name`, `category`, and `priority` in `GuardrailChecker`, not just downstream.** `pet_name` existence is currently checked informally in `_execute_tool`'s `_find_pet` lookup (returning an error string rather than crashing), and `category`/`priority` aren't validated against expected values at all before reaching `Task`/`Priority[...]` construction — moving these into `validate_input` would centralize input validation in one place instead of splitting it across the guardrail and the dispatcher.

---

## Potential Misuse and Safeguards

| Risk | Safeguard | Gap |
|---|---|---|
| Agent adds a task with a nonsensical duration (negative, absurdly large) via a malformed or adversarial request | `validate_input` rejects negative `duration_minutes` before the tool runs | No upper bound check — a 100,000-minute task is accepted |
| Agent adds a task with a garbled time string | `validate_input` rejects anything not matching `HH:MM` (`TIME_RE`) | Doesn't check that the hour/minute are semantically sane beyond the regex range (`00`–`23` / `00`–`59` is enforced, so this is actually covered) |
| Silent overbooking or scheduling conflicts reach the user unflagged | `validate_output` runs `is_overbooked()` and `conflicts()` after every `generate_plan` call and logs warnings to `self.trace` | Warnings are logged, not enforced — nothing stops the agent from proceeding or hides the conflicting plan from the user |
| Agent loops indefinitely on a confusing request, burning API calls | `run(..., max_iterations=8)` caps the tool-call loop and returns a fallback string | No cap on *cost* per iteration (e.g. `max_tokens=2048` per call is fixed, not scaled to task complexity) |
| Destructive action (`remove_task`) executed without confirmation | None — `remove_task` runs immediately once dispatched, same as any other tool | This is the most significant real gap: there's no human-in-the-loop gate before an irreversible action, unlike the `always_ask` permission-policy pattern available in richer agent frameworks |
| Agent invents a pet name that doesn't exist | `_find_pet` returns `None` and `_execute_tool` returns an error string instead of crashing | Relies on the LLM to read and react to the error string; nothing guarantees it retries sensibly |

---

## Testing Surprises

The `malformed_time` scenario in `test_harness.py` initially failed — not because of a bug, but because **Claude Sonnet 5 pre-filters obviously invalid input before ever calling a tool.** Given a request for a task at `25:99`, the model recognized the time as invalid and refused (or corrected) it in conversation, so `add_task` was never called with the bad value — meaning `GuardrailChecker.validate_input`'s `TIME_RE` check never actually executed.

This looked like a broken guardrail on first glance, until the distinction became clear: **"the system behaved safely" and "my specific code path ran" are not the same claim.** Both are legitimate ways to catch bad input — one at the model layer, one at the code layer — but only a test that exercises the guardrail *directly* can confirm the code-level logic is correct independent of whether the LLM happens to filter for it in a given run.

`guardrail_direct_test` was added specifically to close that gap: it instantiates `GuardrailChecker` directly and calls `validate_input('add_task', {'duration_minutes': -15, 'time': '25:99'})` with no `PawPalAgent`, no `run()`, and no API call at all. It confirmed the rejection logic itself is correct. The practical lesson: testing an agent's safety layer requires two kinds of tests — end-to-end scenarios that ask "did anything unsafe happen," and direct unit-style tests that ask "does my validation code actually work," because a passing end-to-end test can mean the model saved you, not your code.

---

## AI Collaboration Reflection

**One helpful suggestion:** Structuring `TOOLS` as plain JSON-schema-style dicts (`name`/`description`/`parameters`) decoupled from the Anthropic SDK's exact `input_schema` wire format, then mapping between them only at the `client.messages.create()` call site in `run()`. This kept `TOOLS` readable and testable on its own, and meant a future SDK or provider change would touch one small mapping instead of every tool definition.

**One flawed suggestion:** The original `negative_duration` scenario's `expected_check` assumed the guardrail's `REJECTED:` trace entry would always appear — i.e., it assumed the LLM would always attempt the tool call and let the code-level guardrail be the one to catch the bad input. That assumption didn't hold in practice (see Testing Surprises above) and had to be loosened to accept either the guardrail or the model catching the issue. It's a good example of an AI-authored test assertion being too confident about *which layer* of a multi-layer safety design would actually fire, rather than testing the outcome that mattered.
