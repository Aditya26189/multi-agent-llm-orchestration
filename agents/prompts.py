"""
Central registry mapping agent IDs to their default system prompts.
"""
from agents.orchestrator import ORCHESTRATOR_SYSTEM
from agents.decomposition import DECOMP_PROMPT
from agents.retrieval import RETRIEVAL_PROMPT_HOP1, RETRIEVAL_PROMPT_HOP2
from agents.critique import CRITIQUE_PROMPT
from agents.synthesis import SYNTHESIS_PROMPT
from agents.compression import SUMMARIZE_PROMPT

SYSTEM_PROMPTS = {
    "orchestrator": ORCHESTRATOR_SYSTEM,
    "decomposition": DECOMP_PROMPT,
    "retrieval": RETRIEVAL_PROMPT_HOP2,
    "critique": CRITIQUE_PROMPT,
    "synthesis": SYNTHESIS_PROMPT,
    "compression": SUMMARIZE_PROMPT,
}
