import argparse, json, sys
from .client import Swarm, SwarmError
def main():
    p = argparse.ArgumentParser(prog="palswarm", description="lens-swarm client (server-computed; signup required)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("signup"); s.add_argument("email")
    a = sub.add_parser("answer"); a.add_argument("question"); a.add_argument("choices", nargs="+"); a.add_argument("--k", type=int, default=5)
    h = sub.add_parser("health")
    args = p.parse_args()
    try:
        if args.cmd == "signup":
            sw = Swarm.signup(args.email)
            print("client_id:", sw.client_id); print("tier:", getattr(sw, "note", "trial"))
        elif args.cmd == "health":
            print(json.dumps(Swarm().health(), indent=1))
        else:
            sw = Swarm()
            r = sw.answer(args.question, args.choices, k=args.k)
            print("selected:", r["selected"], "| agreement:", r["agreement"], "| flag:", r["confidence_flag"])
            print("receipt:", r["receipt"], "| quota:", f"{r['quota_used_today']}/{r['quota_limit']}")
    except SwarmError as e:
        print(str(e), file=sys.stderr); sys.exit(2)
if __name__ == "__main__": main()
