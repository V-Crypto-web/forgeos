from typing import Dict, Tuple

class CostTracker:
    """
    Standardized cost tracking module.
    Prices are per 1M tokens.
    """
    
    # Prices based on OpenAI and Anthropic docs (per 1M tokens)
    MODEL_PRICES: Dict[str, Tuple[float, float]] = {
        # Model Name: (Input Cost, Output Cost)
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-2024-05-13": (5.00, 15.00), # Original launch pricing, let's use standard API pricing
        "gpt-4o-mini": (0.150, 0.600),
        "gpt-4-turbo": (10.00, 30.00),
        
        "claude-3-5-sonnet-20240620": (3.00, 15.00),
        "claude-3-opus-20240229": (15.00, 75.00),
        "claude-3-haiku-20240307": (0.25, 1.25),
        
        "o1-preview": (15.00, 60.00),
        "o1-mini": (3.00, 12.00)
    }

    @classmethod
    def calculate_cost(cls, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calculates the exact cost of an LLM generation based on input/output token counts.
        """
        # Clean model name if it has prefixes like 'anthropic/' or 'openai/'
        clean_model = model_name
        if "/" in clean_model:
            clean_model = clean_model.split("/", 1)[1]
            
        prices = cls.MODEL_PRICES.get(clean_model)
        
        if not prices:
            # Fallback heuristics for unknown models: Assume gpt-4o pricing
            if "mini" in clean_model.lower() or "haiku" in clean_model.lower():
                prices = (0.15, 0.60)
            elif "claude-3-5-sonnet" in clean_model.lower():
                prices = (3.00, 15.00)
            else:
                prices = (2.50, 10.00) # Default to GPT-4o pricing
                
        input_cost_per_million, output_cost_per_million = prices
        
        total_cost = (input_tokens / 1_000_000) * input_cost_per_million + (output_tokens / 1_000_000) * output_cost_per_million
        return round(total_cost, 4)

    @classmethod
    def get_formatted_cost(cls, cost: float) -> str:
        """Returns the cost formatted as a currency string."""
        return f"${cost:.4f}"
