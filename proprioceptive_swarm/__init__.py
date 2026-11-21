"""proprioceptive_swarm — client SDK for the lens-swarm consensus API.

The package contains NO inference logic by design: all computation is
server-side. Without a valid API key obtained via signup(), the client
raises SwarmNotAuthorized on every call. Nothing works offline.
"""
from .client import Swarm, SwarmNotAuthorized, SwarmError

__version__ = "0.1.6"
__all__ = ["Swarm", "SwarmNotAuthorized", "SwarmError"]
