"""proprioceptive_swarm — client SDK for the lens-swarm consensus API.

The package contains NO inference logic by design: all computation is
server-side. Without a valid API key obtained via signup(), the client
raises SwarmNotAuthorized on every call. Nothing works offline.

0.1.8 adds Swarm.proof — the owner-only receipt inclusion proof
(GET /v1/swarm/proof/<prefix>, X-API-Key required; third parties keep
verify() for integrity-only checks) — and aligns docs with production
edge 1.8.6: trial tier is 140/day (500 lifetime, 14-day window),
model_family accepts advertised aliases (phi-2, Qwen2.5-1.5B /
Qwen2.5-1.5B-Instruct resolve to certified heads), and GET
/v1/swarm/models no longer serves certification internals.
"""
from .client import Swarm, SwarmNotAuthorized, SwarmError

__version__ = "0.1.8"
__all__ = ["Swarm", "SwarmNotAuthorized", "SwarmError"]
