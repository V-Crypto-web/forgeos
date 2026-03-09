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
            ModelRole.PLANNER:  ["gpt-4o", "claude-3-opus-20240229", "gemini/gemini-1.5-pro"],
            ModelRole.CODER:    ["gpt-4o-mini", "claude-3-haiku-20240307", "gemini/gemini-1.5-flash"],
            ModelRole.VERIFIER: ["gpt-4o-mini", "gpt-4o", "gemini/gemini-1.5-flash"],
            ModelRole.CRITIC:   ["claude-3-5-sonnet-20240620", "gpt-4o", "gemini/gemini-1.5-pro"],
        }

    def generate_response(self, role: ModelRole, system_prompt: str, user_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Routes the prompt to the appropriate model based on the role.
        Implements basic failover if the primary model fails.
        """
        models = self.routing_policy.get(role, ["gpt-4o-mini"])
        
        if os.environ.get("FORGEOS_MOCK_LLM") == "true":
            print(f"[Router API] using mock response for role {role.value}")
            return self._mock_response(models[0], system_prompt, user_prompt)
            
        for model in models:
            try:
                print(f"[Router] Routing to {model} for role {role.value}...")
                return self._call_llm(model, system_prompt, user_prompt, **kwargs)
            except Exception as e:
                print(f"[Router WARNING] Model {model} failed: {e}. Trying fallback...")
                continue
                
        if os.environ.get("FORGEOS_MOCK_LLM", "false").lower() != "true":
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
        
        # Extract specific parameters from kwargs or set defaults
        max_tokens = kwargs.pop("max_tokens", None) # Use None to let LiteLLM decide if not provided
        temperature = kwargs.pop("temperature", 0.0) # Default temperature to 0.0
        
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": safe_system_prompt},
                {"role": "user", "content": safe_user_prompt}
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=120, # Updated timeout to 120 seconds
            **kwargs # Pass any remaining kwargs
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
        if "cto agent" in system_prompt.lower() or "epic" in user_prompt.lower():
            content = '''```json
{
  "epic_summary": "Full auth system mock",
  "sub_tasks": [
    {
      "order": 1,
      "title": "SubTask 1 Models",
      "description": "Create user models",
      "expected_files_to_touch": ["models/user.py"]
    },
    {
      "order": 2,
      "title": "SubTask 2 Auth",
      "description": "Create util",
      "expected_files_to_touch": ["core/auth.py"]
    }
  ]
}
```'''
        elif "objective engine" in system_prompt.lower():
            if "REVISED" in user_prompt.upper():
                content = '''```json
{
  "approved": true,
  "reason": "Revised plan aligns with constitution."
}
```'''
            else:
                content = '''```json
{
  "approved": false,
  "reason": "Constitution Violation: Attempting to modify cosmetic UI elements which is strictly deprioritized."
}
```'''
        elif "plan" in user_prompt.lower():
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
