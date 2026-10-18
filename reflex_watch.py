#!/usr/bin/env python3
"""S25c · watch the reflex log while he speaks:  python3 reflex_watch.py   (Ctrl-C to stop)
One line per Jev call with the utterance, the distributions and which gates it crossed."""
import json, os, sys, time
import reflex as RX
LOG = RX.LOG_FILE
def fmt(r):
    t = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0))); a = r.get("answers") or {}; P = r.get("purpose")
    n = lambda k: float((a.get(k) or {}).get("noul") or 0)
    if P == "prepass":
        lane = a.get("lane") or {}; c = float(lane.get("confidence") or 0); ch = lane.get("choice") or "?"
        mode = ("partial" if r.get("partial") else "final") + (" filming" if r.get("recording") else "")
        need = RX.ADDRESSED_FILMING if r.get("recording") else RX.ADDRESSED_ROOM
        gates = []
        if c >= RX.LANE_ACT and ch != "none": gates.append("TRUST")
        elif ch == "vault_question" and c >= RX.LANE_PEEK: gates.append("peek")
        if c < RX.LANE_CLARIFY: gates.append("unsure")
        if n("complete") >= RX.COMPLETE_FIRE and c >= RX.LANE_ACT and n("destructive") < RX.DESTRUCTIVE_CONFIRM and ch not in ("none", "dial_now", "agent_task"): gates.append("FIRE")
        gates.append("ADDR" if n("addressed") >= need else "quiet")
        if n("destructive") >= RX.DESTRUCTIVE_CONFIRM: gates.append("CONFIRM")
        return f'{t} PREPASS {r["ms"]:4d}ms {mode:15s} "{(r.get("text") or "")[:70]}"  lane={ch} {c:.2f}  complete={n("complete"):.2f}  addressed={n("addressed"):.2f}  destr={n("destructive"):.2f}  urgent={n("urgent"):.2f}  → {" ".join(gates)}'
    if P == "recall":
        has = n("has"); ext = float((a.get("ext") or {}).get("score") or 0)
        v = "FOUND" if has >= RX.FOUND else ("absent" if has < RX.ABSENT else "unsure")
        kept = sum(1 for k, x in a.items() if k.startswith("n") and k[1:].isdigit() and float(x.get("noul") or 0) >= RX.NOTE_KEEP)
        return f'{t} RECALL  {r["ms"]:4d}ms {r.get("tokens",0):5d}tok "{(r.get("question") or "")[:60]}"  has={has:.2f} ext={ext:.2f} notes={r.get("n_notes","?")} keep≥{RX.NOTE_KEEP}={kept}  → {v}'
    if P == "judge":
        cl, bk = n("claims"), n("backed"); blocked = cl >= RX.CLAIM and bk < RX.BACKED
        return f'{t} JUDGE   {r["ms"]:4d}ms "{(r.get("answer") or "")[:70]}"  claims={cl:.2f} backed={bk:.2f} answers={n("answers"):.2f}  → {"BLOCKED" if blocked else "clean"}'
    if P == "triage":
        return f'{t} TRIAGE  {r["ms"]:4d}ms {r.get("tokens",0)}tok  {sum(1 for k in a if k.startswith("kind"))} cards'
    if P == "govern":
        return f'{t} GOVERN  {r["ms"]:4d}ms {r.get("tokens",0)}tok  "{(r.get("title") or "")[:60]}"  ' + " ".join(f"{k}={float(v.get('noul') or v.get('score') or 0):.2f}" for k, v in a.items() if isinstance(v, dict)) + f'  → old={r.get("old")} gov={r.get("gov")} {"AGREE" if r.get("old") == r.get("gov") else "DIFF"}'
    return f"{t} {P} {r.get('ms')}ms"
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    with open(LOG) as f:
        lines = f.readlines()
        for l in lines[-n:]:
            try: print(fmt(json.loads(l)))
            except Exception: pass
        print("— watching (Ctrl-C to stop) —", flush=True)
        while True:
            l = f.readline()
            if not l: time.sleep(0.25); continue
            try: print(fmt(json.loads(l)), flush=True)
            except Exception: pass
if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
