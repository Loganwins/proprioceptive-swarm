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


## Swarm control plane (live — production edge >= 1.8.7)

Register your own swarm of up to **500 agents** per account and drive it through four
routes plus the judge. Everything stays server-side; the plane is contract-only here —
no internals are documented or shipped by this SDK.

| Method | Route | Costs quota? |
|---|---|---|
| `s.agents_register(name, family)` | `POST /v1/swarm/agents/register` | no |
| `s.agents_list()` | `GET /v1/swarm/agents` (owner-scoped) | no |
| `s.agents_gate(agent_id, state)` | `POST /v1/swarm/agents/gate` | **yes — shared account quota** |
| `s.agents_remove(agent_id)` | `POST /v1/swarm/agents/remove` | no |
| `s.judge(question, choices, votes)` | `POST /v1/swarm/judge` | **yes** |

- `agents_register` returns `{ok, client_id, agent_id (agt_-prefixed), family, name_sha,
  n_agents, cap: 500, receipt, version}`; `family` is passed through for server-side
  validation (advertised aliases like `phi-2` resolve to certified heads).
- `agents_gate` sends your 16-float state vector to one agent and returns a **verdict-only**
  hook response (`hook_verdict` proceed|abstain|repair) carrying that agent's counters:
  `flagged`, `verdicts_seen`, `flagged_count`, plus `quota_used_today`. Gates draw from the
  same daily quota as every other billable call.
- `judge` is the **positional de-bias judge** (`lens-swarm-judge-1.0`): give it the question,
  the choices, and `votes` = a list of `{agent_id, answer_index}` — one vote per agent, up
  to 50; duplicate agent ids are rejected with a 4xx. It returns `{converged, answer_index,
  leaning_index, agreement, n_agents, dissent, tied_indices, debias_offset, reason, n_votes,
  receipt, ...}`. The judge corrects for answer position across your agents' votes; how it
  does that is server-side and outside this contract.

```
s = Swarm()                                   # signup once, key kept in ~/.palswarm.json
a = s.agents_register("scout-1", "phi-2")     # -> a["agent_id"] (agt_...)
v = s.agents_gate(a["agent_id"], state16)     # verdict-only; costs 1 quota
j = s.judge("Q?", ["yes", "no"],
            [{"agent_id": x, "answer_index": i} for x, i in swarm_votes])
s.agents_remove(a["agent_id"])                # free
```

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
