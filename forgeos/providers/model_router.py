import os
import json
from enum import Enum
from typing import Dict, Any, List, Optional

# Stubbing LiteLLM for the MVP architecture.
from litellm import completion, embedding

from forgeos.observability.cost_tracker import CostTracker
from forgeos.security.vault import SecretRedactor

class ModelRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    VERIFIER = "verifier"
    CRITIC = "critic"

class ProviderRouter:
    """
    Intelligence Supply Layer.
    Abstracts LLM vendor calls and routes them based on the required role.
    Supports fallback policies for robust execution.
    """
    def __init__(self):
        # Default policies for the MVP
        self.routing_policy = {
            ModelRole.PLANNER: ["gpt-4o", "claude-3-opus-20240229"],      # Needs strong reasoning
            ModelRole.CODER: ["gpt-4o-mini", "claude-3-haiku-20240307"],  # Needs to be fast and cheap
            ModelRole.VERIFIER: ["gpt-4o-mini", "gpt-4o"],                # Simple boolean logic mostly
            ModelRole.CRITIC: ["claude-3-5-sonnet-20240620", "gpt-4o"]    # Good for catching architectural flaws
        }

    def generate_response(self, role: ModelRole, system_prompt: str, user_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Routes the prompt to the appropriate model based on the role.
        Implements basic failover if the primary model fails.
        """
        models = self.routing_policy.get(role, ["gpt-4o-mini"])
        
        for model in models:
            try:
                print(f"[Router] Routing to {model} for role {role.value}...")
                return self._call_llm(model, system_prompt, user_prompt, **kwargs)
            except Exception as e:
                print(f"[Router WARNING] Model {model} failed: {e}. Trying fallback...")
                continue
                
        raise RuntimeError(f"All models failed for role: {role.value}")
        
    def _call_llm(self, model: str, system_prompt: str, user_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Internal method to execute the actual LiteLLM call.
        Mocked for the local MVP tests unless API keys are present.
        """
        # Real LiteLLM implementation
        # Redact secrets before sending to API
        safe_system_prompt = SecretRedactor.redact(system_prompt)
        safe_user_prompt = SecretRedactor.redact(user_prompt)
        
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": safe_system_prompt},
                {"role": "user", "content": safe_user_prompt}
            ],
            **kwargs
        )
        
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        cost = CostTracker.calculate_cost(model, prompt_tokens, completion_tokens)
        
        return {
            "content": response.choices[0].message.content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost,
            "model": model
        }

    def get_embedding(self, text: str, model: str = "text-embedding-3-small") -> List[float]:
        """
        Generates a dense vector embedding for the given text using LiteLLM.
        """
        try:
            # We don't strictly redact context text for embeddings yet, but we could
            response = embedding(
                model=model,
                input=text
            )
            
            prompt_tokens = response.get("usage", {}).get("prompt_tokens", 0)
            cost = CostTracker.calculate_cost(model, prompt_tokens, 0)
            
            # Since ProviderRouter doesn't have an execution context, we rely on the caller to track global cost if needed
            print(f"[Router API] Generated embedding via {model} [COST: ${cost:.6f}]")
            
            return response["data"][0]["embedding"]
        except Exception as e:
            print(f"[Router WARNING] Embedding generation failed: {e}")
            # Return an empty vector safely
            return []

    def _mock_response(self, model: str, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Simple mock responses to test the state machine flow."""
        content = ""
        if "plan" in user_prompt.lower():
            content = "1. Check auth.py \\n 2. Add empty string check -> return False."
        elif "patch" in user_prompt.lower():
            content = "```diff\\n--- a/api/auth.py\\n+++ b/api/auth.py\\n@@ -3,2 +3,4 @@\\n     if token is None:\\n         return False\\n+    if token == \"\":\\n+        return False\\n```"
        else:
            content = "Mocked response from " + model
            
        prompt_tokens = 10
        completion_tokens = 20
        cost = CostTracker.calculate_cost(model, prompt_tokens, completion_tokens)
        
        return {
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost,
            "model": model
        }
