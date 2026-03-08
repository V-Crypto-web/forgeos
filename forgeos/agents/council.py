from typing import Tuple, Dict, Any, List
from forgeos.providers.model_router import ProviderRouter, ModelRole
from forgeos.engine.state_machine import ExecutionContext

class CouncilAgent:
    """
    Module 9 (God Mode): Multi-Agent Council.
    Takes a draft plan and subjects it to peer review by 3 distinct personas:
    Security Expert, Performance Engineer, and Product Owner.
    If any expert rejects the plan, the Planner is asked to rewrite it.
    """
    
    def __init__(self, provider_router: ProviderRouter):
        self.router = provider_router
        
    def deliberate(self, context: ExecutionContext, draft_plan: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Runs the council review. Returns (is_approved, critique_summary, stats)
        """
        personas = [
            ("Security Expert", "Focus strictly on vulnerabilities, injection risks, hardcoded secrets, and unsafe execution paths."),
            ("Performance Engineer", "Focus on memory leaks, Big O complexity, N+1 query problems, and CPU bottlenecks."),
            ("Product Owner", "Focus on whether the plan actually achieves the Acceptance Criteria of the original Issue.")
        ]
        
        all_critiques = []
        is_approved = True
        total_cost = 0.0
        
        for name, instructions in personas:
            system_prompt = f"""You are a {name}. {instructions}
Review the proposed plan to solve the issue.
If it is safe and correct, reply ONLY with 'APPROVE'.
If there are critical flaws, reply with 'REJECT:' followed by a concise explanation of the flaw."""

            user_prompt = f"""Original Issue:
{context.issue_text}

Proposed Plan:
{draft_plan}

Provide your ruling."""

            # We use the CRITIC role for specialized review
            response = self.router.generate_response(ModelRole.CRITIC, system_prompt, user_prompt)
            ruling = response.get("content", "APPROVE").strip()
            stats = response.get("stats", {})
            total_cost += stats.get("cost", 0.0)
            
            if ruling.startswith("REJECT"):
                is_approved = False
                all_critiques.append(f"**{name} Rejection**: {ruling.replace('REJECT:', '').strip()}")
                
        summary = "\n".join(all_critiques) if not is_approved else "All council members approved."
        
        aggregate_stats = {"cost": total_cost, "model": "Mixed Council"}
        return is_approved, summary, aggregate_stats
