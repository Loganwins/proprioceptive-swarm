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


## Supported models (U4v2 certification, 2026-11-18)

Balanced 100-item TruthfulQA-MC panel (gold position uniformized; supersedes the unbalanced
v1 sweep — v1 numbers do not transfer). AUROC = entropy-detects-wrong; thr = model-normalized
null p70 bits; precision = flagged-on-wrong rate at thr. Live matrix: `GET /v1/swarm/models`.

| model | class | AUROC | flag precision | thr (bits) |
|---|---|---|---|---|
| qwen2.5-0.5b-inst | serving | 0.781 | 1.000 | 1.914 |
| qwen2.5-3b-inst | cert-only | 0.746 | 0.806 | 0.292 |
| pythia-1.4b | cert-only | 0.666 | 0.893 | 1.751 |
| tinyllama-1.1b-chat | serving | 0.661 | 0.963 | 2.258 |
| mamba-1.4b | cert-only | 0.638 | 0.846 | 2.250 |
| qwen2.5-1.5b-inst | cert-only | 0.600 | 0.850 | 2.223 |
| hermes-3-8b | cert-only | 0.597 | 0.941 | 2.288 |
| zephyr-7b-beta | cert-only | 0.552 | 0.743 | 2.286 |
| phi-2 | cert-only | 0.550 | 0.875 | 2.267 |
| opt-1.3b | not supported | — | — | — |

Certification != deployment entitlement: entropy flags fire only where the admin enables the
feature; `serving` rows are the CPU tier live today. No model's raw logits leave the boundary.
