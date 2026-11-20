# proprioceptive-swarm
Client SDK for the **lens-swarm**: a CPU-native consensus answer service with plurality
confidence gates and a hash-chained receipt for every response.

- All inference is server-side. The package is **inert without an account** — no local model, no offline mode.
- Free trial tier: 50 answers/day per account.

```
pip install proprioceptive-swarm
python -c "from proprioceptive_swarm import Swarm; s=Swarm.signup('you@example.com'); print(s.client_id)"
palswarm answer "Where is the Eiffel Tower?" "Paris" "London" --k 5
```
Evidence basis: verification-economics routing (23.5x), per-model uncertainty certification,
custody receipts (500+, zero escapes). Claims are graded; see provider disclosures.


[scrubbed-ip]

[scrubbed-ip]
v1 sweep — v1 numbers do not transfer). Certification internals (metric definitions,
thresholds and per-model scores are not disclosed. Live matrix: `GET /v1/swarm/models`.

| model | class | — | — | — |
|---|---|---|---|---|
| qwen2.5-0.5b-inst | serving | — | — | — |
| qwen2.5-3b-inst | cert-only | — | — | — |
| pythia-1.4b | cert-only | — | — | — |
| tinyllama-1.1b-chat | serving | — | — | — |
| mamba-1.4b | cert-only | — | — | — |
| qwen2.5-1.5b-inst | cert-only | — | — | — |
| hermes-3-8b | cert-only | — | — | — |
| zephyr-7b-beta | cert-only | — | — | — |
| phi-2 | cert-only | — | — | — |
[scrubbed-ip]

Certification != deployment entitlement: entropy flags fire only where the admin enables the
feature; `serving` rows are the CPU tier live today. No model's raw logits leave the boundary.
