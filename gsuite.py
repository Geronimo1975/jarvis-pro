"""GSUITE bay — NATIVE Gmail + Google Calendar for Jarvis (direct REST, no MCP middleman).

Born 2026-07-27 after the Zapier email path proved too slow: every "check my email" rode
chat brain → Anthropic MCP connector → Zapier MCP → Google. This bay talks straight to
Google's REST APIs with the user's own OAuth token (tools.py armory, kind "google" —
gmail + gcal tiles share one consent/token; see tools.GOOGLE_SCOPES).

Two consumers:
  1. tools.chat() attaches NATIVE_TOOLS (Anthropic custom tools) and calls execute()
     locally in its loop — email/calendar asks skip the MCP round-trip entirely.
  2. Deterministic fast paths call the helpers directly (calls.py briefing tier-1,
     assist.py prep cards, the booking→calendar follow-through) — no LLM in the fetch.

Laws honoured: raw ids/JSON are SCREEN-ONLY (speech rides speakable()/_SPEAK_JUNK
downstream — this bay returns compact human strings plus ids in separate fields);
never claim a write succeeded without the API's own receipt (we return the draft/event
id the API gave us, or an error field — the tool brain's RECEIPTS rule does the rest).
"""

import base64, datetime, json, os, re, urllib.error, urllib.parse, urllib.request
from email.mime.text import MIMEText

CTX = {}          # init() fills: cfg, root, access_token(fn tid->bearer|None), raise_card

GMAIL = "https://gmail.googleapis.com/gmail/v1"
GCAL = "https://www.googleapis.com/calendar/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3"
DRIVE_UP = "https://www.googleapis.com/upload/drive/v3/files"

def init(ctx):
    CTX.update(ctx or {})
    print("[gsuite] native Gmail + Calendar bay online" if connected()
          else "[gsuite] bay loaded — Google not connected yet (armory gmail tile)")

def token():
    """First live bearer across the Google tiles — ONE consent mints ONE token carrying every
    granted scope, so any surviving row's bearer serves all granted services. (Audit
    2026-07-28 night: hardcoding 'gmail' bricked the whole bay when a per-scope consent
    left the Gmail boxes unchecked — calendar/sheets/drive/docs showed connected but dead.)"""
    fn = CTX.get("access_token")
    if not fn: return None
    for tid in ("gmail", "gcal", "gsheets", "gdrive", "gdocs"):
        try:
            tok = fn(tid)
            if tok: return tok
        except Exception:
            continue
    return None

def connected():
    return token() is not None

def _has(tid):
    """A capability exists only when the armory holds its tile row — the shared token predates
    the Sheets/Drive scopes on older consents, and a tool that 403s on scope reads as broken."""
    fn = CTX.get("access_token")
    if not fn: return False
    try: return fn(tid) is not None
    except Exception: return False

def sheets_ready(): return _has("gsheets")
def drive_ready(): return _has("gdrive")
def docs_ready(): return _has("gdocs")     # Docs ride the drive scope (create = Drive convert,
                                           # read = Drive export) — the tile mirrors gdrive

# ---------- tiny HTTP (mirrors tools.http_json, but bearer'd and query-friendly) ----------

def _api(method, url, params=None, body=None, timeout=20):
    """Returns (status, parsed-json-or-text). Never raises."""
    tok = token()
    if not tok: return 0, {"error": "google not connected"}
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try: return r.status, (json.loads(raw) if raw else {})
            except Exception: return r.status, {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")[:400]
        try: parsed = json.loads(raw)
        except Exception: parsed = {"error": raw or ("HTTP %d" % e.code)}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)[:200]}

def _err(st, d):
    m = d.get("error") if isinstance(d, dict) else None
    if isinstance(m, dict): m = m.get("message") or json.dumps(m)[:120]
    return "google api %s: %s" % (st or "unreachable", (m or "no detail")[:160])

# ---------- Gmail ----------

def _hdr(msg, name):
    for h in (msg.get("payload") or {}).get("headers", []):
        if h.get("name", "").lower() == name.lower(): return h.get("value", "")
    return ""

def _msg_meta_full(mid):
    # subject arrives via the metadataHeaders list — ask for each header explicitly
    st, d = _api("GET", "%s/users/me/messages/%s" % (GMAIL, mid),
                 params=[("format", "metadata"), ("metadataHeaders", "From"),
                         ("metadataHeaders", "Subject"), ("metadataHeaders", "Date"),
                         ("fields", "id,threadId,snippet,payload/headers,internalDate")])
    if st != 200: return None
    frm = _hdr(d, "From")
    frm = re.sub(r"\s*<[^>]*>", "", frm).strip().strip('"') or frm
    return {"id": d.get("id", mid), "thread_id": d.get("threadId", ""), "from": frm,
            "subject": _hdr(d, "Subject") or "(no subject)",
            "snippet": (d.get("snippet") or "").strip()[:160]}

def search_mail(q, maxn=8):
    """List messages matching a Gmail query. Returns {"count", "messages":[{id,from,subject,snippet}]}."""
    st, d = _api("GET", GMAIL + "/users/me/messages",
                 params={"q": q, "maxResults": max(1, min(int(maxn or 8), 20))})
    if st != 200: return {"error": _err(st, d)}
    rows = []
    for m in (d.get("messages") or []):
        meta = _msg_meta_full(m["id"])
        if meta: rows.append(meta)
    return {"count": len(rows), "query": q, "messages": rows}

def unread(maxn=8):
    """Unread PRIMARY inbox (the standing EMAIL RULE: never Promotions/Social/spam)."""
    return search_mail("in:inbox is:unread category:primary", maxn)

def _walk_text(part, want="text/plain"):
    if not isinstance(part, dict): return ""
    if part.get("mimeType") == want and (part.get("body") or {}).get("data"):
        try:
            return base64.urlsafe_b64decode(part["body"]["data"] + "===").decode(errors="ignore")
        except Exception:
            return ""
    for p in (part.get("parts") or []):
        t = _walk_text(p, want)
        if t: return t
    return ""

def read_mail(mid):
    """Full body of one message (plain text preferred, HTML stripped as fallback)."""
    st, d = _api("GET", "%s/users/me/messages/%s" % (GMAIL, mid), params={"format": "full"})
    if st != 200: return {"error": _err(st, d)}
    pay = d.get("payload") or {}
    body = _walk_text(pay, "text/plain")
    if not body:
        html = _walk_text(pay, "text/html")
        body = re.sub(r"<style.*?</style>|<script.*?</script>", " ", html, flags=re.S | re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"&nbsp;?", " ", body)
    body = re.sub(r"[ \t]+", " ", body or "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return {"id": d.get("id", mid), "thread_id": d.get("threadId", ""),
            "from": _hdr(d, "From"), "to": _hdr(d, "To"), "date": _hdr(d, "Date"),
            "subject": _hdr(d, "Subject") or "(no subject)", "body": body[:4000]}

def draft(to, subject, body_text, reply_to_id=None):
    """Create a Gmail DRAFT (never sends). Returns the draft id as the receipt."""
    m = MIMEText(body_text or "", "plain", "utf-8")
    m["To"] = to or ""
    m["Subject"] = subject or ""
    payload = {}
    if reply_to_id:
        ref = read_mail(reply_to_id)
        if not ref.get("error"):
            payload["threadId"] = ref.get("thread_id") or None
            msgid = ""
            st, full = _api("GET", "%s/users/me/messages/%s" % (GMAIL, reply_to_id),
                            params=[("format", "metadata"), ("metadataHeaders", "Message-ID")])
            if st == 200: msgid = _hdr(full, "Message-ID")
            if msgid:
                m["In-Reply-To"] = msgid
                m["References"] = msgid
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    body = {"message": {"raw": raw}}
    if payload.get("threadId"): body["message"]["threadId"] = payload["threadId"]
    st, d = _api("POST", GMAIL + "/users/me/drafts", body=body)
    if st != 200: return {"error": _err(st, d)}
    return {"draft_id": d.get("id", ""), "to": to, "subject": subject, "status": "draft created"}

# ---------- Calendar ----------

def _now_local():
    return datetime.datetime.now().astimezone()

def _day_bounds(day=None, days=1):
    """day: None/'today' | 'tomorrow' | 'YYYY-MM-DD'. Returns (timeMin, timeMax) RFC3339."""
    base = _now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    d = (day or "today").strip().lower()
    if d == "tomorrow":
        base += datetime.timedelta(days=1)
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        base = base.replace(year=int(d[:4]), month=int(d[5:7]), day=int(d[8:10]))
    end = base + datetime.timedelta(days=max(1, min(int(days or 1), 31)))
    return base.isoformat(), end.isoformat()

def _fmt_when(ev):
    s = (ev.get("start") or {})
    if s.get("date"): return s["date"] + " (all day)"
    t = s.get("dateTime", "")
    try:
        # py3.9 fromisoformat can't read a 'Z' suffix — normalize, and show LOCAL time
        dt = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%a %b %-d, %-I:%M %p")
    except Exception:
        return t

def events(day=None, days=1, maxn=15):
    """Events on the PRIMARY calendar for a day (or a span of days)."""
    tmin, tmax = _day_bounds(day, days)
    st, d = _api("GET", GCAL + "/calendars/primary/events",
                 params={"timeMin": tmin, "timeMax": tmax, "singleEvents": "true",
                         "orderBy": "startTime", "maxResults": max(1, min(int(maxn or 15), 50))})
    if st != 200: return {"error": _err(st, d)}
    rows = []
    for ev in (d.get("items") or []):
        if ev.get("status") == "cancelled": continue
        rows.append({"id": ev.get("id", ""), "title": ev.get("summary") or "(untitled)",
                     "when": _fmt_when(ev), "start": (ev.get("start") or {}).get("dateTime")
                                                     or (ev.get("start") or {}).get("date", ""),
                     "location": (ev.get("location") or "")[:80]})
    return {"count": len(rows), "day": (day or "today"), "events": rows}

def quick_add(text):
    """Natural-language event on the PRIMARY calendar ('dinner with Sam Friday 7pm')."""
    st, d = _api("POST", GCAL + "/calendars/primary/events/quickAdd",
                 params={"text": (text or "").strip()[:300]})
    if st != 200: return {"error": _err(st, d)}
    return {"event_id": d.get("id", ""), "title": d.get("summary") or text,
            "when": _fmt_when(d), "status": "event created"}

def _find_event(query, days=2):
    """Today+tomorrow event whose title matches the query tokens. Returns (event_row, err)."""
    ev = events("today", days, 25)
    if ev.get("error"): return None, ev["error"]
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", (query or "").lower()).split() if len(t) > 2]
    best, score = None, 0
    for e in ev.get("events") or []:
        title = (e.get("title") or "").lower()
        s = sum(1 for t in toks if t in title)
        if s > score:
            best, score = e, s
    if not best:
        return None, f"no event today or tomorrow matching '{query}'"
    return best, None

def _parse_move_time(t, base_start):
    """'8 pm' / '8:30pm tonight' / 'tomorrow at 7 pm' → aware datetime anchored on the event's
    own date (tomorrow shifts a day). Returns None when no clean time is present."""
    tl = (t or "").lower()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", tl)
    if not m: return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").replace(".", "")
    if ap.startswith("p") and h < 12: h += 12
    if ap.startswith("a") and h == 12: h = 0
    if not ap and h < 8: h += 12                    # a bare "7" for dinner means evening
    day = base_start + datetime.timedelta(days=1) if "tomorrow" in tl else base_start
    return day.replace(hour=h, minute=mi, second=0, microsecond=0)

def event_move(query, new_time):
    """Move a calendar event found by title to a new time, keeping its duration.
    THE receipt is Google's own updated start ('change the dinner to 8pm', 2026-07-29)."""
    row, err = _find_event(query)
    if err: return {"error": err}
    st, full = _api("GET", f"{GCAL}/calendars/primary/events/{row['id']}")
    if st != 200: return {"error": _err(st, full)}
    s_raw = (full.get("start") or {}).get("dateTime")
    e_raw = (full.get("end") or {}).get("dateTime")
    if not s_raw:
        return {"error": "that's an all-day event — set a time by recreating it"}
    start = datetime.datetime.fromisoformat(s_raw.replace("Z", "+00:00")).astimezone()
    end = datetime.datetime.fromisoformat((e_raw or s_raw).replace("Z", "+00:00")).astimezone()
    new_start = _parse_move_time(new_time, start)
    if not new_start:
        return {"error": f"I couldn't read a time out of '{new_time}'"}
    new_end = new_start + (end - start)
    st, d = _api("PATCH", f"{GCAL}/calendars/primary/events/{row['id']}",
                 body={"start": {"dateTime": new_start.isoformat()},
                       "end": {"dateTime": new_end.isoformat()}})
    if st != 200: return {"error": _err(st, d)}
    return {"event_id": row["id"], "title": row.get("title"),
            "when": _fmt_when(d), "status": "event moved"}

def event_delete(query):
    """Delete a calendar event found by title. Returns the receipt."""
    row, err = _find_event(query)
    if err: return {"error": err}
    st, d = _api("DELETE", f"{GCAL}/calendars/primary/events/{row['id']}")
    if st not in (200, 204): return {"error": _err(st, d)}
    return {"event_id": row["id"], "title": row.get("title"), "status": "event deleted"}

# ---------- Drive ----------

def drive_search(q, maxn=10):
    """Find files by name fragment. Returns rows with the webViewLink (the 'open it online' URL)."""
    esc = (q or "").replace("\\", "").replace("'", "\\'").strip()
    st, d = _api("GET", DRIVE + "/files",
                 params={"q": f"name contains '{esc}' and trashed=false",
                         "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
                         "pageSize": max(1, min(int(maxn or 10), 25)),
                         "orderBy": "modifiedTime desc"})
    if st != 200: return {"error": _err(st, d)}
    rows = [{"id": f.get("id", ""), "name": f.get("name", ""),
             "kind": (f.get("mimeType", "").rsplit(".", 1)[-1] or "file")[:24],
             "link": f.get("webViewLink", ""), "modified": (f.get("modifiedTime") or "")[:10]}
            for f in (d.get("files") or [])]
    return {"count": len(rows), "query": q, "files": rows}

def drive_upload(name, content, mime="application/pdf", folder_id=None, convert_to=None):
    """Multipart upload. content = bytes or str. Returns id + webViewLink as the receipt.
    convert_to: a google-apps mimeType makes Drive CONVERT on ingest (html → Google Doc)."""
    blob = content if isinstance(content, bytes) else (content or "").encode()
    meta = {"name": (name or "file")[:120]}
    if folder_id: meta["parents"] = [folder_id]
    if convert_to: meta["mimeType"] = convert_to
    bound = "----jarvisdrive" + os.urandom(8).hex()
    body = (f"--{bound}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n--{bound}\r\nContent-Type: {mime}\r\n\r\n").encode() \
           + blob + f"\r\n--{bound}--\r\n".encode()
    tok = token()
    if not tok: return {"error": "google not connected"}
    req = urllib.request.Request(DRIVE_UP + "?uploadType=multipart&fields=id,name,webViewLink",
                                 data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": f"multipart/related; boundary={bound}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        return {"id": d.get("id", ""), "name": d.get("name", name),
                "link": d.get("webViewLink", ""), "status": "uploaded"}
    except urllib.error.HTTPError as e:
        return {"error": "google api %s: %s" % (e.code, e.read().decode(errors="ignore")[:160])}
    except Exception as e:
        return {"error": str(e)[:200]}

# ---------- Docs (no Docs API needed: create = Drive HTML-conversion, read = Drive export —
# both ride the drive scope already granted, so older consents light up without re-consent) ----------

GDOC_MIME = "application/vnd.google-apps.document"

def _wrap_html(content):
    """Plain text arrives tag-less; Drive's HTML import would collapse its line breaks.
    Wrap bare paragraphs in <p> — real HTML passes through untouched."""
    c = (content or "").strip()
    if re.search(r"</?(?:h[1-6]|p|ul|ol|li|table|thead|tbody|tr|td|th|div|br|hr|b|i|u|em|"
                 r"strong|span|a|img|blockquote|pre|code)\b[^>]*>", c, re.I):
        return c
    paras = [p.strip() for p in re.split(r"\n\s*\n", c) if p.strip()]
    return "".join("<p>%s</p>" % p.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace("\n", "<br>") for p in paras) or "<p></p>"

def doc_create(title, content):
    """New Google Doc from HTML (or plain text). Returns id + webViewLink as the receipt."""
    up = drive_upload(title or "Untitled document", _wrap_html(content),
                      mime="text/html", convert_to=GDOC_MIME)
    if up.get("error"): return up
    return {"doc_id": up.get("id", ""), "title": up.get("name", title),
            "link": up.get("link", ""), "status": "doc created"}

def _find_doc(doc):
    """Accepts a Doc id OR a spoken name ('the pricing doc') → id, or (None, err)."""
    s = (doc or "").strip()
    if _ID_RE.match(s): return s, None
    esc = s.replace("\\", "").replace("'", "\\'")
    st, d = _api("GET", DRIVE + "/files",
                 params={"q": f"name contains '{esc}' and trashed=false and mimeType='{GDOC_MIME}'",
                         "fields": "files(id,name)", "pageSize": 3, "orderBy": "modifiedTime desc"})
    if st != 200: return None, _err(st, d)
    files = d.get("files") or []
    if not files: return None, f"no Google Doc named anything like '{s}'"
    return files[0]["id"], None

def doc_read(doc):
    """Full text of one Google Doc (by name or id) via Drive's plain-text export."""
    did, err = _find_doc(doc)
    if err: return {"error": err}
    tok = token()
    if not tok: return {"error": "google not connected"}
    url = f"{DRIVE}/files/{did}/export?mimeType=text%2Fplain"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return {"error": "google api %s: %s" % (e.code, e.read().decode(errors="ignore")[:160])}
    except Exception as e:
        return {"error": str(e)[:200]}
    body = re.sub(r"\n{3,}", "\n\n", body.replace("\r", "")).strip()
    return {"doc_id": did, "body": body[:6000]}

def doc_pdf(doc):
    """One Google Doc (by name or id) exported as PDF. Returns ((blob, filename), err) —
    the Telegram line's courier fetch (a Doc has no local file to push, so Drive renders it)."""
    did, err = _find_doc(doc)
    if err: return None, err
    tok = token()
    if not tok: return None, "google not connected"
    st, meta = _api("GET", DRIVE + "/files/" + did, params={"fields": "name"})
    fname = (((meta or {}).get("name") or "document")[:80]) + ".pdf"
    req = urllib.request.Request(DRIVE + "/files/" + did + "/export?mimeType=application%2Fpdf",
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return (r.read(), fname), None
    except urllib.error.HTTPError as e:
        return None, "google api %s: %s" % (e.code, e.read().decode(errors="ignore")[:160])
    except Exception as e:
        return None, str(e)[:200]

# ---------- Sheets ----------

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{40,}$")   # real ids run ~44 chars; a 25-char threshold
                                               # ate hyphenated sheet NAMES (audit 2026-07-27)

def _find_sheet(sheet):
    """Accepts a spreadsheet id OR a spoken name ('the leads sheet') → id, or (None, err)."""
    s = (sheet or "").strip()
    if _ID_RE.match(s): return s, None
    esc = s.replace("\\", "").replace("'", "\\'")
    st, d = _api("GET", DRIVE + "/files",
                 params={"q": (f"name contains '{esc}' and trashed=false and "
                               "mimeType='application/vnd.google-apps.spreadsheet'"),
                         "fields": "files(id,name)", "pageSize": 3, "orderBy": "modifiedTime desc"})
    if st != 200: return None, _err(st, d)
    files = d.get("files") or []
    if not files: return None, f"no spreadsheet named anything like '{s}'"
    return files[0]["id"], None

def sheet_read(sheet, rng="A1:Z50"):
    """Read a range (default the top of the first tab). sheet = id or name."""
    sid, err = _find_sheet(sheet)
    if err: return {"error": err}
    st, d = _api("GET", "%s/%s/values/%s" % (SHEETS, sid, urllib.parse.quote(rng, safe="!:")))
    if st != 200: return {"error": _err(st, d)}
    vals = d.get("values") or []
    return {"sheet_id": sid, "range": d.get("range", rng), "rows": len(vals), "values": vals[:60]}

def sheet_append(sheet, values):
    """Append ONE row (list of cell strings) — or several (list of lists). Returns the receipt."""
    sid, err = _find_sheet(sheet)
    if err: return {"error": err}
    rows = values if (values and isinstance(values[0], list)) else [values]
    rows = [[str(c) for c in r][:26] for r in rows][:20]
    st, d = _api("POST", "%s/%s/values/A1:append?valueInputOption=USER_ENTERED" % (SHEETS, sid),
                 body={"values": rows})
    if st != 200: return {"error": _err(st, d)}
    up = (d.get("updates") or {})
    return {"sheet_id": sid, "appended_rows": up.get("updatedRows", len(rows)),
            "where": up.get("updatedRange", ""), "status": "appended"}

def sheet_update(sheet, rng, values):
    """Write values into a RANGE (overwrites those cells — 2026-07-29, his leads flow: a
    gathered email lands in an existing lead's blank cell, never a duplicate appended row).
    values = one row (list) or several (list of lists). Returns Google's own receipt."""
    sid, err = _find_sheet(sheet)
    if err: return {"error": err}
    rows = values if (values and isinstance(values[0], list)) else [values]
    rows = [[str(c) for c in r][:26] for r in rows][:50]
    st, d = _api("PUT", "%s/%s/values/%s" % (SHEETS, sid, urllib.parse.quote(rng, safe="!:")),
                 params={"valueInputOption": "USER_ENTERED"}, body={"values": rows})
    if st != 200: return {"error": _err(st, d)}
    return {"sheet_id": sid, "updated": d.get("updatedRange", rng),
            "cells": d.get("updatedCells", 0), "status": "updated"}

def sheet_create(title, header=None):
    """Create a new spreadsheet (optional header row). Returns id + URL as the receipt."""
    st, d = _api("POST", SHEETS, body={"properties": {"title": (title or "Untitled")[:100]}})
    if st != 200: return {"error": _err(st, d)}
    sid = d.get("spreadsheetId", "")
    if header:
        sheet_append(sid, [str(h) for h in header])
    return {"sheet_id": sid, "title": title, "url": d.get("spreadsheetUrl", ""), "status": "created"}

# ---------- the deterministic briefing fetch (no LLM, two round-trips, ~1s) ----------

def brief_pack():
    """{"events": [...], "unread": [...]} for tier-1 briefings and prep cards."""
    if not connected(): return None
    ev, un = events("today", 1, 10), unread(6)
    if ev.get("error") and un.get("error"): return None
    return {"events": ev.get("events") or [], "unread": un.get("messages") or [],
            "events_err": ev.get("error"), "unread_err": un.get("error")}

# ---------- native tools for the fast brain (tools.chat attaches these) ----------

NATIVE_TOOLS = [
    {"name": "gmail_unread", "description":
        "List unread emails in the Gmail PRIMARY inbox (never Promotions/Social/spam). "
        "THE tool for 'check my email / any new mail'. Fast native call.",
     "input_schema": {"type": "object", "properties": {
         "max": {"type": "integer", "description": "max messages, default 8"}}}},
    {"name": "gmail_search", "description":
        "Search Gmail with a query (Gmail syntax: from:, subject:, newer_than:2d, "
        "category:primary...). Returns sender/subject/snippet per hit.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "max": {"type": "integer"}}, "required": ["query"]}},
    {"name": "gmail_read", "description":
        "Read ONE email's full body by id (ids come from gmail_unread/gmail_search).",
     "input_schema": {"type": "object", "properties": {
         "id": {"type": "string"}}, "required": ["id"]}},
    {"name": "gmail_draft", "description":
        "Create a DRAFT email (never sends). Optional reply_to_id threads it as a reply. "
        "Returns the draft id as the receipt.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string"}, "subject": {"type": "string"},
         "body": {"type": "string"}, "reply_to_id": {"type": "string"}},
         "required": ["to", "subject", "body"]}},
    {"name": "gcal_events", "description":
        "Events on the PRIMARY Google Calendar. day: 'today' (default), 'tomorrow', or "
        "YYYY-MM-DD; days: span length (7 = the week ahead). THE tool for 'what's on my calendar'.",
     "input_schema": {"type": "object", "properties": {
         "day": {"type": "string"}, "days": {"type": "integer"}}}},
    {"name": "gcal_add", "description":
        "Add an event to the PRIMARY calendar from natural language "
        "('lunch with Ali tomorrow 1pm'). Returns the event id as the receipt.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"]}},
    {"name": "gcal_move", "description":
        "MOVE an existing calendar event (found by words from its title) to a new time, "
        "keeping its length. THE tool for 'change the dinner to 8pm', 'move the reservation "
        "to tomorrow at 7'. Returns Google's updated time as the receipt.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "words from the event's title"},
         "new_time": {"type": "string", "description": "e.g. '8 pm', 'tomorrow at 7:30 pm'"}},
         "required": ["query", "new_time"]}},
    {"name": "gcal_delete", "description":
        "Delete a calendar event found by words from its title. THE tool for 'take the 7pm "
        "reservation off my calendar', 'delete the duplicate dinner event'.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
]

SHEETS_TOOLS = [
    {"name": "gsheet_read", "description":
        "Read a Google Sheet by NAME or id (default range A1:Z50). THE tool for 'what's in my "
        "leads sheet', 'read the pricing spreadsheet'.",
     "input_schema": {"type": "object", "properties": {
         "sheet": {"type": "string", "description": "spreadsheet name fragment or id"},
         "range": {"type": "string", "description": "A1 notation, optional"}}, "required": ["sheet"]}},
    {"name": "gsheet_append", "description":
        "Append ONE row to a Google Sheet (by name or id). values = the cells left-to-right. "
        "THE tool for 'add X to my leads sheet', 'log this in the tracker'.",
     "input_schema": {"type": "object", "properties": {
         "sheet": {"type": "string"},
         "values": {"type": "array", "items": {"type": "string"}}}, "required": ["sheet", "values"]}},
    {"name": "gsheet_update", "description":
        "OVERWRITE specific cells in a Google Sheet (by name or id) at an A1 range — THE tool "
        "for filling a blank cell in an EXISTING row ('put Mike's email in I7', 'update the "
        "status column for row 3'). Read the sheet first to find the right row; appending a "
        "duplicate row when a cell update was meant is a failure.",
     "input_schema": {"type": "object", "properties": {
         "sheet": {"type": "string"}, "range": {"type": "string", "description": "A1 notation, e.g. I7 or C3:D3"},
         "values": {"type": "array", "items": {"type": "string"}}},
         "required": ["sheet", "range", "values"]}},
    {"name": "gsheet_create", "description":
        "Create a NEW Google Sheet (optional header row). Returns its URL as the receipt. "
        "Sheets are for TABULAR data — a full document (resume, letter, proposal) rides "
        "gdoc_create instead, even if the user says 'sheet' loosely.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "header": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]}},
]
DRIVE_TOOLS = [
    {"name": "gdrive_search", "description":
        "Find files in Google Drive by name fragment — returns each file's open-online link. "
        "THE tool for 'find my pricing doc in Drive'.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "gdrive_upload", "description":
        "Save a text/markdown/html file into Google Drive. Returns the shareable webViewLink "
        "as the receipt.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "content": {"type": "string"},
         "mime": {"type": "string", "description": "default text/plain"}},
         "required": ["name", "content"]}},
]

DOCS_TOOLS = [
    {"name": "gdoc_create", "description":
        "Create a NEW Google Doc (editable, in Drive). content = the document body as simple "
        "HTML (<h1>, <p>, <ul>, <table>) or plain text. THE tool for 'make a google doc of X', "
        "'put this in a doc'. Returns the doc's open-online link as the receipt.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "content": {"type": "string"}},
         "required": ["title", "content"]}},
    {"name": "gdoc_read", "description":
        "Read a Google Doc's full text by NAME or id. THE tool for 'what does my planning "
        "doc say', 'read me the onboarding doc'.",
     "input_schema": {"type": "object", "properties": {
         "doc": {"type": "string", "description": "doc name fragment or id"}}, "required": ["doc"]}},
]

def native_tools():
    """The attachable tool list, gated per capability (older consents lack Sheets/Drive)."""
    out = list(NATIVE_TOOLS)
    if sheets_ready(): out += SHEETS_TOOLS
    if docs_ready(): out += DOCS_TOOLS
    if drive_ready(): out += DRIVE_TOOLS
    return out

def native_names():
    return [t["name"] for t in NATIVE_TOOLS + SHEETS_TOOLS + DOCS_TOOLS + DRIVE_TOOLS]

def execute(name, args):
    """Run one native tool. Returns (result_dict, is_error). Never raises."""
    a = args or {}
    try:
        if name == "gmail_unread":  out = unread(a.get("max") or 8)
        elif name == "gmail_search": out = search_mail(a.get("query") or "", a.get("max") or 8)
        elif name == "gmail_read":  out = read_mail(a.get("id") or "")
        elif name == "gmail_draft": out = draft(a.get("to") or "", a.get("subject") or "",
                                                a.get("body") or "", a.get("reply_to_id"))
        elif name == "gcal_events": out = events(a.get("day"), a.get("days") or 1)
        elif name == "gcal_add":    out = quick_add(a.get("text") or "")
        elif name == "gcal_move":   out = event_move(a.get("query") or "", a.get("new_time") or "")
        elif name == "gcal_delete": out = event_delete(a.get("query") or "")
        elif name == "gsheet_read":   out = sheet_read(a.get("sheet") or "", a.get("range") or "A1:Z50")
        elif name == "gsheet_append": out = sheet_append(a.get("sheet") or "", a.get("values") or [])
        elif name == "gsheet_update": out = sheet_update(a.get("sheet") or "", a.get("range") or "A1",
                                                         a.get("values") or [])
        elif name == "gsheet_create": out = sheet_create(a.get("title") or "", a.get("header"))
        elif name == "gdoc_create":   out = doc_create(a.get("title") or "", a.get("content") or "")
        elif name == "gdoc_read":     out = doc_read(a.get("doc") or "")
        elif name == "gdrive_search": out = drive_search(a.get("query") or "")
        elif name == "gdrive_upload": out = drive_upload(a.get("name") or "", a.get("content") or "",
                                                         a.get("mime") or "text/plain")
        else: return {"error": "unknown native tool %s" % name}, True
    except Exception as e:
        return {"error": str(e)[:200]}, True
    return out, bool(isinstance(out, dict) and out.get("error"))
