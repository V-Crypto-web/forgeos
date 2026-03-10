import os
import sys
from forgeos.providers.model_router import ProviderRouter, ModelRole
from forgeos.engine.objective_engine import ObjectiveEngine

def generate_epic():
    # We must use real LLM for this, so ensure mock is false
    os.environ["FORGEOS_MOCK_LLM"] = "false"
    
    router = ProviderRouter()
    repo_path = "/Users/vasiliyprachev/Python_Projects/ForgeAI"
    
    engine = ObjectiveEngine(router)
    engine.load_constitution(repo_path)
    constitution = engine.get_context_injection()
    
    sys_prompt = f"""You are the lead Architect and CTO of ForgeOS.
ForgeOS is an Autonomous Agentic Development OS.
Your task is to analyze the current state of the project and propose the NEXT BIG EPIC (feature or architectural improvement) that will move ForgeOS closer to its ultimate goal of being a fully autonomous, self-improving, and resilient software engineering platform.

{constitution}

Recent completed Epics:
- Epic 43: Pattern Library & Hybrid Semantic Retrieval (Experience Replay)
- Epic 56: CTO Agent & Sub-task Delegation (Hierarchical Execution)
- Epic 61: Epic Graph & Sub-task Telemetry
- Epic 62: Project Constitution & Objective Layer

Based on these recent additions, identify what the system lacks the most right now to become a truly capable Level 5 Autonomous Developer.

Provide the Epic in a detailed markdown format:
1. Title (Epic XX: ...)
2. Objective
3. Motivation (Why is this the most critical next step?)
4. Proposed Technical Solution (Architecture)
5. Success Criteria
"""
    
    user_prompt = "Draft the next critical Epic for ForgeOS."
    
    print("Asking the CTO Agent (GPT-4o) to dream up the next Epic...\n")
    response = router.generate_response(ModelRole.PLANNER, sys_prompt, user_prompt)
    print("--- GENERATED EPIC ---\n")
    print(response["content"])
    
    with open("next_epic_proposal.md", "w") as f:
        f.write(response["content"])
    print("\n--- Saved to next_epic_proposal.md ---")

if __name__ == "__main__":
    generate_epic()
