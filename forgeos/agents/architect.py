from typing import Tuple, Dict, Any
from forgeos.providers.model_router import ProviderRouter, ModelRole
from forgeos.engine.state_machine import ExecutionContext

class ArchitectAgent:
    """
    Module 8 (Enterprise): Deadlock Breaker Architect Agent.
    When the Coder and Critic are stuck in a Failure Loop (e.g. 3+ failed attempts),
    the Architect steps in to review the entire failure history and issue text.
    It writes an Architecture Decision Record (ADR) that provides a strict 
    new strategy for the Planner to follow, breaking the deadlock.
    """
    
    def __init__(self, provider_router: ProviderRouter):
        self.router = provider_router
        
    def generate_adr(self, context: ExecutionContext) -> Tuple[str, Dict[str, Any]]:
        """
        Generates an ADR to reset the Planner's approach.
        """
        # Compress failure history to not blow context window
        failures = ""
        if context.failure_memory and context.failure_memory.failures:
            for sig, data in context.failure_memory.failures.items():
                failures += f"- Strategy '{data['strategy']}' failed {data['attempts']} times. Signature: {sig[:200]}...\n"
        
        system_prompt = """You are a Principal Software Architect.
The engineering team is stuck in a failure loop trying to resolve an issue.
Your job is to read the original issue and the history of their failed attempts.
Write a strict Architecture Decision Record (ADR) that outlines a completely new, 
simplified, or alternative approach to solve the problem.
Do NOT write code. Write high-level architectural constraints and step-by-step logic 
that the Planner must follow to avoid repeating the same mistakes.

Format as a Markdown ADR:
# ADR: Deadlock Resolution
## Context
(Why they failed)
## Decision
(The new strict rules and approach)
## Consequences
(What the Planner must do)"""

        user_prompt = f"""Original Issue:
{context.issue_text}

Failure History:
{failures}

Current Broken Plan:
{context.plan}

Please provide the ADR."""

        # The Architect requires the highest reasoning capability available.
        response = self.router.generate_response(ModelRole.PLANNER, system_prompt, user_prompt)
        
        adr_text = response.get("content", "# ADR: Fallback\nRestart from scratch.")
        stats = response.get("stats", {})
        
        return adr_text, stats
