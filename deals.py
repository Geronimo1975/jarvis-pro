"""DEALS bay — proposals, invoices, and quotes born from ONE sentence on ANY surface.

Born 2026-07-27 from a community ask ("AI agent that crafts a proposal or quote and texts
it — they click and see it online") reshaped by George: HE asks Jarvis — desk voice, the
hotline, a Telegram text, or a Telegram VOICE NOTE — and a polished PDF lands back on his
phone via Telegram, with a durable Google Drive link for the view-it-online part.

Pipeline: [DEAL:kind|brief] tag (CONTROL_HINT — fires from /chat, pocket, and the assist
extractor's hotline branch) → create_async() acks instantly → the config brain drafts
STRUCTURED content grounded in the vault (retrieve + memory — his real products, prices,
brand) → the AI Workshop editorial page (cream/ink/emerald, serif — the house design
system) → Chrome-headless PDF → Telegram sendDocument + Drive upload + an EDITABLE
Google Doc twin (same page, Drive HTML-conversion — he tweaks a price before sending) →
📄 desk card + ledger row (jarvis-deals.jsonl, also the invoice-number sequence).

Laws honoured: this bay only ever sends to HIS OWN paired Telegram and HIS OWN Drive —
nothing outward-facing, so no confirm gate (rule 4 covers email/social/production sends);
receipts come from the real APIs (Telegram ok / Drive webViewLink), never claimed; raw
ids stay on screen, the spoken line is butler-clean.
"""

import json, os, re, shutil, subprocess, threading, time

CTX = {}   # init(): cfg, root, call_model, mem_block, retrieve, raise_card, pocket_file, gsuite, log

LEDGER = "jarvis-deals.jsonl"

def _find_chrome():
    """A Chromium that can --print-to-pdf, wherever this brain lives. Mac path first
    (the proven default), then PATH, then the Windows homes — Edge included, since
    every Windows box ships it and it prints identically."""
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(mac):
        return mac
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    pf, pfx = os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")
    local = os.environ.get("LOCALAPPDATA", "")
    for p in (os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
              os.path.join(pfx, "Google", "Chrome", "Application", "chrome.exe"),
              os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
              os.path.join(pfx, "Microsoft", "Edge", "Application", "msedge.exe"),
              os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe")):
        if p and os.path.exists(p):
            return p
    return mac   # keep the old sentinel: exists() gates rendering downstream

CHROME = _find_chrome()
KINDS = ("proposal", "invoice", "quote")

def init(ctx):
    CTX.update(ctx or {})
    print("[deals] bay online — proposals/invoices/quotes to the phone")

def _ledger_path():
    return os.path.join(CTX.get("root", "."), LEDGER)

_SEQ_LOCK = threading.Lock()
_INFLIGHT = {}     # kind -> numbers claimed but not yet in the ledger (concurrent creates)

def _next_number(kind):
    """INV-2026-007 style — the ledger + in-flight reservations are the sequence. Two deals
    drafting at once (the extractor can fire two tags off one call) must never share a
    number or overwrite each other's file (audit 2026-07-27)."""
    n = 0
    try:
        with open(_ledger_path()) as f:
            for line in f:
                try:
                    if json.loads(line).get("kind") == kind: n += 1
                except Exception:
                    pass
    except Exception:
        pass
    with _SEQ_LOCK:
        n += _INFLIGHT.get(kind, 0)
        _INFLIGHT[kind] = _INFLIGHT.get(kind, 0) + 1
    return f"{kind[:3].upper()}-{time.strftime('%Y')}-{n + 1:03d}"

def _seq_release(kind):
    with _SEQ_LOCK:
        _INFLIGHT[kind] = max(0, _INFLIGHT.get(kind, 0) - 1)

def _ledger_add(row):
    try:
        with open(_ledger_path(), "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass
    _seq_release(row.get("kind", ""))

def _num(v, fb=0):
    """'$1,500' → 1500.0; '2 passes' → fb. The models write currency strings no matter what
    the schema says — arithmetic sites must never see raw model values (audit 2026-07-27)."""
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or fb)
    except Exception:
        m = re.search(r"-?\d[\d.]*", str(v or ""))
        try:
            return float(m.group(0)) if m else float(fb)
        except Exception:
            return float(fb)

# ---------- content: the config brain, grounded in HIS business ----------

def _biz():
    b = ((CTX.get("cfg") or {}).get("business") or {})
    return {"name": b.get("name") or "the user's company",
            "email": b.get("email") or "",
            "blurb": b.get("blurb") or "their products and services"}

def _deal_sys():
    b = _biz()
    return (
    f"You draft client-ready business documents for {b['name']} "
    f"({b['blurb']}). Use the BUSINESS CONTEXT for real product names and "
    "prices when the request implies them; NEVER invent client details beyond the brief. "
    "Return ONLY a JSON object, no prose, shaped exactly:\n"
    '{"title": "...", "client": "name or company from the brief (or \'Client\')", '
    '"intro": "2-3 sentence opening tailored to the request", '
    '"items": [{"desc": "...", "qty": 1, "unit_price": 0}], '
    '"total": 0, "terms": "payment/engagement terms in 1-2 sentences", '
    '"validity": "e.g. Valid 30 days / Due on receipt", '
    '"notes": "optional closing note or empty string"}\n'
    "Prices: use amounts from the brief verbatim; otherwise price sensibly from the business "
    "context. qty * unit_price must sum to total. Keep items to 2-6 lines. For a PROPOSAL, "
    "items are phases/deliverables; for an INVOICE, delivered work; for a QUOTE, the offer.")

def _content(kind, brief):
    ctx_notes = ""
    try:
        # server.retrieve returns (notes, top_score) — the calls.py:brain_answer convention.
        # Iterating the raw tuple silently killed ALL grounding (audit 2026-07-27: every deal
        # priced from thin air while the blanket except ate the AttributeError).
        hits = CTX["retrieve"](brief + " pricing products offer") or ([], 0)
        if isinstance(hits, tuple):
            hits = hits[0] or []
        ctx_notes = "\n".join(f"- {n.get('label')}: {(n.get('p') or '')[:200]}" for n in hits[:5])
    except Exception:
        pass
    mem = ""
    try:
        mem = CTX["mem_block"]() or ""
    except Exception:
        pass
    user = (f"Draft a {kind}.\nBRIEF: {brief}\n\nBUSINESS CONTEXT (real notes):\n"
            f"{ctx_notes or '(none)'}\n{mem[:1200]}")
    out, err = CTX["call_model"]([{"role": "user", "content": user}], _deal_sys(), 900)
    if err or not out:
        return None, err or "the drafting brain came back empty"
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, "the draft arrived shapeless"
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None, "the draft arrived malformed"
    d["items"] = [i for i in (d.get("items") or []) if isinstance(i, dict)][:8]
    # normalize ONCE so every downstream consumer sees clean numbers, then the total is OURS
    # whenever items exist — a zero-item-sum draft must never keep a model-invented total
    for i in d["items"]:
        i["qty"] = _num(i.get("qty"), 1) or 1
        i["unit_price"] = _num(i.get("unit_price"), 0)
    calc = round(sum(i["qty"] * i["unit_price"] for i in d["items"]), 2)
    if d["items"] and abs(calc - _num(d.get("total"), 0)) > 0.01:
        d["total"] = calc                        # arithmetic is ours, not the model's
    return d, None

# ---------- render: the AI Workshop editorial page (cream / ink / emerald) ----------

def _money(v):
    try:
        f = float(v)
        return "${:,.2f}".format(f).replace(".00", "") if f else "—"
    except Exception:
        return _esc(v)          # a non-numeric model value must never land as live HTML

def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))      # S23: attribute-safe too

def render_html(kind, number, d):
    today = time.strftime("%B %d, %Y")
    rows = "".join(
        f"<tr><td>{_esc(i.get('desc'))}</td><td class='n'>{_esc(i.get('qty') or 1)}</td>"
        f"<td class='n'>{_money(i.get('unit_price'))}</td>"
        f"<td class='n'>{_money(_num(i.get('qty'), 1) * _num(i.get('unit_price'), 0))}</td></tr>"
        for i in d.get("items") or [])
    notes = f"<p class='notes'>{_esc(d.get('notes'))}</p>" if (d.get("notes") or "").strip() else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_esc(d.get('title'))}</title>
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #F7F3EA; color: #16130D; font-family: Georgia, 'Times New Roman', serif;
         -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .page {{ padding: 64px 72px; min-height: 100vh; }}
  .eyebrow {{ font-family: -apple-system, Helvetica, sans-serif; font-size: 11px; letter-spacing: .28em;
             text-transform: uppercase; color: #0E6B4F; margin-bottom: 10px; }}
  h1 {{ font-size: 34px; font-weight: normal; font-style: italic; line-height: 1.15; margin-bottom: 6px; }}
  .meta {{ font-family: -apple-system, Helvetica, sans-serif; font-size: 12px; color: #6B6455;
          margin-bottom: 34px; }}
  .meta b {{ color: #16130D; font-weight: 600; }}
  .rule {{ height: 2px; background: #16130D; margin: 26px 0; }}
  .intro {{ font-size: 15px; line-height: 1.65; max-width: 58ch; margin-bottom: 30px; }}
  table {{ width: 100%; border-collapse: collapse; font-family: -apple-system, Helvetica, sans-serif;
          font-size: 13px; }}
  th {{ text-align: left; font-size: 10.5px; letter-spacing: .18em; text-transform: uppercase;
       color: #6B6455; padding: 0 10px 10px 0; border-bottom: 1.5px solid #16130D; }}
  td {{ padding: 12px 10px 12px 0; border-bottom: 1px solid #D9D2C2; line-height: 1.45; }}
  td.n, th.n {{ text-align: right; white-space: nowrap; }}
  .total td {{ border-bottom: none; padding-top: 18px; font-size: 16px; font-weight: 700; }}
  .total .lbl {{ font-size: 10.5px; letter-spacing: .18em; text-transform: uppercase; color: #0E6B4F; }}
  .terms {{ margin-top: 40px; font-size: 13px; line-height: 1.6; color: #3A3428; max-width: 60ch; }}
  .terms .h {{ font-family: -apple-system, Helvetica, sans-serif; font-size: 10.5px; letter-spacing: .18em;
              text-transform: uppercase; color: #0E6B4F; margin-bottom: 6px; }}
  .notes {{ margin-top: 18px; font-style: italic; font-size: 13.5px; color: #3A3428; }}
  .foot {{ margin-top: 56px; padding-top: 14px; border-top: 1px solid #D9D2C2;
          font-family: -apple-system, Helvetica, sans-serif; font-size: 10.5px; letter-spacing: .14em;
          text-transform: uppercase; color: #6B6455; display: flex; justify-content: space-between; }}
</style></head><body><div class="page">
  <div class="eyebrow">{_esc(_biz()["name"])} · {_esc(kind)}</div>
  <h1>{_esc(d.get('title'))}</h1>
  <div class="meta"><b>{_esc(number)}</b> · Prepared for <b>{_esc(d.get('client'))}</b> · {today}</div>
  <p class="intro">{_esc(d.get('intro'))}</p>
  <table>
    <tr><th>Description</th><th class="n">Qty</th><th class="n">Unit</th><th class="n">Amount</th></tr>
    {rows}
    <tr class="total"><td class="lbl">Total</td><td></td><td></td><td class="n">{_money(d.get('total'))}</td></tr>
  </table>
  <div class="terms"><div class="h">Terms</div>{_esc(d.get('terms'))} · {_esc(d.get('validity'))}</div>
  {notes}
  <div class="foot"><span>{_esc(_biz()["name"])}</span><span>{_esc(_biz()["email"])}</span></div>
</div></body></html>"""

def _pdf(html_path, pdf_path):
    if not os.path.exists(CHROME):
        return False
    try:
        try:
            from pathlib import Path
            url = Path(html_path).resolve().as_uri()   # windows drive letters need file:///C:/…
        except Exception:
            url = "file://" + html_path
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path}", url],
                       capture_output=True, timeout=75)
    except Exception:
        return False
    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1500

# ---------- client records: look FIRST, ask only when the records come up empty ----------
# (2026-07-28, his spec: "if I ask for a quote for someone, automatically look through my
# records; if the person isn't there, come back and ask for details or a general draft.")

PENDING_ASK = {}      # sid -> {ts, kind, client}: we asked once; his next [DEAL:] emission drafts
ASK_TTL = 600

def lookup_client(name):
    """A quick sweep of HIS OWN accounts (mail + Drive) for the named client. Returns a short
    context string for the drafting prompt, or None when the records are empty/unavailable."""
    gs = CTX.get("gsuite")
    if not (gs and gs.connected()):
        return None
    bits = []
    try:
        r = gs.search_mail('"%s"' % name.replace('"', ""), 3)
        for m in (r.get("messages") or [])[:3]:
            bits.append(f"email from {m.get('from')}: {m.get('subject')}")
    except Exception:
        pass
    try:
        if getattr(gs, "drive_ready", lambda: False)():
            r = gs.drive_search(name, 3)
            for f in (r.get("files") or [])[:2]:
                bits.append(f"drive file: {f.get('name')}")
    except Exception:
        pass
    return "; ".join(bits) or None

def prepare(kind, client, brief, sid=None):
    """Gate before drafting. Returns (action, payload, note):
    ("go", enriched_brief, note) — draft now; ("ask", question, "") — no draft, ask him first.
    The ask fires ONCE per conversation (PENDING_ASK): his answer arrives as a fresh [DEAL:]
    emission from the chat brain, which then drafts unconditionally. sid=None (the hotline
    extractor — no conversation to ask into) always drafts directly."""
    key = sid or ""
    client = (client or "").strip()
    pend = PENDING_ASK.get(key)
    if pend and time.time() - pend["ts"] < ASK_TTL:
        PENDING_ASK.pop(key, None)
        # he answered — draft now, and make sure the client NAME survives into the brief even
        # when the brain's second emission dropped it (live 2026-07-28: the ledger said "Client")
        c = client or pend.get("client") or ""
        if c and c.lower() not in brief.lower():
            brief = f"For client {c}: {brief}"
        return "go", brief, ""
    for k in [k for k, v in list(PENDING_ASK.items()) if time.time() - v["ts"] >= ASK_TTL]:
        PENDING_ASK.pop(k, None)
    if client and sid is not None:
        found = lookup_client(client)
        if found:
            lead = brief if client.lower() in brief.lower() else f"For client {client}: {brief}"
            return ("go", lead + "\nCLIENT RECORDS (from his own accounts — use what's relevant, "
                    "never invent beyond them): " + found[:600], "records")
        if (CTX.get("gsuite") and CTX["gsuite"].connected()):
            PENDING_ASK[key] = {"ts": time.time(), "kind": kind, "client": client}
            return ("ask", f"I looked through your records, sir — no {client} in your mail or "
                           f"Drive. Give me their details, or say the word and I'll draft the "
                           f"{kind or 'document'} with just the name.", "")
    return "go", brief, ""

# ---------- the pipeline ----------

def create(kind, brief, sid=None):
    """Synchronous full run. Returns (spoken_summary, err)."""
    kind = (kind or "").strip().lower()
    if kind in ("estimate", "bid"): kind = "quote"
    if kind not in KINDS:
        kind = "proposal"
    brief = (brief or "").strip()
    if len(brief) < 8:
        return None, "the brief is too thin — who is it for, and for what?"
    d, err = _content(kind, brief)
    if err:
        return None, err
    number = _next_number(kind)
    try:
        return _finish(kind, brief, number, d, sid)
    except Exception:
        _seq_release(kind)      # a crashed run must hand its reserved number back
        raise

def _finish(kind, brief, number, d, sid):
    slug = re.sub(r"[^a-z0-9]+", "-", (d.get("client") or kind).lower()).strip("-")[:32] or kind
    folder = os.path.join(CTX.get("root", "."), "deals")
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"{time.strftime('%Y-%m-%d')}-{number}-{slug}")
    html_path, pdf_path = base + ".html", base + ".pdf"
    html = render_html(kind, number, d)
    with open(html_path, "w") as f:
        f.write(html)
    have_pdf = _pdf(html_path, pdf_path)
    send_path = pdf_path if have_pdf else html_path
    fname = os.path.basename(send_path)
    mime = "application/pdf" if have_pdf else "text/html"
    with open(send_path, "rb") as f:
        blob = f.read()
    # Drive first (its link rides the Telegram caption)
    drive_link = ""
    gs = CTX.get("gsuite")
    if gs and getattr(gs, "drive_ready", lambda: False)():
        try:
            up = gs.drive_upload(fname, blob, mime)
            drive_link = (up or {}).get("link") or ""
        except Exception:
            pass
    # the editable twin (2026-07-28, his ask: "if I tell them to create an invoice, it uses
    # Google Docs"): the same editorial page lands as a REAL Google Doc so he can tweak a
    # price or a name before sending. Failure is silent-non-fatal — the PDF is the deliverable,
    # and the doc link is only ever spoken/shown when the API's own receipt carried it.
    doc_link = ""
    if gs and getattr(gs, "docs_ready", lambda: False)():
        try:
            dc = gs.doc_create(f"{number} — {d.get('client')}", html)
            doc_link = (dc or {}).get("link") or ""
        except Exception:
            pass
    caption = (f"{kind.capitalize()} {number} — {d.get('client')} · {_money(d.get('total'))}"
               + (f"\nView online: {drive_link}" if drive_link else "")
               + (f"\nEdit (Google Doc): {doc_link}" if doc_link else ""))
    sent = False
    pf = CTX.get("pocket_file")
    if pf:
        try:
            sent = bool(pf(blob, fname, mime, caption))
        except Exception:
            sent = False
    _ledger_add({"ts": int(time.time()), "kind": kind, "number": number,
                 "client": d.get("client"), "title": d.get("title"), "total": d.get("total"),
                 "file": send_path, "drive": drive_link, "doc": doc_link, "sent": sent,
                 "brief": brief[:200]})
    try:
        # a failed delivery is a HIGH card that speaks — a quiet receipt would let the [DEAL:]
        # ack's promise stand unchallenged (audit 2026-07-27)
        CTX["raise_card"]("notify", f"📄 {kind.capitalize()} {number} — {d.get('client')}",
                          f"{d.get('title')} · {_money(d.get('total'))}"
                          + (f" · Drive: {drive_link}" if drive_link else "")
                          + (f" · Doc: {doc_link}" if doc_link else "")
                          + (" · sent to your phone" if sent
                             else " · Telegram delivery FAILED — it's in the deals folder"),
                          source="deals", speak=(False if sent else None),
                          **({} if sent else {"priority": "high"}))
    except Exception:
        pass
    try:
        CTX["log"]("deal", f"{kind} {number} for {d.get('client')} — {_money(d.get('total'))}")
    except Exception:
        pass
    where = ("on your phone" if sent else "in the deals folder — Telegram delivery failed") \
            + (" and in your Drive" if drive_link else "") \
            + (" — with an editable Google Doc" if doc_link else "")
    return (f"The {kind} for {d.get('client')} is drafted, sir — {_money(d.get('total'))}, "
            f"{number}. It's {where}."), None

def recent_note(hours=48, n=3):
    """A context block of his freshest drafted deals — the TOOL brain once opened the leads
    sheet and asked WHO Mike Johnson was, twenty minutes after drafting his quote
    (2026-07-29). Operational context must ride every brain that acts for him."""
    rows = []
    try:
        cutoff = time.time() - hours * 3600
        for line in open(_ledger_path()).read().strip().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ts", 0) >= cutoff:
                rows.append(r)
    except Exception:
        return ""
    if not rows:
        return ""
    rows = rows[-n:]
    lines = "\n".join(
        f"- {r.get('number')} ({r.get('kind')}) for {r.get('client')} — ${r.get('total')} — "
        f"\"{r.get('title')}\" — {time.strftime('%b %d %I:%M %p', time.localtime(r.get('ts', 0)))}"
        + (" · delivered to his phone" if r.get("sent") else "")
        for r in rows)
    return ("\n\nRECENT DEALS he drafted (real, from the ledger — use these details when he "
            "references a client or document):\n" + lines)

def ledger_matches(query, n=5):
    """Ledger rows whose CLIENT name intersects the query's words — the AUTHORITATIVE numbers
    for 'tell me about Mike Johnson' (2026-07-29: the hotline stitched Mike + the oil shop +
    an unrelated $2,000 deal into one confident wrong answer)."""
    toks = {t for t in re.sub(r"[^a-z0-9 ]", " ", (query or "").lower()).split() if len(t) > 2}
    if not toks:
        return ""
    out = []
    try:
        for line in open(_ledger_path()).read().strip().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            ctoks = {t for t in re.sub(r"[^a-z0-9 ]", " ", str(r.get("client") or "").lower()).split()
                     if len(t) > 2}
            if ctoks & toks:
                out.append(f"- {r.get('number')} ({r.get('kind')}) for {r.get('client')} — "
                           f"${r.get('total')} — \"{r.get('title')}\""
                           + (" · delivered" if r.get("sent") else ""))
    except Exception:
        return ""
    if not out:
        return ""
    return ("DEALS LEDGER (authoritative — these amounts are the truth for this client):\n"
            + "\n".join(out[-n:]))

def create_async(kind, brief, sid=None):
    """Fire the pipeline in the background; the receipt arrives via Telegram + the desk card."""
    def run():
        say, err = (None, None)
        try:
            say, err = create(kind, brief, sid)
        except Exception as e:
            err = str(e)[:160]
        if err:
            try:
                CTX["raise_card"]("notify", "📄 Deal drafting FAILED",
                                  f"{kind}: {err}", source="deals", priority="high", speak=None)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()
