# proprioceptive-swarm
Client SDK for the **lens-swarm**: a CPU-native consensus answer service with plurality
confidence gates and a hash-chained receipt for every response.

- All inference is server-side. The package is **inert without an account** — no local model, no offline mode.
- Free trial tier: **140 requests/day** per account (500 lifetime, 14-day window). Live numbers: `GET /v1/swarm/status`.

```
pip install proprioceptive-swarm
python -c "from proprioceptive_swarm import Swarm; s=Swarm.signup('you@example.com'); print(s.client_id)"
palswarm answer "Where is the Eiffel Tower?" "Paris" "London" --k 5
```
Evidence basis: verification-economics routing (23.5x), per-model uncertainty certification,
custody receipts (1290+, zero escapes). Claims are graded; see provider disclosures.


## Receipt proofs and integrity checks

Every response carries a hash-chained receipt id. Two routes, two audiences:

- `s.proof(receipt_prefix)` — **owner-only** (edge >= 1.8.6): `GET /v1/swarm/proof/<prefix>`
  with your `X-API-Key`. Returns the inclusion proof for one of *your* receipts:
  `position`, `receipt_sha`, `prev`, `record`, plus the chain head anchor
  (`head_sha`, `head_count`). Unknown-to-you prefixes come back as
  `{"chain_integrity": "NOT_FOUND"}`; a missing key is `401` (raised as `SwarmNotAuthorized`).
- `s.verify(receipt_prefix)` — **public, integrity-only**: `GET /v1/swarm/verify/<prefix>`
  for third parties who just need to confirm the chain link recomputes. No secret data moves.

```
s = Swarm()                       # key from signup / PALSWARM_KEY / ~/.palswarm.json
r = s.hook("phi-2", state)        # state = exactly 16 finite floats, user-supplied
p = s.proof(r["receipt"])         # owner-only inclusion proof
s.verify(r["receipt"])            # integrity-only check anyone can run
```

## Supported models

`model_family` accepts the advertised aliases: **`phi-2`** and **`Qwen2.5-1.5B` /
`Qwen2.5-1.5B-Instruct`** resolve server-side to their certified heads; canonical ids
(`qwen2.5-0.5b-inst`, `tinyllama-1.1b-chat`, ...) work directly. The live serving/cert
matrix is whatever `GET /v1/swarm/models` answers at call time — certification internals
are no longer disclosed by that route (`cert` reports `disclosed: false`), and this SDK
never ships, computes, or caches them. Certification is not deployment entitlement:
entropy flags fire only where the admin enables the feature. No model's raw logits or
weights leave the boundary.
