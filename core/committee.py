
from core.llm import generate_rules_from_samples, historical_negatives, validate_against_historical
def run_committee_phased(samples, phase: str, trace_id: str):
    candidates = generate_rules_from_samples(samples, phase=phase)
    passed=[]
    if phase in ("v1点0",):
        passed = candidates[:3]
    elif phase in ("v1点5","v2点0"):
        for c in candidates[:5]:
            negs = historical_negatives(signature=c["sample_log"][:16], top_k=50)
            v = validate_against_historical(c, negs)
            if v.get("ok", False): passed.append(c)
    return passed
