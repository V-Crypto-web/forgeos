from typing import Tuple, Dict, Any
from forgeos.providers.model_router import ProviderRouter, ModelRole
from forgeos.engine.state_machine import ExecutionContext

class PRGeneratorAgent:
    """
    Module 8 (Enterprise): PR Description Generator.
    Reads the final patch and the original issue, and drafts a comprehensive 
    GitHub-style Pull Request description.
    """
    
    def __init__(self, provider_router: ProviderRouter):
        self.router = provider_router
        
    def generate_pr_description(self, context: ExecutionContext) -> Tuple[str, Dict[str, Any]]:
        """
        Generates a polished PR description using the Critic/Docs model role.
        """
        if not context.patch:
            return "No code changes were made.", {"model": "none"}
            
        system_prompt = """You are an expert Senior Software Engineer writing a Pull Request description.
Your goal is to summarize the changes made to resolve the issue clearly and professionally.
Follow this Markdown structure:
## What's Changed
- (Bullet point summary of the code changes)

## Why
- (Brief explanation of why these changes resolve the original issue)

## Testing
- (Brief mention that the code passes all automated tests)"""

        user_prompt = f"""Original Issue:
{context.issue_text}

Applied Patch:
{context.patch}

Please write the PR description."""

        # We use the CRITIC role here as it generally points to a smarter reasoning model 
        # that is good at reviewing code, like Claude 3.5 Sonnet or GPT-4o.
        response = self.router.route(ModelRole.CRITIC, system_prompt, user_prompt)
        
        pr_text = response.get("content", "Failed to generate PR description.")
        stats = response.get("stats", {})
        
        return pr_text, stats
