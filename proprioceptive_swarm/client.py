import hashlib, json, math, os, time, urllib.parse, urllib.request, urllib.error
from typing import Sequence

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Never let the API key ride a redirect to another host; POST redirects get refused."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.data is not None and code in (301, 302, 303):
            raise urllib.error.HTTPError(newurl, code, "redirect refused for POST", headers, fp)
        from urllib.parse import urlparse
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is not None and urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            for hdr in ("X-API-Key", "Authorization"):
                if newreq.has_header(hdr): newreq.remove_header(hdr)
                for d in (getattr(newreq, "headers", {}), getattr(newreq, "unredirected_hdrs", {})):
                    for kk in [k2 for k2 in list(d) if k2.lower() == hdr.lower()]: del d[kk]
        return newreq

_OPENER = urllib.request.build_opener(_SafeRedirect)

API = os.environ.get("PALSWARM_API", "https://api.proprioceptiveai.com")
CFG = os.path.join(os.path.expanduser("~"), ".palswarm.json")

def _state16(state):
    """Client-side guard shared by hook() and agents_gate(): the user's own state
    vector must be exactly 16 finite, non-bool numbers. Raises SwarmError BEFORE any
    network call, so a wrong local vector costs the user nothing (no quota burned)."""
    try:
        st = list(state)
    except TypeError:
        raise SwarmError("state must be a sequence of exactly 16 floats; nothing was sent")
    if len(st) != 16:
        raise SwarmError("state must be exactly 16 floats (got %d); nothing was sent" % len(st))
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in st):
        raise SwarmError("state must contain only numbers (got %s); nothing was sent"
                         % next(type(x).__name__ for x in st
                                if isinstance(x, bool) or not isinstance(x, (int, float))))
    feats = [float(x) for x in st]
    if not all(math.isfinite(y) for y in feats):
        bad = next(i for i, y in enumerate(feats) if not math.isfinite(y))
        raise SwarmError("state must be finite (index %d is NaN or +/-inf); nothing was sent" % bad)
    return feats

class SwarmError(Exception): pass
class SwarmNotAuthorized(SwarmError):
    def __init__(self):
        super().__init__("No API key. Run Swarm.signup('you@example.com') first. "
                         "The service is server-computed and does not work offline.")

def _post(path, obj=None, key=None, timeout=180):
    data = json.dumps(obj).encode() if obj is not None else b"{}"
    h = {"Content-Type": "application/json"}
    if key: h["X-API-Key"] = key
    req = urllib.request.Request(API + path, data=data, headers=h)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            out = json.loads(r.read())
        if not isinstance(out, dict): raise SwarmError("malformed response from service")
        return out
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            if not isinstance(body, dict): body = {"error": "malformed error body"}
        except Exception: body = {"error": "unreadable error body"}
        if e.code in (401, 403): raise SwarmNotAuthorized()
        if e.code == 429:
            raise SwarmError(body.get("error") or ("limit reached: %s" % body.get("limit")))
        raise SwarmError("HTTP %s: %s" % (e.code, str(body.get("error", "?"))[:200]))
    except Exception as e:
        raise SwarmError("network: %s" % type(e).__name__)

def _get(path, key=None, timeout=60):
    """GET a JSON object response through the guarded opener (same error posture as status())."""
    headers = {"X-API-Key": key} if key else {}
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            out = json.loads(r.read())
        if not isinstance(out, dict): raise SwarmError("malformed response from service")
        return out
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            if not isinstance(body, dict): body = {}
        except Exception: body = {}
        if e.code in (401, 403): raise SwarmNotAuthorized()
        raise SwarmError("HTTP %s: %s" % (e.code, str(body.get("error", "?"))[:200]))
    except SwarmError: raise
    except Exception as e:
        raise SwarmError("network: %s" % type(e).__name__)

class Swarm:
    """Gated consensus client. answer() returns selected option, agreement,
    confidence flag, quota state, and a hash-chained receipt id."""
    HOOK_VERDICTS = ("proceed", "abstain", "repair")

    def __init__(self, api_key=None, client_id=None):
        cfg = {}
        if os.path.exists(CFG):
            try: cfg = json.load(open(CFG))
            except Exception: cfg = {}
        self.key = api_key or os.environ.get("PALSWARM_KEY") or cfg.get("api_key")
        self.client_id = client_id or cfg.get("client_id")

    @classmethod
    def signup(cls, email):
        r = _post("/v1/swarm/signup", {"email": email})
        if "api_key" not in r: raise SwarmError("signup failed: %s" % r)
        saved = True
        try:
            tmp = CFG + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"api_key": r["api_key"], "client_id": r["client_id"],
                           "email": email, "tier": r.get("tier"),
                           "total_cap": r.get("total_cap"), "expires": r.get("expires"),
                           "created": int(time.time())}, f)
            os.chmod(tmp, 0o600); os.replace(tmp, CFG)
        except Exception: saved = False
        s = cls(api_key=r["api_key"], client_id=r.get("client_id"))  # NEVER inherit env/stale creds
        s.note = r.get("note", "new trial account")
        s.credential_saved = saved
        if not saved:
            import warnings
            warnings.warn("signup succeeded but credentials could not be persisted to %s; "
                          "pass api_key explicitly or fix file permissions" % CFG, RuntimeWarning)
        return s

    @property
    def authorized(self): return bool(self.key)

    def answer(self, question, choices, k=5, model=None):
        if not self.key: raise SwarmNotAuthorized()
        obj = {"question": question, "choices": list(choices), "k": k}
        if model: obj["model"] = model
        return _post("/v1/swarm/answer", obj, key=self.key)

    def select(self, question, choices, model="qwen2.5-0.5b-inst"):
        """Server-side truth-selection head (gated). Returns selected_index/letter/text,
        low_confidence flag, quota state, receipt. Head weights never leave the server."""
        if not self.key: raise SwarmNotAuthorized()
        return _post("/v1/swarm/select", {"question": question, "choices": list(choices),
                                          "model": model}, key=self.key)

    def hook(self, model_family, state):
        """Ask the server-side hook head for a verdict on a model state vector.
        POSTs /v1/swarm/hook {"model_family", "state"} with the API key; the reply is a
        verdict-only passthrough dict: {"hook_verdict": proceed|abstain|repair, "margin",
        "model", "client_id", "evidence", quota fields, "receipt", "version"}.
        CLIENT-SIDE GUARD (runs BEFORE any network call, so a wrong local vector costs
        the user nothing): model_family must be a 1-64 char string and state exactly 16
        finite non-bool numbers, else SwarmError. The response is accepted only if
        hook_verdict is one of proceed|abstain|repair; anything else raises SwarmError.
        model_family accepts the advertised aliases: "phi-2" and "Qwen2.5-1.5B" /
        "Qwen2.5-1.5B-Instruct" resolve server-side to their certified heads.
        No model internals are sent or received — the head lives server-side."""
        if not self.key: raise SwarmNotAuthorized()
        if not isinstance(model_family, str) or not (1 <= len(model_family) <= 64):
            raise SwarmError("model_family must be a non-empty string <=64 chars; nothing was sent")
        feats = _state16(state)
        r = _post("/v1/swarm/hook", {"model_family": model_family, "state": feats}, key=self.key)
        if r.get("hook_verdict") not in self.HOOK_VERDICTS:
            raise SwarmError("service returned an invalid hook_verdict: %r" % (r.get("hook_verdict"),))
        return r

    def batch(self, items):
        """Run up to 25 select|hook items in one authorized call (POST /v1/swarm/batch,
        body {"items": [...]}). Returns the server's result dict (per-item verdicts +
        summary + batch receipt). CLIENT-SIDE GUARD before sending: items must be a list
        with 1 <= len(items) <= 25, else SwarmError — an out-of-range batch never leaves
        the machine and never costs quota."""
        if not self.key: raise SwarmNotAuthorized()
        if not isinstance(items, list):
            raise SwarmError("batch items must be a list (got %s); nothing was sent"
                             % type(items).__name__)
        if not (1 <= len(items) <= 25):
            raise SwarmError("batch requires 1-25 items (got %d); nothing was sent" % len(items))
        return _post("/v1/swarm/batch", {"items": items}, key=self.key)

    # ------------------------------------------------ swarm control plane (edge >= 1.8.7)
    def agents_register(self, name, family):
        """Register an agent on the live swarm control plane:
        POST /v1/swarm/agents/register {"name", "family"}. Returns the server's
        receipt verbatim: {"ok": true, "client_id", "agent_id" (always "agt_"-prefixed),
        "family", "name_sha", "n_agents", "cap" (500), "receipt", "version"}.
        Each account may hold up to 500 live agents; registration itself consumes
        no quota. `family` is passed through verbatim — the server owns family
        validation and any 4xx comes back through the standard error mapping
        (401/403 -> SwarmNotAuthorized, otherwise SwarmError carrying the server's
        message)."""
        if not self.key: raise SwarmNotAuthorized()
        return _post("/v1/swarm/agents/register", {"name": name, "family": family}, key=self.key)

    def agents_list(self):
        """GET /v1/swarm/agents — the caller's own swarm roster, owner-scoped (only
        agents registered under this key are ever returned):
        {"product", "version", "client_id", "count", "cap" (500),
        "agents": [{"agent_id", "family", "verdicts_seen", "last_verdict",
        "flagged_count"}, ...]}. Listing is free: it never consumes quota."""
        if not self.key: raise SwarmNotAuthorized()
        return _get("/v1/swarm/agents", key=self.key)

    def agents_gate(self, agent_id, state):
        """Run one verdict through a registered agent's server-side hook:
        POST /v1/swarm/agents/gate {"agent_id", "state"}. `state` is the caller's own
        16-float feature vector; the same client-side guard as hook() runs BEFORE the
        wire, so a malformed vector costs nothing and burns no quota.
        Returns the verdict-only hook response: {"hook_verdict":
        proceed|abstain|repair, "margin", "model", "evidence", "client_id",
        "agent_id", "flagged", "verdicts_seen", "flagged_count", quota fields,
        "receipt", "version"} — per-agent counters ride back with the verdict.
        Gates share the account quota: one gate == one request against the same
        daily limit (see status()). No model internals cross the boundary in either
        direction. 401/403 -> SwarmNotAuthorized; other 4xx -> SwarmError."""
        if not self.key: raise SwarmNotAuthorized()
        if not isinstance(agent_id, str) or not agent_id:
            raise SwarmError("agent_id must be a non-empty string; nothing was sent")
        feats = _state16(state)
        r = _post("/v1/swarm/agents/gate", {"agent_id": agent_id, "state": feats}, key=self.key)
        if r.get("hook_verdict") not in self.HOOK_VERDICTS:
            raise SwarmError("service returned an invalid hook_verdict: %r" % (r.get("hook_verdict"),))
        return r

    def agents_remove(self, agent_id):
        """Remove one agent from the caller's swarm: POST /v1/swarm/agents/remove
        {"agent_id"}. Returns {"ok": true, "client_id", "agent_id", "n_agents",
        "cap", "receipt", "version"}. Free — removal never consumes quota."""
        if not self.key: raise SwarmNotAuthorized()
        if not isinstance(agent_id, str) or not agent_id:
            raise SwarmError("agent_id must be a non-empty string; nothing was sent")
        return _post("/v1/swarm/agents/remove", {"agent_id": agent_id}, key=self.key)

    def judge(self, question, choices, votes):
        """Positional de-bias consensus judge over the caller's registered agents:
        POST /v1/swarm/judge {"question", "choices", "items"}, where items is the
        votes list — one {"agent_id", "answer_index"} per agent, at most 50. Duplicate
        agent_ids are rejected by the server with a 4xx (raised here as SwarmError).
        Returns the judge verdict: {"product": "lens-swarm-judge-1.0", "client_id",
        "converged", "answer_index", "leaning_index", "agreement", "n_agents",
        "dissent", "tied_indices", "debias_offset", "reason", "n_votes", quota fields,
        "receipt", "version"}. The judge de-biases for answer position across your
        agents' votes; how it does that is server-side and not part of this contract.
        A judge call consumes quota like any other request. CLIENT-SIDE GUARD before
        the wire: votes must be a non-empty list of <= 50 dicts carrying agent_id and
        integer answer_index, else SwarmError and nothing is sent."""
        if not self.key: raise SwarmNotAuthorized()
        if not isinstance(votes, list) or not (1 <= len(votes) <= 50):
            raise SwarmError("votes must be a non-empty list of <=50 {agent_id, answer_index} "
                             "items (got %s); nothing was sent"
                             % ("len %d" % len(votes) if isinstance(votes, list)
                                else type(votes).__name__))
        items = []
        for i, v in enumerate(votes):
            if not isinstance(v, dict) or "agent_id" not in v or "answer_index" not in v:
                raise SwarmError("votes[%d] must carry agent_id and answer_index; nothing was sent" % i)
            ai = v["answer_index"]
            if isinstance(ai, bool) or not isinstance(ai, int):
                raise SwarmError("votes[%d].answer_index must be an integer; nothing was sent" % i)
            items.append({"agent_id": v["agent_id"], "answer_index": ai})
        return _post("/v1/swarm/judge", {"question": question, "choices": list(choices),
                                         "items": items}, key=self.key)

    def export(self, since=None, until=None):
        """GET /v1/swarm/export?since=<ts>&until=<ts> — fetch the caller's receipt-chain
        export bundle as a dict {"events": [ledger records...], ...}. since/until are
        optional epoch-second bounds; None omits the param. Validate any returned bundle
        with verify_export() before trusting it."""
        if not self.key: raise SwarmNotAuthorized()
        params = {}
        for name, val in (("since", since), ("until", until)):
            if val is not None:
                if isinstance(val, bool):
                    raise SwarmError("%s must be an epoch-seconds integer" % name)
                try: val = int(val)
                except (TypeError, ValueError):
                    raise SwarmError("%s must be an epoch-seconds integer" % name)
                params[name] = val
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        return _get("/v1/swarm/export" + qs, key=self.key)

    def verify_export(self, bundle):
        """Walk an export bundle's hash chain and return True only if every link recomputes.
        Chain convention (mirrors the server's receipt() writer and verify_bundle exactly,
        lens-swarm edge >= 1.8.3):
          * signed payload = record minus the chain/meta keys {sha, prev, prev_sha, index,
            event_type}; raw = json.dumps(payload, sort_keys=True);
          * sha = sha256(PREV_FULL_SHA + raw) where PREV_FULL_SHA is the record's own
            prev_sha field (full 64-hex; "" at ledger genesis) in bundle form, or the
            previous record's sha in raw ledger form (sequential chain);
          * in bundle form, when consecutive events are adjacent in the global ledger
            (index difference == 1) the embedded prev_sha must equal the preceding event's
            sha - catches splicing; a gap is an honest cross-client omission, not a break.
        An empty events list is vacuously intact (True). A bundle that is not a dict with
        an "events" list raises SwarmError (shape problem, not a chain verdict)."""
        if not isinstance(bundle, dict) or not isinstance(bundle.get("events"), list):
            raise SwarmError("export bundle must be a dict containing an 'events' list")
        _META = ("sha", "prev", "prev_sha", "index", "event_type")
        prev = ""
        prev_index = None
        for e in bundle["events"]:
            if not isinstance(e, dict) or not isinstance(e.get("sha"), str) or not e.get("sha"):
                return False
            payload = {k: v for k, v in e.items() if k not in _META}
            if isinstance(e.get("prev_sha"), str):
                base = e["prev_sha"]
                idx = e.get("index")
                if (prev_index is not None and isinstance(idx, int) and idx == prev_index + 1
                        and base != prev):
                    return False
            else:
                base = prev
            chk = hashlib.sha256((base + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
            if chk != e["sha"]:
                return False
            prev = e["sha"]
            prev_index = e.get("index") if isinstance(e.get("index"), int) else None
        return True

    def status(self):
        """Quota/tier for this key: {'client_id','tier','used_today','limit',...}."""
        if not self.key: raise SwarmNotAuthorized()
        req = urllib.request.Request(API + "/v1/swarm/status", headers={"X-API-Key": self.key})
        try:
            with _OPENER.open(req, timeout=60) as r:
                out = json.loads(r.read())
            if not isinstance(out, dict): raise SwarmError("malformed status response")
            return out
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise SwarmNotAuthorized()
            try:
                body = json.loads(e.read())
                if not isinstance(body, dict): body = {}
            except Exception: body = {}
            raise SwarmError("HTTP %s: %s" % (e.code, str(body.get("error", "?"))[:200]))
        except SwarmError: raise
        except Exception as e:
            raise SwarmError("network: %s" % type(e).__name__)

    def verify(self, receipt_id):
        """Fetch + chain-verify a receipt by id (prefix ok). Owner receipts return
        full payload; non-owners get chain-integrity fields only (A10 posture)."""
        if not receipt_id or len(str(receipt_id)) < 8:
            raise SwarmError("receipt prefix must be >= 8 chars")
        headers = {"X-API-Key": self.key} if self.key else {}
        try:
            with _OPENER.open(urllib.request.Request(API + "/v1/swarm/verify/" + urllib.parse.quote(str(receipt_id)), headers=headers), timeout=60) as r:
                out = json.loads(r.read())
            if not isinstance(out, dict): raise SwarmError("malformed verify response")
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404: return {"chain_integrity": "NOT_FOUND"}
            try:
                body = json.loads(e.read())
                if not isinstance(body, dict): body = {}
            except Exception: body = {}
            raise SwarmError("HTTP %s: %s" % (e.code, str(body.get("error", "?"))[:200]))
        except SwarmError: raise
        except Exception as e:
            raise SwarmError("network: %s" % type(e).__name__)

    def proof(self, receipt_prefix):
        """GET /v1/swarm/proof/<prefix> — OWNER-ONLY inclusion proof (edge >= 1.8.6).
        Sends the stored API key as X-API-Key; the service matches the prefix against
        YOUR receipts only and returns {position, receipt_sha, prev, record,
        proof: "inclusion", head_sha, head_count, verify_hint}, or the integrity
        verdict {chain_integrity: "NOT_FOUND", head_count} passed through as-is
        (200-body posture, same as verify()). 4xx maps to the standard client errors:
        401/403 -> SwarmNotAuthorized, anything else -> SwarmError. Third parties who
        need integrity-only checks use verify() (no key required).
        CLIENT-SIDE GUARD before any network call: prefix must be >= 8 chars, else
        SwarmError. The client computes nothing — every field is the server's chain."""
        if not self.key: raise SwarmNotAuthorized()
        if not receipt_prefix or len(str(receipt_prefix)) < 8:
            raise SwarmError("receipt prefix must be >= 8 chars; nothing was sent")
        return _get("/v1/swarm/proof/" + urllib.parse.quote(str(receipt_prefix)), key=self.key)

    def order_stub(self, model="qwen2.5-0.5b-inst", note=""):
        """Draft a DISTILL-ORDER ticket locally (SKU intake only).
        Fulfillment is an offline GPU job run by Proprioceptive AI; weights
        are NEVER shipped, downloaded, or exposed by this client. No server
        route exists yet, so nothing is billed; the only possible network
        call is an authorized /status read resolving client_id when the
        client was constructed from a bare key."""
        cid = self.client_id
        if not cid and self.key:
            try:
                cid = self.status().get("client_id")
            except Exception:
                cid = None
        return {"sku": "distill-order", "model": model,
                "client_id": cid,
                "requested_at": int(time.time()),
                "status": "draft-not-billed",
                "note": note or ("Order intake opens with the storefront; "
                                 "fulfillment is offline; weights never ship.")}

    def health(self):
        return _post("/v1/swarm/health", {}) if False else json.loads(
            _OPENER.open(API + "/v1/swarm/health", timeout=15).read())
