import re
from pydantic import BaseModel

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+|your\s+|above\s+)?instructions",
    r"disregard\s+(your\s+|the\s+|all\s+)?instructions",
    r"forget\s+(everything|all\s+instructions)",
    r"you\s+are\s+now\s+(a|an|the)",
    r"act\s+as\s+(if\s+you\s+are|a|an)",
    r"system\s+prompt",
    r"reveal\s+(your|the)\s+(system|instructions|prompt|api.?key)",
    r"output\s+(your|the)\s+(database|connection|credentials)",
    r"jailbreak",
    r"DAN\s+mode",
    r"pretend\s+you\s+(are|have\s+no)",
    r"override\s+(your|all)\s+(instructions|rules|guidelines)",
]
COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


class InjectionResult(BaseModel):
    is_injection: bool
    confidence: float
    detected_pattern: str


def detect_injection(query: str) -> InjectionResult:
    for pattern in COMPILED:
        m = pattern.search(query)
        if m:
            return InjectionResult(
                is_injection=True, confidence=0.95, detected_pattern=m.group(0)
            )
    return InjectionResult(is_injection=False, confidence=0.0, detected_pattern="")
