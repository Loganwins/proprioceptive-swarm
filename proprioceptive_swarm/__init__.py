"""proprioceptive_swarm — client SDK for the lens-swarm consensus API.

The package contains NO inference logic by design: all computation is
server-side. Without a valid API key obtained via signup(), the client
raises SwarmNotAuthorized on every call. Nothing works offline.

0.1.7 adds the hook verdict client (Swarm.hook), the batch runner guard
(Swarm.batch), the receipt-chain export fetch (Swarm.export) and a local
chain walker (Swarm.verify_export) that mirrors the server's sha convention.
"""
from .client import Swarm, SwarmNotAuthorized, SwarmError

__version__ = "0.1.7"
__all__ = ["Swarm", "SwarmNotAuthorized", "SwarmError"]
