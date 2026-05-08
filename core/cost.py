"""
Cost calculation logic mapping token usage to USD based on Gemini pricing.
"""
from typing import Dict
from core.context import SharedContext

# Pricing for Gemini 2.0 Flash (as of mid-2024, approximately $0.15 per 1M input tokens, $0.60 per 1M output tokens)
# Since we just have generic token counts from our len//4 heuristic, we will use a blended rate of $0.35 per 1M tokens.
GEMINI_FLASH_BLENDED_RATE_PER_1M = 0.35

class CostCalculator:
    @staticmethod
    def calculate_cost(context: SharedContext) -> float:
        """
        Calculates the total USD cost for a given job context based on its budget registry.
        """
        total_tokens = sum(entry.used_tokens for entry in context.budget_registry.values())
        cost_usd = (total_tokens / 1_000_000) * GEMINI_FLASH_BLENDED_RATE_PER_1M
        return round(cost_usd, 6)
