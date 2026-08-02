from pawpal_agent import PawPalAgent
from pawpal_system import Owner, Pet, Scheduler

owner = Owner(name="Alex", available_minutes=120, day_start_hour=8)
biscuit = Pet(name="Biscuit", species="dog", breed="Golden Retriever", age_years=3.0)
owner.add_pet(biscuit)

scheduler = Scheduler(owner=owner)
agent = PawPalAgent(owner=owner, scheduler=scheduler)

response = agent.run(
    "Add a 30 minute walk for Biscuit at 9am, high priority, category exercise, "
    "then generate today's plan and explain it"
)

print("=== Final response ===")
print(response)

print("\n=== Trace ===")
for entry in agent.trace:
    print(entry)
