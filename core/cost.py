"""Token-to-USD cost calculation based on Gemini published pricing."""

# Official Gemini Flash rates (per token, USD)
INPUT_COST_PER_TOKEN  = 0.000_000_075   # gemini-2.0-flash input
OUTPUT_COST_PER_TOKEN = 0.000_000_30    # gemini-2.0-flash output

GEMINI_PRICING = {
    "gemini-2.0-flash": {"input": INPUT_COST_PER_TOKEN,  "output": OUTPUT_COST_PER_TOKEN},
    "gemini-1.5-flash": {"input": 0.000_000_075, "output": 0.000_000_30},
}


class CostCalculator:
    def calculate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = GEMINI_PRICING.get(model, {"input": 0.0, "output": 0.0})
        return (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
