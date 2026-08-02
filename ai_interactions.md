# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

<!-- Describe the goal you asked the agent to accomplish -->

I asked the agent to refactor the Scheduler class to work across multiple pets instead of a single pet. The agent was given access to `pawpal_system.py`, `main.py`, and `tests/test_pawpal.py` simultaneously.

**What did the agent do?**

<!-- List the steps the agent took (files edited, commands run, etc.) -->


- Read `pawpal_system.py` and identified the single-pet limitation
- Removed the `pet` parameter from `Scheduler.__init__`
- Added `_all_tasks()` helper to flatten tasks across all owner's pets
- Updated `generate_plan()`, `explain()`, `conflicts()`, `tasks_by_category()`, and `is_overbooked()` to use `_all_tasks()`
- Rewrote `main.py` to use a single `Scheduler(owner=owner)` with tasks added per pet
- Updated all tests in `test_pawpal.py` to use the new API
- Ran `python main.py` and `pytest` to verify everything passed



**What did you have to verify or fix manually?**

<!-- Describe anything the agent got wrong or that required human review -->

I verified that the output correctly showed tasks from both pets labeled with `[Biscuit]` and `[Whiskers]`. I also confirmed the overbooked warning appeared correctly when total task time exceeded available minutes.

---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | Claude Code (agent mode) | Claude Code (chat mode) |
| **Prompt** | "Refactor Scheduler to work across all pets in the Owner. Remove the pet parameter and use _all_tasks() to flatten tasks across all owner.pets. Update all methods and tests." | "How should I update Scheduler to support multiple pets?" |
| **Response summary** | Directly edited all 3 files, ran tests, and verified output automatically | Explained the approach in text and suggested code snippets to copy manually |
| **What was useful** | Made all changes atomically across multiple files with no manual copy-paste | Good for understanding the concept before implementing |
| **Problems noticed** | Agent occasionally made assumptions about file names (used uml.mmd instead of uml_draft.mmd) | Required manually copying and pasting every suggestion into files |
| **Decision** | Used agent mode for implementation | Used chat mode for planning and understanding |

**Which approach did you use in your final implementation and why?**

<!-- Your conclusion -->

I used agent mode for implementation tasks and chat mode for planning and understanding. Agent mode was faster and more reliable for multi-file changes, while chat mode helped me understand what the agent was doing before accepting its edits.

---

## Known Limitation: Task time not honored in scheduling

**Request given to the agent (via `test_agent.py`):**

```
Add a 30 minute walk for Biscuit at 9am, high priority, category exercise, then generate today's plan and explain it
```

**Final response:**

```
Done! Here's a summary of what I set up:
**Task added:** A 30-minute Walk for Biscuit (HIGH priority, exercise category).
**Today's plan:**
- **08:00** — [Biscuit] Walk (30 min) [HIGH]
**Total scheduled:** 30 min out of 120 available minutes — so you've got plenty of room to spare, with no conflicts.
One thing to note: you requested the walk at **9:00 AM**, but the generated plan scheduled it at **08:00** (the default start time). If you'd like it firmly at 9:00 AM, let me know and I can re-add it with that time locked in.
```

**Trace:**

```
('add_task', {'pet_name': 'Biscuit', 'name': 'Walk', 'duration_minutes': 30, 'priority': 'HIGH', 'category': 'exercise', 'time': '09:00'}, "Added task 'Walk' to Biscuit.")
('generate_plan', {}, '{"plan": ["08:00 Walk"], "warnings": []}')
('explain', {}, "Daily plan for Alex's pets (Biscuit):\n  Available: 120 min\n\n  08:00 — [Biscuit] Walk (30 min) [HIGH]\n\n  Total scheduled: 30 min")
```

**Explanation:**

`Task.time` was correctly stored as `"09:00"` on `add_task`, but `Scheduler.generate_plan()` only uses `Task.time` as a sort key (`pawpal_system.py`, `sorted_tasks` key: `(priority.order, Time.fromisoformat(t.time), duration_minutes)`). Actual slot assignment ignores it entirely — slots are computed by walking sequentially from `owner.day_start_hour`, incrementing by each task's `duration_minutes` in sorted order. As a result, the task was placed at `08:00` instead of the requested `09:00`, even though the agent (correctly, per its trace) had recorded `09:00` as the task's preferred time. The agent noticed and flagged the mismatch in its response, but this is a real gap between `Task.time` (advisory, sort-only) and the plan's actual slots — an LLM agent reporting the plan verbatim would otherwise state a task was scheduled at a time it wasn't.
