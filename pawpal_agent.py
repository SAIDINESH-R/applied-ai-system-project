from __future__ import annotations

import json
import re
from datetime import date

import anthropic

from pawpal_system import Owner, Pet, Priority, Scheduler, Task

MODEL = "claude-sonnet-5"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Each entry describes one Scheduler/Pet method as a callable tool.
# "parameters" is a JSON-schema-style spec of what an LLM tool-call would
# supply; a wiring layer (not implemented yet) is responsible for looking up
# Pet/Task objects and any current plan before calling the real method.
TOOLS = [
    {
        "name": "add_task",
        "description": "Add a new task to a specific pet's task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "pet_name": {"type": "string", "description": "Name of the pet to add the task to."},
                "name": {"type": "string", "description": "Task name."},
                "duration_minutes": {"type": "integer", "description": "How long the task takes, in minutes."},
                "priority": {
                    "type": "string",
                    "enum": ["HIGH", "MEDIUM", "LOW"],
                    "description": "Task priority.",
                },
                "category": {"type": "string", "description": "Task category, e.g. exercise, nutrition, health."},
                "notes": {"type": "string", "description": "Optional free-text notes.", "default": ""},
                "time": {"type": "string", "description": "Preferred start time, HH:MM.", "default": "08:00"},
                "frequency": {
                    "type": "string",
                    "enum": ["once", "daily", "weekly"],
                    "description": "How often the task recurs.",
                    "default": "once",
                },
                "repeat_day": {
                    "type": "integer",
                    "description": "Weekday index for weekly tasks (0=Mon ... 6=Sun), -1 if not set.",
                    "default": -1,
                },
            },
            "required": ["pet_name", "name", "duration_minutes", "priority", "category"],
        },
    },
    {
        "name": "remove_task",
        "description": "Remove a task by name from a specific pet's task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Name of the task to remove."},
                "pet_name": {"type": "string", "description": "Name of the pet the task belongs to."},
            },
            "required": ["task_name", "pet_name"],
        },
    },
    {
        "name": "generate_plan",
        "description": "Sort due tasks across all pets by priority, time, and duration, and fit them within available minutes.",
        "parameters": {
            "type": "object",
            "properties": {
                "today": {
                    "type": "string",
                    "format": "date",
                    "description": "ISO date to evaluate due tasks against. Defaults to today.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "is_overbooked",
        "description": "Return True if total pending task time across all pets exceeds available minutes.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "conflicts",
        "description": (
            "Return warning strings for any two scheduled tasks whose time slots overlap. "
            "Operates on the most recently generated plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "next_available_slot",
        "description": (
            "Return the next HH:MM slot where a new task fits without overlapping any scheduled task. "
            "Operates on the most recently generated plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "explain",
        "description": "Return a human-readable summary of the combined plan across all pets.",
        "parameters": {
            "type": "object",
            "properties": {
                "today": {
                    "type": "string",
                    "format": "date",
                    "description": "ISO date to evaluate due tasks against. Defaults to today.",
                },
            },
            "required": [],
        },
    },
]


class GuardrailChecker:
    def __init__(self, scheduler: Scheduler):
        self.scheduler = scheduler

    def validate_input(self, tool_name: str, args: dict) -> str | None:
        """Return an error message if args are invalid, else None."""
        duration = args.get("duration_minutes")
        if duration is not None and duration < 0:
            return f"Invalid duration_minutes: {duration} (must be non-negative)."
        time_str = args.get("time")
        if time_str is not None and not TIME_RE.match(time_str):
            return f"Invalid time string: {time_str!r} (expected HH:MM)."
        return None

    def validate_output(self, plan: list[tuple[str, Task]]) -> list[str]:
        """Run post-generate_plan checks and return any warning strings."""
        warnings = []
        if self.scheduler.is_overbooked():
            warnings.append("Owner is overbooked: pending task time exceeds available minutes.")
        warnings.extend(self.scheduler.conflicts(plan))
        return warnings


class PawPalAgent:
    def __init__(self, owner: Owner, scheduler: Scheduler):
        self.owner = owner
        self.scheduler = scheduler
        self.trace: list = []
        self.guardrails = GuardrailChecker(scheduler)
        self._last_plan: list[tuple[str, Task]] = []

    def _find_pet(self, pet_name: str) -> Pet | None:
        return next((p for p in self.owner.pets if p.name == pet_name), None)

    def _execute_tool(self, name: str, args: dict) -> str:
        if name == "add_task":
            pet = self._find_pet(args["pet_name"])
            if pet is None:
                return f"Error: no pet named {args['pet_name']!r}."
            task = Task(
                name=args["name"],
                duration_minutes=args["duration_minutes"],
                priority=Priority[args["priority"]],
                category=args["category"],
                notes=args.get("notes", ""),
                time=args.get("time", "08:00"),
                frequency=args.get("frequency", "once"),
                repeat_day=args.get("repeat_day", -1),
            )
            self.scheduler.add_task(task, pet)
            return f"Added task {task.name!r} to {pet.name}."

        if name == "remove_task":
            pet = self._find_pet(args["pet_name"])
            if pet is None:
                return f"Error: no pet named {args['pet_name']!r}."
            self.scheduler.remove_task(args["task_name"], pet)
            return f"Removed task {args['task_name']!r} from {pet.name}."

        if name == "generate_plan":
            today = date.fromisoformat(args["today"]) if args.get("today") else None
            plan = self.scheduler.generate_plan(today)
            self._last_plan = plan
            warnings = self.guardrails.validate_output(plan)
            for warning in warnings:
                self.trace.append(("guardrail_warning", warning))
            summary = [f"{slot} {task.name}" for slot, task in plan]
            return json.dumps({"plan": summary, "warnings": warnings})

        if name == "is_overbooked":
            return json.dumps({"is_overbooked": self.scheduler.is_overbooked()})

        if name == "conflicts":
            return json.dumps(self.scheduler.conflicts(self._last_plan))

        if name == "next_available_slot":
            return self.scheduler.next_available_slot(self._last_plan)

        if name == "explain":
            today = date.fromisoformat(args["today"]) if args.get("today") else None
            return self.scheduler.explain(today)

        return f"Error: unknown tool {name!r}."

    def run(self, request: str, max_iterations: int = 8) -> str:
        client = anthropic.Anthropic()
        api_tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in TOOLS
        ]
        messages = [{"role": "user", "content": request}]

        for _ in range(max_iterations):
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                tools=api_tools,
                messages=messages,
            )

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks:
                return next((b.text for b in response.content if b.type == "text"), "")

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in tool_use_blocks:
                error = self.guardrails.validate_input(block.name, block.input)
                if error is not None:
                    self.trace.append((block.name, block.input, f"REJECTED: {error}"))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": error,
                        "is_error": True,
                    })
                    continue

                result = self._execute_tool(block.name, block.input)
                self.trace.append((block.name, block.input, result))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        message = f"Stopped after {max_iterations} iterations"
        self.trace.append(("max_iterations_reached", {}, message))
        return (
            f"I wasn't able to finish within {max_iterations} tool-call rounds, "
            "so I stopped without a final answer. Try a narrower request or a higher max_iterations."
        )
