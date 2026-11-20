import json, os, time, urllib.request, urllib.error

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Never let the API key ride a redirect to another host; POST redirects get refused."""
    def redirect_request(self, req, fp, code, msg, newheaders, newurl):
        if req.data is not None and code in (301, 302, 303):
            raise urllib.error.HTTPError(newurl, code, "redirect refused for POST", newheaders, fp)
        from urllib.parse import urlparse
        if urlparse(req.fullurl).netloc != urlparse(newurl).netloc:
            for h in list(newheaders):
                if h.lower() in ("x-api-key", "authorization"): del newheaders[h]
        return super().redirect_request(req, fp, code, msg, newheaders, newurl)

_OPENER = urllib.request.build_opener(_SafeRedirect)

API = os.environ.get("PALSWARM_API", "https://api.proprioceptiveai.com")
CFG = os.path.join(os.path.expanduser("~"), ".palswarm.json")

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
        try: body = json.loads(e.read())
        except Exception: body = {"error": str(e)}
        if e.code in (401, 403): raise SwarmNotAuthorized()
        if e.code == 429:
            raise SwarmError(body.get("error") or ("limit reached: %s" % body.get("limit")))
        raise SwarmError("HTTP %s: %s" % (e.code, body.get("error", "?")))
    except Exception as e:
        raise SwarmError("network: %r" % e)

class Swarm:
    """Gated consensus client. answer() returns selected option, agreement,
    confidence flag, quota state, and a hash-chained receipt id."""
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

    def status(self):
        """Quota/tier for this key: {'client_id','tier','used_today','limit'}."""
        if not self.key: raise SwarmNotAuthorized()
        req = urllib.request.Request(API + "/v1/swarm/status", headers={"X-API-Key": self.key})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise SwarmNotAuthorized()
            try: body = json.loads(e.read())
            except Exception: body = {}
            raise SwarmError("HTTP %s: %s" % (e.code, body.get("error", "?")))

    def verify(self, receipt_id):
        """Fetch + chain-verify a receipt by id (prefix ok)."""
        r = urllib.request.urlopen(API + "/v1/swarm/verify/" + receipt_id, timeout=30).read()
        return json.loads(r)

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
            urllib.request.urlopen(API + "/v1/swarm/health", timeout=15).read())
