#!/usr/bin/env python3
"""Self-contained functional suite for the proprioceptive-swarm client SDK (0.1.9).

Runs entirely against a local stub edge on an ephemeral 127.0.0.1 port — nothing
external is touched. Covers: signup credential persistence, answer/select/hook/batch/
export/status/verify, the 0.1.8 proof route (owner gate, inclusion happy path,
NOT_FOUND passthrough, 401 mapping, prefix guard), the 0.1.9 swarm control plane
(agents_register/agents_list/agents_gate/agents_remove/judge: verdict-only shapes,
no-leak key allowlist, quota-shared gate fields, duplicate-vote rejection), and the
client-side guards that must never put bytes on the wire, plus the verify_export chain
walker against a chain built with the server's exact sha convention.

Run:  python3 -m unittest discover -s tests -v   (from the repo root)
"""
import hashlib, json, os, socket, sys, threading, unittest, urllib.parse, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.pop("PALSWARM_KEY", None)

from proprioceptive_swarm import Swarm, SwarmError, SwarmNotAuthorized  # noqa: E402
from proprioceptive_swarm import client  # noqa: E402
import proprioceptive_swarm as pkg  # noqa: E402

GOOD = [1.0] * 16


def chain_record(prev, index, **fields):
    """Build a ledger record exactly as the server's receipt() writer does:
    signed payload = fields minus meta {sha, prev, prev_sha, index, event_type};
    sha = sha256(prev_sha_base + json.dumps(payload, sort_keys=True))."""
    rec = dict(fields, index=index)
    if prev is not None:
        rec["prev_sha"] = prev
    base = rec.get("prev_sha", "")
    payload = {k: v for k, v in rec.items()
               if k not in ("sha", "prev", "prev_sha", "index", "event_type")}
    rec["sha"] = hashlib.sha256((base + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    rec["prev"] = base
    return rec


class StubHandler(BaseHTTPRequestHandler):
    """Minimal stand-in for the lens-swarm edge. Routes live in the class-level
    table set by each test via the server fixture."""

    def log_message(self, *a):  # silence
        pass

    def _dispatch(self, method):
        path = urllib.parse.urlparse(self.path).path
        self.server.hits.append((method, self.path,
                                 {k.lower(): v for k, v in self.headers.items()}))
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(ln) if ln else b""
        if body:
            try:
                self.server.last_body = json.loads(body)
            except Exception:
                self.server.last_body = body
        routes = self.server.routes
        key = (method, path)
        target = None
        if key in routes:
            target = routes[key]
        else:
            for (m, pfx), fn in routes.items():
                if m == method and pfx.endswith("*") and path.startswith(pfx[:-1]):
                    target = fn
                    break
        if target is None:
            code, payload = 404, {"error": "stub: no route %s" % key}
        elif callable(target):
            res = target(self)
            if res is None:
                return  # handler wrote the response itself
            code, payload = res
        else:
            code, payload = target
        raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


class StubServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the per-test route table and request log."""
    routes: dict
    hits: list
    last_body: object

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.routes = {}
        self.hits = []
        self.last_body = None


class StubCase(unittest.TestCase):
    def setUp(self):
        self.srv = StubServer(("127.0.0.1", 0), StubHandler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self._api = client.API
        client.API = "http://127.0.0.1:%d" % self.port
        self._cfg = client.CFG
        self.credpath = os.path.join(REPO, ".stub_creds_test.json")
        client.CFG = self.credpath
        if os.path.exists(self.credpath):
            os.remove(self.credpath)

    def tearDown(self):
        client.API = self._api
        client.CFG = self._cfg
        if os.path.exists(self.credpath):
            os.remove(self.credpath)
        self.srv.shutdown()
        self.srv.server_close()

    def wire(self):
        return list(self.srv.hits)

    def sw(self, key="k-test-key"):
        return Swarm(api_key=key)


# ---------------------------------------------------------------- version meta
class TestVersion(unittest.TestCase):
    def test_pkg_version(self):
        self.assertEqual(pkg.__version__, "0.1.9")

    def test_exports(self):
        self.assertEqual(sorted(pkg.__all__), sorted(["Swarm", "SwarmNotAuthorized", "SwarmError"]))


# ------------------------------------------------------------------- signup
class TestSignup(StubCase):
    def test_signup_saves_creds_and_returns_client(self):
        self.srv.routes[("POST", "/v1/swarm/signup")] = (
            200, {"api_key": "abc123", "client_id": "c-1", "tier": "trial",
                  "total_cap": 500, "expires": 99, "note": "new trial account"})
        s = Swarm.signup("user@example.com")
        self.assertEqual(s.key, "abc123")
        self.assertEqual(s.client_id, "c-1")
        self.assertTrue(s.credential_saved)
        cfg = json.load(open(self.credpath))
        self.assertEqual(cfg["api_key"], "abc123")
        self.assertEqual(oct(os.stat(self.credpath).st_mode)[-3:], "600")

    def test_signup_missing_key_raises(self):
        self.srv.routes[("POST", "/v1/swarm/signup")] = (200, {"error": "gated"})
        with self.assertRaises(SwarmError):
            Swarm.signup("user@example.com")

    def test_authorized_property(self):
        self.assertFalse(Swarm(api_key=None).authorized)
        self.assertTrue(Swarm(api_key="x").authorized)


# ------------------------------------------------------------------- answer
class TestAnswer(StubCase):
    def test_answer_happy_with_key_header(self):
        self.srv.routes[("POST", "/v1/swarm/answer")] = (
            200, {"selected": "Paris", "agreement": 4, "confidence_flag": False,
                  "quota_used_today": 1, "quota_limit": 140, "receipt": "deadbeef" * 8})
        r = self.sw().answer("Q?", ["Paris", "London"], k=5)
        self.assertEqual(r["selected"], "Paris")
        self.assertEqual(self.srv.hits[0][2].get("x-api-key"), "k-test-key")
        self.assertEqual(self.srv.last_body["k"], 5)

    def test_answer_without_key_never_touches_wire(self):
        s = Swarm(api_key=None)
        with self.assertRaises(SwarmNotAuthorized):
            s.answer("Q?", ["a", "b"])
        self.assertEqual(self.wire(), [])

    def test_answer_429_maps_error_with_body_message(self):
        self.srv.routes[("POST", "/v1/swarm/answer")] = (429, {"error": "daily limit 140"})
        with self.assertRaises(SwarmError) as cm:
            self.sw().answer("Q", ["a", "b"])
        self.assertIn("140", str(cm.exception))


# -------------------------------------------------------------------- hook
class TestHook(StubCase):
    def test_hook_happy_verdict_passthrough(self):
        self.srv.routes[("POST", "/v1/swarm/hook")] = (
            200, {"hook_verdict": "proceed", "margin": 0.4, "model": "phi2",
                  "client_id": "c-1", "receipt": "r" * 16, "version": "1.8.6"})
        r = self.sw().hook("phi-2", GOOD)
        self.assertEqual(r["hook_verdict"], "proceed")
        self.assertEqual(self.srv.last_body["model_family"], "phi-2")
        self.assertEqual(self.srv.last_body["state"], GOOD)

    def test_hook_invalid_verdict_rejected(self):
        self.srv.routes[("POST", "/v1/swarm/hook")] = (200, {"hook_verdict": "maybe"})
        with self.assertRaises(SwarmError):
            self.sw().hook("phi-2", GOOD)

    def _guard(self, family, state):
        with self.assertRaises(SwarmError):
            self.sw().hook(family, state)
        self.assertEqual(self.wire(), [], "guard must not touch the wire")

    def test_guard_family_not_string(self):
        self._guard(123, GOOD)

    def test_guard_family_empty(self):
        self._guard("", GOOD)

    def test_guard_family_too_long(self):
        self._guard("x" * 65, GOOD)

    def test_guard_state_short(self):
        self._guard("phi-2", [1.0] * 15)

    def test_guard_state_not_sequence(self):
        self._guard("phi-2", 42)

    def test_guard_state_bool(self):
        self._guard("phi-2", [True] + [1.0] * 15)

    def test_guard_state_nan(self):
        self._guard("phi-2", [float("nan")] + [1.0] * 15)

    def test_guard_state_inf(self):
        self._guard("phi-2", [1.0] * 15 + [float("inf")])

    def test_hook_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).hook("phi-2", GOOD)
        self.assertEqual(self.wire(), [])


# ------------------------------------------------------------------- batch
class TestBatch(StubCase):
    def test_batch_passthrough(self):
        self.srv.routes[("POST", "/v1/swarm/batch")] = (
            200, {"results": [{"ok": True}, {"ok": True}], "summary": {"n": 2}, "receipt": "b" * 16})
        r = self.sw().batch([{"type": "hook", "model_family": "phi-2", "state": GOOD},
                             {"type": "select", "question": "Q", "choices": ["a", "b"]}])
        self.assertEqual(r["summary"]["n"], 2)
        self.assertEqual(len(self.srv.last_body["items"]), 2)

    def _guard(self, items):
        with self.assertRaises(SwarmError):
            self.sw().batch(items)
        self.assertEqual(self.wire(), [])

    def test_guard_not_list(self):
        self._guard({"type": "hook"})

    def test_guard_empty(self):
        self._guard([])

    def test_guard_26(self):
        self._guard([{"type": "hook"}] * 26)

    def test_batch_without_key(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).batch([{"type": "hook"}])


# ------------------------------------------------------------------ export
class TestExport(StubCase):
    def test_export_happy_and_params(self):
        self.srv.routes[("GET", "/v1/swarm/export")] = (200, {"events": [], "count": 0})
        s = self.sw()
        s.export()
        self.assertEqual(self.srv.hits[-1][1], "/v1/swarm/export")
        s.export(since=100, until=200)
        self.assertIn("since=100", self.srv.hits[-1][1])
        self.assertIn("until=200", self.srv.hits[-1][1])
        self.assertEqual(self.srv.hits[-1][2].get("x-api-key"), "k-test-key")

    def test_export_rejects_bool_since(self):
        with self.assertRaises(SwarmError):
            self.sw().export(since=True)
        self.assertEqual(self.wire(), [])

    def test_export_rejects_garbage_since(self):
        with self.assertRaises(SwarmError):
            self.sw().export(since="yesterday")
        self.assertEqual(self.wire(), [])

    def test_export_without_key(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).export()


# ----------------------------------------------------------- verify_export
class TestVerifyExport(unittest.TestCase):
    def test_valid_bundle_true(self):
        e1 = chain_record("", 10, event="signup", client_id="c-1")
        e2 = chain_record(e1["sha"], 11, event="hook", client_id="c-1")
        e3 = chain_record(e2["sha"], 13, event="hook", client_id="c-1")  # honest gap
        self.assertTrue(Swarm.verify_export(None, {"events": [e1, e2, e3]}))

    def test_adjacent_splice_false(self):
        e1 = chain_record("", 10, event="signup", client_id="c-1")
        e2 = chain_record("f" * 64, 11, event="hook", client_id="c-1")  # wrong prev_sha
        self.assertFalse(Swarm.verify_export(None, {"events": [e1, e2]}))

    def test_tampered_payload_false(self):
        e1 = chain_record("", 10, event="signup", client_id="c-1")
        e1["client_id"] = "c-2"  # payload changed, sha stale
        self.assertFalse(Swarm.verify_export(None, {"events": [e1]}))

    def test_sequential_chain_true(self):
        """Raw-ledger form: no prev_sha field, base = previous record's sha."""
        _META = ("sha", "prev", "prev_sha", "index", "event_type")
        r1 = {"index": 1, "event": "a"}
        p1 = {k: v for k, v in r1.items() if k not in _META}
        r1["sha"] = hashlib.sha256(("" + json.dumps(p1, sort_keys=True)).encode()).hexdigest()
        r2 = {"index": 2, "event": "b"}
        p2 = {k: v for k, v in r2.items() if k not in _META}
        r2["sha"] = hashlib.sha256((r1["sha"] + json.dumps(p2, sort_keys=True)).encode()).hexdigest()
        self.assertTrue(Swarm.verify_export(None, {"events": [r1, r2]}))

    def test_empty_vacuously_true(self):
        self.assertTrue(Swarm.verify_export(None, {"events": []}))

    def test_malformed_shapes_raise(self):
        for bad in ([], {"events": {}}, "x", None):
            with self.assertRaises(SwarmError):
                Swarm.verify_export(None, bad)

    def test_missing_sha_false(self):
        self.assertFalse(Swarm.verify_export(None, {"events": [{"index": 1}]}))


# ----------------------------------------------------------------- verify
class TestVerify(StubCase):
    def test_verify_happy(self):
        self.srv.routes[("GET", "/v1/swarm/verify/abcdef1234")] = (
            200, {"chain_verified": True, "position": 3})
        r = self.sw().verify("abcdef1234")
        self.assertTrue(r["chain_verified"])

    def test_verify_404_not_found_dict(self):
        self.srv.routes[("GET", "/v1/swarm/verify/ffffffff")] = (404, {"error": "receipt not found"})
        r = self.sw().verify("ffffffff")
        self.assertEqual(r, {"chain_integrity": "NOT_FOUND"})

    def test_verify_short_prefix_guard(self):
        with self.assertRaises(SwarmError):
            self.sw().verify("abc")

    def test_verify_works_without_key_public(self):
        self.srv.routes[("GET", "/v1/swarm/verify/12345678")] = (
            200, {"chain_verified": True, "integrity_only": True})
        r = Swarm(api_key=None).verify("12345678")
        self.assertTrue(r["chain_verified"])
        self.assertNotIn("x-api-key", self.srv.hits[0][2])


# ------------------------------------------------------------------ proof
class TestProof(StubCase):
    RECEIPT = "a1b2c3d4e5f6"

    def inclusion(self, handler=None):
        return (200, {"position": 42, "receipt_sha": self.RECEIPT + "0" * 52,
                      "prev": "9" * 64,
                      "record": {"event": "hook", "client_id": "c-1", "index": 42},
                      "proof": "inclusion", "head_sha": "8" * 64, "head_count": 51,
                      "verify_hint": "anchor = head_sha at head_count"})

    def test_proof_happy_path_owner(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = self.inclusion
        r = self.sw().proof(self.RECEIPT)
        self.assertEqual(r["position"], 42)
        self.assertEqual(r["proof"], "inclusion")
        self.assertIn("receipt_sha", r)
        self.assertIn("prev", r)
        self.assertIn("record", r)
        self.assertIn("head_sha", r)
        self.assertIn("verify_hint", r)
        # the owner key rode the request, GET with no body:
        m, path, hdrs = self.srv.hits[0]
        self.assertEqual(m, "GET")
        self.assertEqual(hdrs.get("x-api-key"), "k-test-key")
        self.assertEqual(path, "/v1/swarm/proof/" + self.RECEIPT)

    def test_proof_missing_key_raises_before_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).proof(self.RECEIPT)
        self.assertEqual(self.wire(), [], "no key: nothing may leave the machine")

    def test_proof_401_maps_to_not_authorized(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = (
            401, {"error": "proof requires X-API-Key (owner)"})
        with self.assertRaises(SwarmNotAuthorized):
            self.sw().proof(self.RECEIPT)

    def test_proof_403_unknown_key_maps_to_not_authorized(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = (403, {"error": "unknown key"})
        with self.assertRaises(SwarmNotAuthorized):
            self.sw().proof(self.RECEIPT)

    def test_proof_not_found_passthrough(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = (
            200, {"chain_integrity": "NOT_FOUND", "head_count": 51})
        r = self.sw().proof(self.RECEIPT)
        self.assertEqual(r["chain_integrity"], "NOT_FOUND")
        self.assertEqual(r["head_count"], 51)

    def test_proof_short_prefix_guard(self):
        with self.assertRaises(SwarmError):
            self.sw().proof("abc")
        self.assertEqual(self.wire(), [])

    def test_proof_400_maps_to_swarm_error(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = (
            400, {"error": "receipt prefix must be >= 8 chars"})
        with self.assertRaises(SwarmError) as cm:
            self.sw().proof("x" * 8)
        self.assertIn("400", str(cm.exception))

    def test_proof_url_encodes_prefix(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = self.inclusion
        self.sw().proof("a b/c?d#e/")
        self.assertNotIn(" ", self.srv.hits[0][1])
        self.assertIn("%20", self.srv.hits[0][1])

    def test_proof_malformed_json_raises(self):
        self.srv.routes[("GET", "/v1/swarm/proof/*")] = (200, b"not json at all")
        with self.assertRaises(SwarmError):
            self.sw().proof(self.RECEIPT)


# ----------------------------------------------------------------- status
class TestStatus(StubCase):
    def test_status_happy(self):
        self.srv.routes[("GET", "/v1/swarm/status")] = (
            200, {"client_id": "c-1", "tier": "trial", "used_today": 3, "limit": 140})
        r = self.sw().status()
        self.assertEqual(r["limit"], 140)

    def test_status_401_maps(self):
        self.srv.routes[("GET", "/v1/swarm/status")] = (401, {"error": "no"})
        with self.assertRaises(SwarmNotAuthorized):
            self.sw().status()

    def test_status_without_key(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).status()


# -------------------------------------------------------------- redirect
def _hdr(req, name):
    """Case-insensitive request-header presence (urllib capitalization varies by version)."""
    return any(k.lower() == name for k in list(req.headers) + list(req.unredirected_hdrs))


class TestRedirectGuard(StubCase):
    def test_post_redirect_refused(self):
        def redir(handler):
            handler.send_response(302)
            handler.send_header("Location", "http://127.0.0.1:%d/moved" % handler.server.port)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return None
        h = StubHandler
        self.srv.routes[("POST", "/v1/swarm/answer")] = redir
        with self.assertRaises(SwarmError):
            self.sw().answer("Q", ["a", "b"])

    def test_redirect_guards_unit(self):
        import urllib.request as ur
        from email.message import Message
        h = client._SafeRedirect()
        # POST + 302 must be refused outright (no body smuggling across hops)
        post = ur.Request("https://api.example.com/v1/x", data=b"{}",
                          headers={"X-API-Key": "s"})
        with self.assertRaises(urllib.error.HTTPError):
            h.redirect_request(post, None, 302, "Found", Message(),
                               "https://api.example.com/v1/y")
        # cross-host GET redirect: followed, but the API key is stripped
        getreq = ur.Request("https://api.example.com/v1/x", headers={"X-API-Key": "s"})
        new = h.redirect_request(getreq, None, 302, "Found", Message(),
                                 "https://other.example.org/v1/x")
        self.assertIsNotNone(new)
        self.assertFalse(_hdr(new, "x-api-key"))
        # same-host redirect keeps the key
        same = h.redirect_request(getreq, None, 302, "Found", Message(),
                                  "https://api.example.com/v1/y")
        self.assertTrue(_hdr(same, "x-api-key"))


# ------------------------------------------------- swarm control plane (0.1.9)
AID = "agt_ab026178126b"
# Verdict-only gate response keys per the published contract (edge >= 1.8.7).
# Anything outside this allowlist on a gate reply is a leak: the no-leak test
# pins the response keys to exactly this set.
GATE_ALLOW = {"hook_verdict", "margin", "model", "evidence", "client_id", "agent_id",
              "flagged", "verdicts_seen", "flagged_count", "quota_used_today",
              "quota_limit", "trial_total_cap", "trial_expires", "receipt", "version"}


def gate_resp(verdict="proceed", flagged=False, seen=1, fc=0, used=1):
    return {"hook_verdict": verdict, "margin": 0.4898, "model": "phi2",
            "evidence": "verdict-only", "client_id": "c-1", "agent_id": AID,
            "flagged": flagged, "verdicts_seen": seen, "flagged_count": fc,
            "quota_used_today": used, "quota_limit": 140, "trial_total_cap": 500,
            "trial_expires": 9999, "receipt": "43" * 8, "version": "1.8.7"}


class TestAgentsRegister(StubCase):
    ROUTE = ("POST", "/v1/swarm/agents/register")

    def test_register_happy(self):
        self.srv.routes[self.ROUTE] = (
            200, {"ok": True, "client_id": "c-1", "agent_id": AID, "family": "phi-2",
                  "name_sha": "6794af8371f2", "n_agents": 1, "cap": 500,
                  "receipt": "ad" * 8, "version": "1.8.7"})
        r = self.sw().agents_register("scout-1", "phi-2")
        self.assertTrue(r["ok"])
        self.assertTrue(r["agent_id"].startswith("agt_"))
        self.assertEqual(r["cap"], 500)
        self.assertEqual(self.srv.hits[0][2].get("x-api-key"), "k-test-key")
        self.assertEqual(self.srv.last_body, {"name": "scout-1", "family": "phi-2"})

    def test_register_family_passthrough_no_local_validation(self):
        """The client must not pre-validate family: whatever the server accepts (or
        rejects) is the server's call — the exact string has to reach the wire."""
        self.srv.routes[self.ROUTE] = (
            200, {"ok": True, "client_id": "c-1", "agent_id": AID,
                  "family": "weird/FAMILY 9", "name_sha": "x" * 12, "n_agents": 1,
                  "cap": 500, "receipt": "ad" * 8, "version": "1.8.7"})
        r = self.sw().agents_register("odd", "weird/FAMILY 9")
        self.assertEqual(self.srv.last_body["family"], "weird/FAMILY 9")
        self.assertEqual(r["family"], "weird/FAMILY 9")

    def test_register_server_family_validation_error_passes_through(self):
        self.srv.routes[self.ROUTE] = (400, {"error": "unsupported family: qwen-9000"})
        with self.assertRaises(SwarmError) as cm:
            self.sw().agents_register("a", "qwen-9000")
        self.assertIn("unsupported family", str(cm.exception))

    def test_register_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).agents_register("a", "phi-2")
        self.assertEqual(self.wire(), [])


class TestAgentsList(StubCase):
    def test_list_owner_scoped_get_with_key(self):
        self.srv.routes[("GET", "/v1/swarm/agents")] = (
            200, {"product": "lens-swarm-1.8.7", "version": "1.8.7", "client_id": "c-1",
                  "count": 1, "cap": 500,
                  "agents": [{"agent_id": AID, "family": "phi-2", "verdicts_seen": 0,
                              "last_verdict": None, "flagged_count": 0}]})
        r = self.sw().agents_list()
        self.assertEqual(r["product"], "lens-swarm-1.8.7")
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["agents"][0]["agent_id"], AID)
        m, path, hdrs = self.srv.hits[0]
        self.assertEqual(m, "GET")
        self.assertEqual(path, "/v1/swarm/agents")
        self.assertEqual(hdrs.get("x-api-key"), "k-test-key")

    def test_list_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).agents_list()
        self.assertEqual(self.wire(), [])


class TestAgentsGate(StubCase):
    ROUTE = ("POST", "/v1/swarm/agents/gate")

    def test_gate_proceed_shape(self):
        self.srv.routes[self.ROUTE] = (200, gate_resp("proceed"))
        r = self.sw().agents_gate(AID, GOOD)
        self.assertEqual(r["hook_verdict"], "proceed")
        self.assertFalse(r["flagged"])
        self.assertEqual(self.srv.last_body["agent_id"], AID)
        self.assertEqual(self.srv.last_body["state"], GOOD)

    def test_gate_abstain_shape_with_counters_and_shared_quota(self):
        self.srv.routes[self.ROUTE] = (200, gate_resp("abstain", flagged=True, seen=2,
                                                      fc=1, used=3))
        r = self.sw().agents_gate(AID, GOOD)
        self.assertEqual(r["hook_verdict"], "abstain")
        self.assertEqual(r["verdicts_seen"], 2)
        self.assertEqual(r["flagged_count"], 1)
        self.assertTrue(r["flagged"])
        # gates draw on the shared daily quota, visible on the reply itself
        self.assertEqual(r["quota_used_today"], 3)
        self.assertEqual(r["quota_limit"], 140)

    def test_gate_response_respects_no_leak_key_allowlist(self):
        self.srv.routes[self.ROUTE] = (200, gate_resp("repair", flagged=True, seen=3,
                                                      fc=2, used=4))
        r = self.sw().agents_gate(AID, GOOD)
        self.assertLessEqual(set(r.keys()), GATE_ALLOW,
                             "gate reply carried keys outside the verdict-only contract")
        self.assertLessEqual(set(self.srv.last_body.keys()), {"agent_id", "state"},
                             "gate request must carry only agent_id and the user's state")

    def test_gate_invalid_verdict_rejected(self):
        bad = gate_resp("proceed")
        bad["hook_verdict"] = "maybe"
        self.srv.routes[self.ROUTE] = (200, bad)
        with self.assertRaises(SwarmError):
            self.sw().agents_gate(AID, GOOD)

    def _guard(self, agent_id, state):
        with self.assertRaises(SwarmError):
            self.sw().agents_gate(agent_id, state)
        self.assertEqual(self.wire(), [], "guard must not touch the wire")

    def test_gate_state_short_guard(self):
        self._guard(AID, [1.0] * 15)

    def test_gate_state_nan_guard(self):
        self._guard(AID, [float("nan")] + [1.0] * 15)

    def test_gate_empty_agent_id_guard(self):
        self._guard("", GOOD)

    def test_gate_401_without_server_key_maps_to_not_authorized(self):
        self.srv.routes[self.ROUTE] = (401, {"error": "missing key"})
        with self.assertRaises(SwarmNotAuthorized):
            self.sw(key="k-revoked").agents_gate(AID, GOOD)

    def test_gate_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).agents_gate(AID, GOOD)
        self.assertEqual(self.wire(), [])


class TestAgentsRemove(StubCase):
    def test_remove_happy(self):
        self.srv.routes[("POST", "/v1/swarm/agents/remove")] = (
            200, {"ok": True, "client_id": "c-1", "agent_id": AID, "n_agents": 0,
                  "cap": 500, "receipt": "b8" * 8, "version": "1.8.7"})
        r = self.sw().agents_remove(AID)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_agents"], 0)
        self.assertEqual(self.srv.last_body, {"agent_id": AID})

    def test_remove_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).agents_remove(AID)
        self.assertEqual(self.wire(), [])


class TestJudge(StubCase):
    ROUTE = ("POST", "/v1/swarm/judge")

    def test_judge_majority(self):
        self.srv.routes[self.ROUTE] = (
            200, {"product": "lens-swarm-judge-1.0", "client_id": "c-1",
                  "converged": True, "answer_index": 1, "leaning_index": 1,
                  "agreement": 0.6667, "n_agents": 3,
                  "dissent": [{"agent_id": "agt_c" * 4, "answer_index": 0}],
                  "tied_indices": [], "debias_offset": 1, "reason": "majority",
                  "n_votes": 3, "quota_used_today": 5, "quota_limit": 140,
                  "receipt": "41" * 8, "version": "1.8.7"})
        votes = [{"agent_id": AID, "answer_index": 1},
                 {"agent_id": "agt_b", "answer_index": 1},
                 {"agent_id": "agt_c" * 4, "answer_index": 0}]
        r = self.sw().judge("Is the sky blue?", ["no", "yes"], votes)
        self.assertEqual(r["product"], "lens-swarm-judge-1.0")
        self.assertTrue(r["converged"])
        self.assertEqual(r["answer_index"], 1)   # 2-of-3 majority
        self.assertEqual(r["n_votes"], 3)
        # wire contract: third field is "items", each item only {agent_id, answer_index}
        body = self.srv.last_body
        self.assertEqual(set(body.keys()), {"question", "choices", "items"})
        self.assertEqual(body["items"], [{"agent_id": AID, "answer_index": 1},
                                         {"agent_id": "agt_b", "answer_index": 1},
                                         {"agent_id": "agt_c" * 4, "answer_index": 0}])
        self.assertEqual(self.srv.hits[0][2].get("x-api-key"), "k-test-key")

    def test_judge_duplicate_agent_rejected_4xx(self):
        self.srv.routes[self.ROUTE] = (
            400, {"error": "duplicate agent_id in items", "item_index": 1, "agent_id": AID})
        with self.assertRaises(SwarmError) as cm:
            self.sw().judge("Q?", ["a", "b"],
                            [{"agent_id": AID, "answer_index": 0},
                             {"agent_id": AID, "answer_index": 1}])
        self.assertIn("duplicate agent_id", str(cm.exception))
        self.assertIn("400", str(cm.exception))

    def _guard(self, votes):
        with self.assertRaises(SwarmError):
            self.sw().judge("Q?", ["a", "b"], votes)
        self.assertEqual(self.wire(), [], "guard must not touch the wire")

    def test_judge_guard_empty_votes(self):
        self._guard([])

    def test_judge_guard_not_a_list(self):
        self._guard({"agent_id": AID, "answer_index": 0})

    def test_judge_guard_over_50_votes(self):
        self._guard([{"agent_id": "agt_%d" % i, "answer_index": 0} for i in range(51)])

    def test_judge_guard_missing_fields(self):
        self._guard([{"agent_id": AID}])

    def test_judge_guard_bool_answer_index(self):
        self._guard([{"agent_id": AID, "answer_index": True}])

    def test_judge_without_key_never_touches_wire(self):
        with self.assertRaises(SwarmNotAuthorized):
            Swarm(api_key=None).judge("Q?", ["a", "b"],
                                      [{"agent_id": AID, "answer_index": 0}])
        self.assertEqual(self.wire(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
