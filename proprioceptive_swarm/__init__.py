"""proprioceptive_swarm — client SDK for the lens-swarm consensus API.

The package contains NO inference logic by design: all computation is
server-side. Without a valid API key obtained via signup(), the client
raises SwarmNotAuthorized on every call. Nothing works offline.

0.1.9 exposes the LIVE swarm control plane (production edge >= 1.8.7):
agents_register/agents_list/agents_gate/agents_remove manage up to 500
agents per account, and judge() runs the positional de-bias consensus
judge (lens-swarm-judge-1.0) over your agents' votes. Gates and judge
calls share the account quota; register/list/remove are free.
"""
from .client import Swarm, SwarmNotAuthorized, SwarmError

__version__ = "0.1.9"
__all__ = ["Swarm", "SwarmNotAuthorized", "SwarmError"]
