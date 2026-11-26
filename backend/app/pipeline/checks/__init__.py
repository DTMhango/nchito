"""Document checks (DESIGN.md 5.3, 9, 18.5): guardrails, fact tracing, claim drift, keep-out facts.

Deterministic checks run first and decide; the optional model pass can only add findings. A spec
counts as checked only for the exact content hash, and the exact Kit facts, it was checked against.
"""
