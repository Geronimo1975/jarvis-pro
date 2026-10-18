"""TEARDOWN bay — "Jarvis, reverse engineer igloo.inc" (2026-10-13).

REA (Reverse Engineer Anything, github.com/morluto/rea, MIT, npm `rea-agents`) is the
evidence engine. REA never launches or drives a browser — it ATTACHES (Chrome DevTools
Protocol) to one we own. So this bay:

  1. opens the site in a CLEAN Chrome window (its own profile + a loopback debug port; never
     his logged-in Chrome, never his cookies),
  2. arms REA's page capture (inspect-web-page) and, while REA watches, scrolls the page so
     scroll effects and lazy assets actually fire,
  3. runs REA's static bundle analysis (analyze-web-bundle: chunk graph, routes, GPU/shader
     signals) and REA's viewport screenshot,
  4. adds two things REA deliberately doesn't do: the browser's own asset log (every origin,
     sizes) and library fingerprints from the license banners REA captured in the code,
  5. closes the window, and has the brain write an evidence-cited teardown note into the
     vault (captures/teardowns/), born live in the galaxy under the [[REA]] concept node.

Scope: WEBSITES ONLY (his call, 2026-10-10 research: native binaries need Hopper/Ghidra/IDA
and many app licences forbid reverse engineering). REA is pinned and installed OUTSIDE the
Jarvis folder (~/.jarvis-tools/rea); without it this bay idles and says so.

⚖ Laws honoured: receipts only (the note exists on disk before Jarvis says so), the window
always closes (a lingering second Chrome instance hijacks the FOCUS tab lane's AppleEvents),
the debug port is loopback-only, one teardown at a time.
"""

import base64, json, os, re, shutil, socket, subprocess, threading, time, urllib.request, uuid
from urllib.parse import urlparse

CTX = {}   # init(): cfg, root, vault, call_model, persist_node, find_note, retrieve, wikilink,
           #         log, note_turn, pocket_text

REA_PIN = "6.4.0"                                   # the version this bay was built and tested on
TOOLS_HOME = os.path.expanduser("~/.jarvis-tools/rea")
CDP_PORT = 9333                                     # loopback only; 9222 is the common default — avoid collisions
OBSERVE_MS = 7000                                   # REA's capture window (the scroll tour runs inside it)
SETTLE_S = 2.5                                      # after load, let the intro animation start
JOB_CAP_S = 300
NOTE_DIR = "captures/teardowns"

_LOCK = threading.Lock()
JOBS = {}                                           # jid -> job dict
LAST = [None]                                       # last finished job id


# ---------- environment ----------
def init(ctx):
    CTX.update(ctx or {})
    d = diag()
    print("[teardown] bay online — REA %s, %s" % (d.get("rea_version") or "missing",
          "ready" if d.get("ready") else "NOT ready: " + "; ".join(d.get("problems") or [])))

def _cfg():
    return (CTX.get("cfg") or {}).get("rea") or {}

def _home():
    return os.path.expanduser(_cfg().get("home") or TOOLS_HOME)

def _node():
    cands = [_cfg().get("node"), shutil.which("node"),
             os.path.expanduser("~/.local/bin/node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None

def _rea_entry():
    p = os.path.join(_home(), "node_modules", "rea-agents", "scripts", "rea.mjs")
    return p if os.path.exists(p) else None

def _rea_version():
    try:
        with open(os.path.join(_home(), "node_modules", "rea-agents", "package.json")) as f:
            return json.load(f).get("version")
    except Exception:
        return None

_NODE_VER = {}
def _node_version(node):
    if node in _NODE_VER:
        return _NODE_VER[node]
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception:
        out = ""
    _NODE_VER[node] = out
    return out

def _node_ok(v):
    m = re.match(r"v(\d+)\.(\d+)", v or "")
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return (major == 22 and minor >= 19) or (major == 24 and minor >= 11) or major >= 26

def _find_chrome():
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if _cfg().get("chrome") and os.path.exists(_cfg()["chrome"]):
        return _cfg()["chrome"]
    if os.path.exists(mac):
        return mac
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "brave-browser"):
        p = shutil.which(name)
        if p:
            return p
    pf, pfx, local = (os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"))
    for p in (os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
              os.path.join(pfx, "Google", "Chrome", "Application", "chrome.exe"),
              os.path.join(local, "Google", "Chrome", "Application", "chrome.exe")):
        if p and os.path.exists(p):
            return p
    return None

def diag():
    node, entry, chrome = _node(), _rea_entry(), _find_chrome()
    nv = _node_version(node) if node else ""
    problems = []
    if not entry:
        problems.append("REA isn't installed (npm install rea-agents@%s --prefix %s)" % (REA_PIN, TOOLS_HOME))
    if not node:
        problems.append("Node.js isn't installed")
    elif not _node_ok(nv):
        problems.append("REA needs Node 22.19+ (found %s)" % (nv or "unknown"))
    if not chrome:
        problems.append("Google Chrome isn't installed")
    if not (CTX.get("vault") and os.path.isdir(CTX.get("vault"))):
        problems.append("vault not set in config.json")
    running = next((j["id"] for j in JOBS.values() if j["status"] == "running"), None)
    return {"ready": not problems, "problems": problems, "rea_version": _rea_version(),
            "rea_pinned": REA_PIN, "node": nv, "chrome": bool(chrome), "port": CDP_PORT,
            "running": running, "last": LAST[0]}


# ---------- what did he ask us to open? ----------
_TLD = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}"
_HOST_RE = re.compile(r"(?:https?://)?(?:" + _TLD + r"|localhost|127\.0\.0\.1)(?::\d{2,5})?(?:/[^\s,;!?\"')]*)?", re.I)
THIS_RE = re.compile(r"^(?:this|this (?:site|page|website|tab|one)|current (?:tab|site|page)|the (?:current )?(?:tab|page|site) i'?m on)$", re.I)

def normalize_target(text):
    """Speech → URL. 'igloo dot inc' → https://igloo.inc · 'stripe.com slash pricing' →
    https://stripe.com/pricing · 'localhost:5001' → http://localhost:5001. None if no host."""
    t = (text or "").strip().strip(".,!?\"'")
    t = re.sub(r"\s+dot\s+", ".", t, flags=re.I)
    t = re.sub(r"\s*\bslash\b\s*", "/", t, flags=re.I)
    t = re.sub(r"\s*\bcolon\b\s*", ":", t, flags=re.I)
    t = re.sub(r"\b(?:www)\s*\.\s*", "www.", t, flags=re.I)
    t = re.sub(r"\s*\.\s*", ".", t)                   # 'igloo . inc' (spaced recognizer output)
    m = _HOST_RE.search(t)
    if not m:
        return None
    u = m.group(0).rstrip(".,")
    if not re.match(r"https?://", u, re.I):
        local = re.match(r"(?:localhost|127\.0\.0\.1)", u, re.I)
        u = ("http://" if local else "https://") + u
    try:
        p = urlparse(u)
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
    except Exception:
        return None
    return u

def active_tab_url():
    """The URL of his front Chrome window's active tab (macOS only). Never the Jarvis tab.
    Read BEFORE our own window opens — a second Chrome instance steals AppleEvents."""
    if not shutil.which("osascript"):
        return None, "I can only read your current tab on a Mac, sir — tell me the site's name instead."
    try:
        out = subprocess.run(["osascript", "-e",
                              'tell application "Google Chrome" to get URL of active tab of front window'],
                             capture_output=True, text=True, timeout=4)
    except Exception:
        return None, "I couldn't read your current tab, sir — tell me the site's name instead."
    u = (out.stdout or "").strip()
    if out.returncode != 0 or not u:
        return None, "I couldn't read your current tab, sir — tell me the site's name instead."
    host = (urlparse(u).netloc or "").lower()
    if host in ("localhost:4719", "127.0.0.1:4719"):
        return None, "Your front tab is me, sir — bring the site's tab to the front, or tell me its name."
    if not u.startswith(("http://", "https://")):
        return None, "That tab isn't a website I can open, sir — tell me the site's name instead."
    return u, None


# ---------- the browser we own ----------
def _bare(h):
    h = (h or "").lower()
    return h[4:] if h.startswith("www.") else h

# S29 (2026-10-13): REA covers far more than websites. The clean-browser path above is only for
# sites; an app, a file, a package or a bundle name goes to the REA worker mission (missions.py),
# which runs REA's whole MCP catalog. This is the fork.
_FILE_EXT = r"\.(?:zip|dmg|pkg|asar|apk|ipa|aab|exe|dll|msi|jar|elf|so|dylib|framework|wasm|node)\b"
def is_web(target):
    t = (target or "").strip()
    if not t:
        return False
    if THIS_RE.match(t):
        return True
    if re.match(r"https?://", t, re.I):
        return bool(normalize_target(t))
    if t.startswith(("/", "~")) or re.search(_FILE_EXT, t, re.I) or re.search(r"[A-Z][\w -]*\.app\b", t):
        return False                                   # a path, an archive, or Notes.app (linear.app stays a site)
    return bool(normalize_target(t))

def mcp_config():
    """REA's MCP server registration for Jarvis's Claude Code workers: every REA tool (170 in
    6.4.0) over stdio, pinned to the same install the browser path uses. Written once under
    ~/.jarvis-tools/rea; never touches ~/.claude.json."""
    path = os.path.join(_home(), "mcp.json")
    entry = _rea_entry()
    if not entry:
        return None
    want = {"mcpServers": {"rea": {"command": _node() or "node", "args": [entry, "mcp"]}}}
    try:
        cur = json.load(open(path)) if os.path.exists(path) else None
    except Exception:
        cur = None
    if cur != want:
        os.makedirs(_home(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(want, f, indent=1)
    return path

def _http_json(path, timeout=3, port=None):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port or CDP_PORT, path), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def _kill_profile_chrome(profile):
    if os.name == "nt":
        return
    try:
        subprocess.run(["pkill", "-f", profile], capture_output=True, timeout=5)
    except Exception:
        pass

def _launch_chrome(url, visible=True, jid=None, port=None, root=None):
    chrome = _find_chrome()
    port = port or CDP_PORT
    # a BRAND-NEW profile per teardown: an empty cache keeps download sizes honest (a reused
    # profile reported igloo.inc at 0.4 MB instead of 14.7), and no cookies ride between sites
    root = root or os.path.join(_home(), "profiles")
    _kill_profile_chrome(root.rstrip(os.sep) + os.sep)   # stale windows from a crashed run (this root only)
    shutil.rmtree(root, ignore_errors=True)
    profile = os.path.join(root, jid or uuid.uuid4().hex[:10])
    os.makedirs(profile, exist_ok=True)
    args = [chrome, "--remote-debugging-port=%d" % port, "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--window-size=1280,820", "--window-position=60,60"]
    if not visible:
        args.append("--headless")
    args += ["--new-window", url]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=(os.name != "nt"))
    end = time.time() + 25
    while time.time() < end:
        try:
            _http_json("/json/version", timeout=1, port=port)
            return proc, profile
        except Exception:
            time.sleep(0.4)
    _close_chrome(proc, profile)
    raise RuntimeError("the clean browser never opened its debug port")

def _close_chrome(proc, profile):
    try:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
    except Exception:
        pass
    if os.name == "nt" and proc:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
        except Exception:
            pass
    _kill_profile_chrome(profile)

def _page_target(want_host, timeout=20, port=None):
    """The page target for the site (redirects allowed: igloo.inc → www.igloo.inc)."""
    base = _bare(want_host)
    end = time.time() + timeout
    best = None
    while time.time() < end:
        try:
            for t in _http_json("/json/list", port=port):
                if t.get("type") != "page":
                    continue
                u = t.get("url") or ""
                if not u.startswith(("http://", "https://")):
                    continue
                h = (urlparse(u).hostname or "").lower()
                best = t
                if not base or _bare(h) == base or _bare(h).endswith("." + base) or base.endswith("." + _bare(h)):
                    return t
        except Exception:
            pass
        time.sleep(0.4)
    return best


class _CDP:
    """A minimal, stdlib-only DevTools WebSocket client (handshake, masked client frames,
    fragmented/large server frames, ping/pong). Enough for Runtime.evaluate + wheel input."""

    def __init__(self, ws_url, timeout=15):
        u = urlparse(ws_url)
        self.s = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        self.s.sendall(("GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                        % (path, u.hostname, u.port, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("DevTools handshake closed")
            buf += chunk
            if len(buf) > 65536:
                raise ConnectionError("DevTools handshake too long")
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101" not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("DevTools refused the socket")
        self.n = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("DevTools socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode, payload):
        hdr = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126); hdr += n.to_bytes(2, "big")
        else:
            hdr.append(0x80 | 127); hdr += n.to_bytes(8, "big")
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _recv(self):
        parts = []
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 9:
                self._send(10, data); continue
            if op == 10:
                continue
            if op == 8:
                raise ConnectionError("DevTools closed the socket")
            parts.append(data)
            if b0 & 0x80:
                return b"".join(parts).decode("utf-8", "replace")

    def call(self, method, params=None, timeout=20):
        self.n += 1
        mid = self.n
        self._send(1, json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        end = time.time() + timeout
        while time.time() < end:
            self.s.settimeout(max(0.5, end - time.time()))
            msg = json.loads(self._recv())
            if msg.get("id") == mid:
                if msg.get("error"):
                    raise RuntimeError("%s: %s" % (method, (msg["error"].get("message") or "")[:120]))
                return msg.get("result") or {}
        raise TimeoutError(method)

    def eval(self, expr, timeout=12):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True}, timeout=timeout)
        return (r.get("result") or {}).get("value")

    def drain(self, seconds):
        """Every event the browser pushes for `seconds` (S29: the smoke test's error net).
        Frames are only ever read whole: select() guards the socket, so a slow large event
        never leaves half a frame in the buffer."""
        import select
        out, end = [], time.time() + seconds
        self.s.settimeout(5)
        while time.time() < end:
            if not self.buf:
                r, _, _ = select.select([self.s], [], [], min(0.3, max(0.05, end - time.time())))
                if not r:
                    continue
            try:
                msg = json.loads(self._recv())
            except (ConnectionError, OSError, ValueError):
                break
            if msg.get("method"):
                out.append(msg)
        return out

    def close(self):
        try:
            self._send(8, b"")
        except Exception:
            pass
        try:
            self.s.close()
        except Exception:
            pass


# What the page itself says about its build — read-only DOM/global reads, no clicks.
PROBE_JS = r"""(() => {
  const g = k => { try { return window[k]; } catch (_) { return undefined; } };
  const q = s => { try { return document.querySelectorAll(s).length; } catch (_) { return 0; } };
  const html = document.documentElement, cs = getComputedStyle(html);
  const res = performance.getEntriesByType('resource').slice(0, 900).map(e =>
    [String(e.name).slice(0, 300), e.initiatorType, Math.round(e.transferSize || e.encodedBodySize || e.decodedBodySize || 0)]);
  let fonts = [];
  try { fonts = [...new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/["']/g, '')))].slice(0, 12); } catch (_) {}
  let gsap = g('gsap'); gsap = gsap ? (gsap.version || 'yes') : null;
  let deep = 0, seen = 0;                                  // canvases inside shadow roots count too
  const walk = root => { try { for (const el of root.querySelectorAll('*')) { if (++seen > 20000) return;
    if (el.tagName === 'CANVAS') deep++; if (el.shadowRoot) walk(el.shadowRoot); } } catch (_) {} };
  walk(document);
  return {
    title: document.title || '', href: location.href,
    generator: (document.querySelector('meta[name=generator]') || {}).content || '',
    dom: document.getElementsByTagName('*').length,
    canvases: Math.max(q('canvas'), deep), offscreen_api: typeof OffscreenCanvas !== 'undefined', videos: q('video'), iframes: q('iframe'), images: q('img'), svgs: q('svg'),
    screens: Math.round(html.scrollHeight / Math.max(1, innerHeight) * 10) / 10,
    viewport: [innerWidth, innerHeight],
    html_class: String(html.className || '').slice(0, 200), body_class: String((document.body || {}).className || '').slice(0, 200),
    pin_spacers: q('.pin-spacer'), sticky_hint: q('[style*="sticky"]'),
    data_scroll: q('[data-scroll],[data-scroll-container]'),
    fonts, resources: res,
    globals: {
      three: g('__THREE__') || null, gsap, ScrollTrigger: !!g('ScrollTrigger'),
      Lenis: !!(g('Lenis') || g('lenis') || /\blenis\b/.test(html.className)),
      next: !!(g('__NEXT_DATA__') || document.getElementById('__next')), nuxt: !!(g('__NUXT__') || document.getElementById('__nuxt')),
      vue: !!g('__VUE__'), react: !!(document.querySelector('[data-reactroot]') || g('React')),
      sveltekit: !!document.querySelector('[data-sveltekit-preload-data],[data-sveltekit-hydrate]'),
      astro: q('astro-island') > 0, framer: q('[data-framer-name],[data-framer-component-type]') > 0,
      webflow: !!(g('Webflow') || html.getAttribute('data-wf-page')), shopify: !!g('Shopify'),
      wordpress: !!document.querySelector('link[href*="wp-content"],script[src*="wp-includes"]'),
      tailwind: cs.getPropertyValue('--tw-border-spacing-x') !== '' || !!document.querySelector('[class*="tw-"]'),
      webgpu_api: !!navigator.gpu
    }
  };
})()"""


def _scroll_tour(cdp, cancel, down=16, pause=0.28):
    """Wheel the page down (scroll-driven effects + lazy assets fire while REA watches),
    then back to the top for the snapshot. Wheel events, not scrollTo — smooth-scroll
    libraries (Lenis, custom WebGL scrollers) only listen to the wheel."""
    try:
        w, h = cdp.eval("[innerWidth, innerHeight]") or [1280, 800]
    except Exception:
        w, h = 1280, 800
    x, y = int(w / 2), int(h / 2)
    for i in range(down):
        if cancel():
            return
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": 260})
        time.sleep(pause)

def _scroll_home(cdp, steps=12):
    try:
        w, h = cdp.eval("[innerWidth, innerHeight]") or [1280, 800]
        for i in range(steps):
            cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": int(w / 2), "y": int(h / 2),
                                                  "deltaX": 0, "deltaY": -900})
            time.sleep(0.06)
        cdp.eval("window.scrollTo(0, 0)")
    except Exception:
        pass


# ---------- REA ----------
def _rea(args, timeout=120):
    node, entry = _node(), _rea_entry()
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(node) + os.pathsep + env.get("PATH", "")
    p = subprocess.run([node, entry] + args + ["--json"], capture_output=True, text=True,
                       timeout=timeout, env=env)
    out = (p.stdout or "").strip()
    try:
        return json.loads(out), None
    except Exception:
        err = (p.stderr or out or "no output").strip().splitlines()
        return None, (err[-1] if err else "no output")[:200]

def _rea_async(args, timeout=120):
    """Start a REA command in the background; returns a getter that blocks for (obj, err)."""
    box = {}
    def run():
        try:
            box["r"] = _rea(args, timeout)
        except Exception as e:
            box["r"] = (None, str(e)[:200])
    t = threading.Thread(target=run, daemon=True)
    t.start()
    def get():
        t.join(timeout + 5)
        return box.get("r", (None, "REA timed out"))
    return get


# ---------- fingerprints (what REA captured, read like a detective) ----------
# (name, regex over the captured code, optional version group). License banners survive
# minification, so they are the strongest signal; plain strings are labelled as such.
FINGERPRINTS = [
    ("Three.js", r"Three\.js Authors[\s\S]{0,240}?[=:]\s*\"(\d{3})\"", "r"),
    ("Three.js", r"THREE\.WebGLRenderer|__THREE__", None),
    ("GSAP", r"GSAP (\d+\.\d+\.\d+)", ""),
    ("GSAP", r"\bgsap\b.{0,40}version|_gsap\b", None),
    ("ScrollTrigger", r"ScrollTrigger (\d+\.\d+\.\d+)", ""),
    ("ScrollTrigger", r"\"ScrollTrigger\"|scrollTrigger", None),
    ("Lenis smooth scroll", r"lenis-smooth|\"lenis\"|lenis-stopped", None),
    ("Locomotive Scroll", r"locomotive-scroll|has-scroll-smooth", None),
    ("postprocessing (pmndrs)", r"postprocessing v(\d+\.\d+\.\d+)", ""),
    ("EffectComposer post-processing", r"EffectComposer|RenderPass|UnrealBloomPass", None),
    ("Bloom", r"UnrealBloomPass|BloomEffect|luminosityThreshold", None),
    ("Depth of field", r"nearCoCBuffer|farCoCBuffer|BokehPass|DepthOfFieldEffect|bokehScale", None),
    ("FXAA anti-aliasing", r"SUBPIXEL_QUALITY|FXAAShader|FXAA_", None),
    ("Theatre.js", r"@theatre/(?:core|studio)", None),
    ("Spline", r"@splinetool|spline\.design", None),
    ("Rive", r"@rive-app|rive\.wasm", None),
    ("Lottie", r"lottie-web|bodymovin", None),
    ("glTF models (GLTFLoader)", r"GLTFLoader|KHR_materials_|KHR_draco_mesh_compression", None),
    ("Draco mesh compression", r"DRACOLoader|draco_decoder|DracoDecoderModule", None),
    ("KTX2 / Basis textures", r"KTX2Loader|basis_transcoder|BasisTextureLoader", None),
    ("Meshopt compression", r"MeshoptDecoder|EXT_meshopt_compression", None),
    ("Svelte", r"Function called outside component initialization|svelte-[a-z0-9]{6}", None),
    ("React", r"@license React|react\.production|__reactFiber|react-dom", None),
    ("Vue", r"@vue/(?:runtime|shared)|__VUE_OPTIONS_API__|__vue_app__", None),
    ("Next.js", r"__NEXT_DATA__|next/dist|_next/static", None),
    ("Framer Motion", r"framer-motion|data-framer-appear-id", None),
    ("Howler audio", r"howler\.js v(\d+\.\d+\.\d+)", ""),
    ("Howler audio", r"\bHowler\b|new Howl\(", None),
    ("Tone.js", r"Tone\.js|tonejs", None),
    ("Rapier physics", r"rapier3d|@dimforge/rapier", None),
    ("cannon-es physics", r"cannon-es|CANNON\.World", None),
    ("Matter.js physics", r"matter-js|Matter\.Engine", None),
    ("Barba page transitions", r"@barba/core|barba\.init", None),
    ("Swiper", r"Swiper (\d+\.\d+\.\d+)", ""),
    ("PixiJS", r"pixi\.js - v(\d+\.\d+\.\d+)", ""),
    ("Babylon.js", r"BABYLON\.Engine|babylonjs", None),
    ("OGL", r"\bogl\b.{0,30}Renderer", None),
    ("WebGPU", r"navigator\.gpu|GPUBufferUsage|@vertex\s+fn", None),
    ("GLSL shader code", r"gl_FragColor|gl_Position|#version 300 es", None),
    ("Vite build", r"__vitePreload|vite/modulepreload-polyfill", None),
    ("Webpack build", r"webpackChunk|__webpack_require__", None),
]
BANNER_RE = re.compile(r"/\*[!*]\s*\n?\s*\*?\s*(?:@license\s+)?([A-Za-z@][\w@./ -]{1,40}?)\s+v?(\d+\.\d+\.\d+)")

def _fingerprint(sources, probe):
    """Returns (stack, banners). stack = the curated table's hits in its own priority order
    (what the panel shows); banners = every other 'name vX.Y.Z' license banner in the code
    (evidence for the brain and the note — e.g. GSAP's CustomEase/CustomWiggle plugins)."""
    found, order, banners = {}, [], {}
    def add(name, version, how):
        cur = found.get(name)
        if cur:
            if version and not cur["version"]:
                cur["version"], cur["how"] = version, how
            return
        found[name] = {"name": name, "version": version or "", "how": how}
        order.append(name)
    for url, text in sources:
        if not text:
            continue
        short = (url or "").rsplit("/", 1)[-1][:60]
        for name, rx, vpre in FINGERPRINTS:
            m = re.search(rx, text)
            if not m:
                continue
            v = ""
            if vpre is not None and m.groups():
                v = (vpre + m.group(1)) if vpre == "r" else m.group(1)
            add(name, v, "found in %s" % short)
        for m in BANNER_RE.finditer(text[:4000000]):
            nm = m.group(1).strip(" *-")
            if 2 <= len(nm) <= 40 and not re.match(r"^(?:Copyright|The|This|MIT|Apache|paths?)$", nm, re.I) \
                    and not re.match(r"^(?:Copyright|The|This)\b", nm, re.I):
                banners.setdefault(nm.lower(), {"name": nm, "version": m.group(2), "how": "license banner in %s" % short})
    gl = (probe or {}).get("globals") or {}
    if gl.get("three"):
        add("Three.js", "r%s" % gl["three"], "the page's own Three.js revision flag")
    if gl.get("gsap"):
        add("GSAP", "" if gl["gsap"] == "yes" else str(gl["gsap"]), "a live gsap object on the page")
    for key, name in (("ScrollTrigger", "ScrollTrigger"), ("Lenis", "Lenis smooth scroll"), ("next", "Next.js"),
                      ("nuxt", "Nuxt"), ("vue", "Vue"), ("react", "React"), ("sveltekit", "SvelteKit"),
                      ("astro", "Astro"), ("framer", "Framer"), ("webflow", "Webflow"), ("shopify", "Shopify"),
                      ("wordpress", "WordPress"), ("tailwind", "Tailwind CSS")):
        if gl.get(key):
            add(name, "", "seen on the live page")
    if (probe or {}).get("pin_spacers"):
        add("ScrollTrigger", "", "%d pinned sections (pin-spacer) on the page" % probe["pin_spacers"])
    stack = [found[n] for n in order]
    have = " ".join(n.lower() for n in order)
    extra = [b for k, b in banners.items() if k not in have and not any(k in n.lower() for n in order)]
    return stack[:24], extra[:16]

ASSET_KINDS = [
    ("3D models", r"\.(?:glb|gltf|fbx|obj|usdz|drc|splat|ply)(?:\?|$)"),
    ("GPU textures", r"\.(?:ktx2|basis|dds|hdr|exr)(?:\?|$)"),
    ("Video", r"\.(?:mp4|webm|mov|m3u8|ts)(?:\?|$)"),
    ("Audio", r"\.(?:mp3|ogg|wav|m4a|aac|flac)(?:\?|$)"),
    ("Images", r"\.(?:png|jpe?g|webp|avif|gif|svg)(?:\?|$)"),
    ("Fonts", r"\.(?:woff2?|ttf|otf)(?:\?|$)"),
    ("WebAssembly", r"\.wasm(?:\?|$)"),
    ("Shaders", r"\.(?:glsl|vert|frag|wgsl)(?:\?|$)"),
    ("Animation data", r"\.(?:riv|lottie)(?:\?|$)|lottie.*\.json"),
    ("Scripts", r"\.m?js(?:\?|$)"),
    ("Styles", r"\.css(?:\?|$)"),
]

def _assets(resources, site_host):
    cats, origins, rows = {}, {}, []
    for row in resources or []:
        try:
            url, itype, size = row[0], row[1], int(row[2] or 0)
        except Exception:
            continue
        low = url.lower()
        kind = next((k for k, rx in ASSET_KINDS if re.search(rx, low)), "Other (" + (itype or "fetch") + ")")
        c = cats.setdefault(kind, [0, 0])
        c[0] += 1; c[1] += size
        h = (urlparse(url).hostname or "").lower()
        sb = _bare(site_host)
        if h and sb and not (_bare(h) == sb or h.endswith("." + sb)):
            origins[h] = origins.get(h, 0) + 1
        rows.append((size, kind, url))
    rows.sort(reverse=True)
    return {"requests": len(rows), "bytes": sum(r[0] for r in rows),
            "by_kind": sorted(([k, v[0], v[1]] for k, v in cats.items()), key=lambda x: -x[2]),
            "largest": [[s, k, u] for s, k, u in rows[:12]],
            "third_party": sorted(origins.items(), key=lambda x: -x[1])[:12]}

def _mb(n):
    return ("%.1f MB" % (n / 1048576.0)) if n >= 104858 else ("%d KB" % max(1, round(n / 1024.0)))


# ---------- the job ----------
STEPS = [("open", "Opening the site in a clean browser"), ("load", "Waiting for it to load"),
         ("watch", "REA is watching while I scroll"), ("bundle", "REA is reading the code"),
         ("shot", "Taking a snapshot"), ("assets", "Listing everything it loaded"),
         ("stack", "Identifying the stack"), ("write", "Writing the teardown")]
STEP_LABEL = dict(STEPS)

def _ev(job, step, state, detail=""):
    with _LOCK:
        job["events"].append({"i": len(job["events"]), "step": step, "state": state,
                              "label": STEP_LABEL.get(step, step), "detail": detail, "t": round(time.time() - job["t0"], 1)})

def start(target, question="", sid=None, headless=False, then_build=None):
    """target: a URL / spoken domain / 'this'. Returns (job_summary, error_line). then_build: a build request
    (see build_request) that starts the moment the note is written — "…and build me my own version"."""
    d = diag()
    if not d["ready"]:
        return None, "My teardown kit isn't ready, sir: " + d["problems"][0] + "."
    with _LOCK:
        if any(j["status"] == "running" for j in JOBS.values()):
            return None, "I'm already taking one site apart, sir — give me a moment to finish it."
    t = (target or "").strip()
    if THIS_RE.match(t) or not t:
        url, err = active_tab_url()
        if err:
            return None, err
    else:
        url = normalize_target(t)
        if not url:
            return None, "Which website, sir? Give me its address, like igloo dot inc."
    host = (urlparse(url).hostname or "").lower()
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "url": url, "host": host, "question": (question or "").strip()[:300],
           "sid": sid, "status": "running", "events": [], "result": None, "error": None,
           "t0": time.time(), "cancel": False, "headless": bool(headless or _cfg().get("headless")),
           "then_build": (then_build if isinstance(then_build, dict) else None)}
    with _LOCK:
        JOBS[jid] = job
        for old in list(JOBS)[:-8]:                   # keep the last few for /status (insertion order)
            if JOBS[old]["status"] != "running":
                JOBS.pop(old, None)
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    nice = host[4:] if host.startswith("www.") else host
    return {"id": jid, "url": url, "host": nice,
            "ack": "Opening %s in a clean browser, sir. REA will take it apart while I scroll — "
                   "give me about a minute." % nice}, None

def _run(job):
    proc = profile = cdp = None
    cancel = lambda: job["cancel"] or (time.time() - job["t0"] > JOB_CAP_S)
    try:
        _ev(job, "open", "run")
        proc, profile = _launch_chrome(job["url"], visible=not job["headless"], jid=job["id"])
        _ev(job, "open", "ok")
        _ev(job, "load", "run")
        tgt = _page_target(job["host"])
        if not tgt:
            raise RuntimeError("the page never appeared in the browser")
        cdp = _CDP(tgt["webSocketDebuggerUrl"])
        end = time.time() + 25
        while time.time() < end and not cancel():
            try:
                if cdp.eval("document.readyState") == "complete":
                    break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(SETTLE_S)
        tid = tgt["id"]
        job["final_url"] = tgt.get("url") or job["url"]
        _ev(job, "load", "ok", (urlparse(job["final_url"]).hostname or ""))
        endpoint = "http://127.0.0.1:%d" % CDP_PORT

        # 3. REA watches while we scroll
        _ev(job, "watch", "run")
        get_inspect = _rea_async(["inspect-web-page", endpoint, tid, "--observation-ms", str(OBSERVE_MS),
                                  "--include-script-sources"], timeout=120)
        time.sleep(1.2)                                # let REA attach before the first wheel
        try:
            _scroll_tour(cdp, cancel)
        except Exception:
            pass
        inspect, ierr = get_inspect()
        nr_i = (inspect or {}).get("normalized_result") or {}
        sc = (nr_i.get("scripts") or {})
        _ev(job, "watch", "ok" if inspect else "warn",
            ("%d scripts captured" % (sc.get("total") or 0)) if inspect else ("REA: " + (ierr or "no result")))

        # 4. REA static bundle analysis
        _ev(job, "bundle", "run")
        bundle, berr = _rea(["analyze-web-bundle", endpoint, tid], timeout=150)
        nr_b = (bundle or {}).get("normalized_result") or {}
        obs = nr_b.get("observations") or {}
        _ev(job, "bundle", "ok" if bundle else "warn",
            ("%d routes · %d code signals" % (len(obs.get("routes") or []), len(obs.get("endpoints") or [])))
            if bundle else ("REA: " + (berr or "no result")))

        # 5. snapshot at the top of the page
        _ev(job, "shot", "run")
        _scroll_home(cdp)
        time.sleep(1.2)
        shot, serr = _rea(["capture-web-screenshot", endpoint, tid], timeout=60)
        png = None
        try:
            png = base64.b64decode(((shot or {}).get("normalized_result") or {})["artifact"]["data_base64"])
        except Exception:
            png = None
        if png:
            sd = os.path.join(_home(), "shots")
            os.makedirs(sd, exist_ok=True)
            with open(os.path.join(sd, job["id"] + ".png"), "wb") as f:
                f.write(png)
        _ev(job, "shot", "ok" if png else "warn", "" if png else ("REA: " + (serr or "no image")))

        # 6. the browser's own asset log (all origins — REA's capture is origin-bounded by design)
        _ev(job, "assets", "run")
        try:
            probe = cdp.eval(PROBE_JS, timeout=15) or {}
        except Exception:
            probe = {}
        try:                                           # background threads (OffscreenCanvas renderers live there)
            probe["workers"] = sum(1 for t in _http_json("/json/list") if t.get("type") == "worker")
        except Exception:
            probe["workers"] = None
        assets = _assets(probe.get("resources"), (urlparse(job["final_url"]).hostname or "").lower())
        _ev(job, "assets", "ok", "%d requests · %s" % (assets["requests"], _mb(assets["bytes"])))
    except Exception as e:
        job["status"], job["error"] = "error", str(e)[:200]
        _ev(job, "open" if not job["events"] else job["events"][-1]["step"], "fail", str(e)[:160])
        return
    finally:
        if cdp:
            cdp.close()
        if proc or profile:
            _close_chrome(proc, profile)              # ⚖ always: a lingering 2nd Chrome breaks FOCUS
            shutil.rmtree(profile, ignore_errors=True)

    try:
        # 7. the stack
        _ev(job, "stack", "run")
        sources = []
        for it in (sc.get("items") or []):
            art = ((it.get("source") or {}).get("artifact") or {})
            sources.append((it.get("url") or "", art.get("text") or ""))
        stack, banners = _fingerprint(sources, probe)
        _ev(job, "stack", "ok", ", ".join(s["name"] + ((" " + s["version"]) if s["version"] else "")
                                         for s in stack[:6]) or "nothing conclusive")

        # 8. the note
        _ev(job, "write", "run")
        facts = _facts(job, nr_i, nr_b, probe, assets, stack, inspect, bundle, shot)
        facts["banners"] = banners
        res = _write(job, facts)
        job["result"] = res
        if job.get("then_build") and CTX.get("then_build"):   # S29g: the build follows the note, same breath
            try:
                nm = CTX["then_build"](res.get("rel"), job["then_build"])
                if nm:
                    res["next_mission"] = nm
                    _ev(job, "write", "ok", "saved — now building your own version")
            except Exception:
                pass
        job["status"] = "done"
        _ev(job, "write", "ok", "saved to your vault")
        LAST[0] = job["id"]
        try:
            CTX.get("log", lambda *a: None)("teardown", "Teardown: %s → %s" % (job["host"], res.get("rel", "")))
        except Exception:
            pass
        try:
            if CTX.get("note_turn"):
                CTX["note_turn"](job.get("sid"), "[Teardown finished — %s] %s Note: %s" %
                                 (job["host"], res.get("summary", ""), res.get("rel", "")))
        except Exception:
            pass
        sid = str(job.get("sid") or "")
        if sid.startswith("pocket") and CTX.get("pocket_text"):
            try:
                CTX["pocket_text"]("🔍 Teardown: %s\n\n%s\n\nNote: %s" % (job["host"], res.get("summary", ""), res.get("rel", "")))
            except Exception:
                pass
    except Exception as e:
        job["status"], job["error"] = "error", str(e)[:200]
        _ev(job, "write", "fail", str(e)[:160])


def _facts(job, nr_i, nr_b, probe, assets, stack, inspect, bundle, shot):
    sc = nr_i.get("scripts") or {}
    scripts = [{"url": (it.get("url") or "")[:200], "bytes": int(it.get("length") or 0),
                "module": bool(it.get("is_module"))} for it in (sc.get("items") or [])]
    obs = nr_b.get("observations") or {}
    chunks = (obs.get("chunks") or {})
    names = {n.get("script_key"): (n.get("url") or "").rsplit("/", 1)[-1] for n in (chunks.get("nodes") or [])}
    edges = ["%s → %s (%s)" % (names.get(e.get("from_script_key"), "script"),
                               (e.get("resolved_url") or e.get("specifier") or "?").rsplit("/", 1)[-1],
                               (e.get("kind") or "").replace("_", " "))
             for e in (chunks.get("edges") or [])][:12]
    signals = [x.get("value") for x in (obs.get("endpoints") or []) if x.get("value")]
    signals = [s for s in dict.fromkeys(signals) if not re.match(r"^(?:while|for|if|map|scale|intensity|fragment|vertex|SAMPLES)$", s)]
    net = (nr_i.get("network") or {}).get("requests") or []
    return {
        "url": job.get("final_url") or job["url"], "host": job["host"], "question": job["question"],
        "title": (probe or {}).get("title") or ((nr_i.get("target") or {}).get("title") or ""),
        "page": {k: (probe or {}).get(k) for k in ("dom", "canvases", "workers", "videos", "iframes", "images", "svgs",
                                                   "screens", "generator", "html_class", "pin_spacers",
                                                   "data_scroll", "fonts")},
        "scripts": scripts, "script_bytes": sum(s["bytes"] for s in scripts),
        "chunk_edges": edges, "routes": [x.get("value") for x in (obs.get("routes") or [])][:20],
        "code_signals": signals[:40],
        "inferences": [("%s: %s (%s)" % (x.get("kind"), x.get("value"), x.get("confidence")))
                       for x in (nr_b.get("inferences") or [])][:10],
        "rea_network": len(net),
        "assets": assets, "stack": stack,
        "evidence": [x for x in ((inspect or {}).get("evidence_id"), (bundle or {}).get("evidence_id"),
                                 (shot or {}).get("evidence_id")) if x],
        "limits": ["REA attaches to a running page, so requests made before it attached come from the "
                   "browser's own performance log, not REA.",
                   "REA's capture is limited to the site's own origin; third-party files come from the browser log.",
                   "Library names come from license banners and strings in minified code — strong, not certain.",
                   "Server-side behaviour is invisible from the browser."],
        "rea_version": _rea_version(),
    }

def _digest(f):
    a = f["assets"]
    lines = ["SITE: %s  (title: %s)" % (f["url"], f["title"] or "none"),
             "WHAT HE ASKED: %s" % (f["question"] or "How is this site built, and how do its signature effects work?"),
             "PAGE (JARVIS's own live DOM read after load + scroll, shadow DOM included — not REA): %s elements · %s canvas · %s background worker threads · %s video · %s iframe · %s img · %s svg · page length %s screens%s" % (
                 f["page"].get("dom"), f["page"].get("canvases"), f["page"].get("workers"), f["page"].get("videos"), f["page"].get("iframes"),
                 f["page"].get("images"), f["page"].get("svgs"), f["page"].get("screens"),
                 (" · generator meta: " + f["page"]["generator"]) if f["page"].get("generator") else ""),
             "ROOT CLASSES: html='%s'" % (f["page"].get("html_class") or ""),
             "SCROLL HINTS: %s pinned sections (pin-spacer) · %s data-scroll elements" % (
                 f["page"].get("pin_spacers") or 0, f["page"].get("data_scroll") or 0),
             "FONTS IN USE: %s" % (", ".join(f["page"].get("fonts") or []) or "none reported"),
             "SCRIPTS (REA inspect-web-page, same-origin): %d · %s total" % (len(f["scripts"]), _mb(f["script_bytes"]))]
    for s in f["scripts"][:14]:
        lines.append("  - %s (%s%s)" % (s["url"], _mb(s["bytes"]), ", ES module" if s["module"] else ""))
    lines.append("CHUNK GRAPH (REA analyze-web-bundle): " + ("; ".join(f["chunk_edges"]) or "none"))
    lines.append("ROUTES (REA): " + (", ".join(f["routes"]) or "none found"))
    lines.append("CODE SIGNALS (REA — strings the bundle hands to the GPU/APIs): " + (", ".join(f["code_signals"]) or "none"))
    if f["inferences"]:
        lines.append("REA INFERENCES: " + "; ".join(f["inferences"]))
    lines.append("LIBRARIES (JARVIS fingerprints over the code REA captured, plus live page flags):")
    for s in f["stack"] or []:
        lines.append("  - %s%s — %s" % (s["name"], (" " + s["version"]) if s["version"] else "", s["how"]))
    if not f["stack"]:
        lines.append("  - nothing conclusive")
    if f.get("banners"):
        lines.append("OTHER LICENSE BANNERS IN THE CODE (JARVIS): " + ", ".join(
            "%s %s" % (b["name"], b["version"]) for b in f["banners"]))
    lines.append("ASSETS (JARVIS: the browser's own performance log after a scroll tour, all origins — not REA): %d requests · %s" % (a["requests"], _mb(a["bytes"])))
    for k, n, b in a["by_kind"][:12]:
        lines.append("  - %s: %d (%s)" % (k, n, _mb(b)))
    lines.append("LARGEST FILES:")
    for s, k, u in a["largest"][:10]:
        lines.append("  - %s · %s · %s" % (_mb(s), k, u[:160]))
    lines.append("THIRD-PARTY ORIGINS: " + (", ".join("%s (%d)" % (h, n) for h, n in a["third_party"]) or "none"))
    lines.append("LIMITS: " + " ".join(f["limits"]))
    return "\n".join(lines)

SYSTEM = (
    "You are writing a reverse-engineering TEARDOWN of a public website for a builder who makes "
    "cinematic scroll websites with AI coding tools. You are given evidence captured by REA "
    "(an open-source reverse-engineering tool) plus a browser asset log and library fingerprints. "
    "Each evidence line says who captured it (REA, or JARVIS's own browser reads) — keep that "
    "attribution straight. RULES: every claim must trace to the evidence; say 'likely' or 'appears to' for inferences; "
    "never invent a library, file, or technique the evidence doesn't support; if the evidence "
    "can't answer part of the question, say so plainly in the 'What the evidence can't show' "
    "section. Explain like a sharp senior creative developer: concrete, no fluff.\n\n"
    "OUTPUT EXACTLY THIS FORMAT, nothing before or after:\n"
    "LABEL: Teardown · <site host>\n"
    "SPOKEN: <2-3 short sentences for a dry British butler AI to say aloud to 'sir': the headline "
    "answer to his question first, in plain words, then the one most surprising detail. No URLs, "
    "no file names, no markdown. End with: The full teardown is on screen, sir.>\n"
    "SUMMARY: <one plain paragraph, max 70 words, the answer in brief>\n"
    "---NOTE---\n"
    "<a markdown note, 350-650 words, with these sections in order: '> ' a one-line verdict; "
    "'## The answer' (his question, answered directly); '## The stack' (bullets: each library or "
    "technique with its evidence in parentheses); '## How the effect works' (numbered steps); "
    "'## What it loads' (the asset story: heaviest files, models/textures/video, third parties); "
    "'## Rebuild it' (5-7 numbered steps to build something similar with Claude Code); "
    "'## What the evidence can't show'. No title heading — the system adds it.>"
)

def _parse(text):
    t = (text or "").strip()
    label = re.search(r"^LABEL:\s*(.+)$", t, re.M)
    spoken = re.search(r"^SPOKEN:\s*(.+?)(?=^\w+:|^---NOTE---)", t, re.M | re.S)
    summary = re.search(r"^SUMMARY:\s*(.+?)(?=^---NOTE---)", t, re.M | re.S)
    note = t.split("---NOTE---", 1)[1].strip() if "---NOTE---" in t else ""
    return ((label.group(1).strip() if label else ""), (spoken.group(1).strip() if spoken else ""),
            (summary.group(1).strip() if summary else ""), note)

def _corpus():
    try:
        return CTX.get("corpus", lambda: [])() or []
    except Exception:
        return []

def _jarvis_anchor():
    """The Jarvis node REA hangs off: the concept note if the graph has it, else the first
    concept whose label starts with Jarvis ('JARVIS — Second Brain'), else any Jarvis node.
    (find_note's fuzzy match picked JARVIS-V5-ROADMAP — never again.)"""
    cor = _corpus()
    for test in (lambda n: n.get("id") == "wiki/concepts/Jarvis.md",
                 lambda n: n.get("g") == "concept" and re.match(r"^jarvis\b", str(n.get("label", "")), re.I),
                 lambda n: re.match(r"^jarvis\b", str(n.get("label", "")), re.I)):
        hit = next((n for n in cor if test(n)), None)
        if hit:
            return hit
    return None

def _ensure_concept():
    """The [[REA]] concept node every teardown hangs off. Returns (anchor, created_info)."""
    hit = next((n for n in _corpus() if n.get("id") == "wiki/concepts/REA.md" or
                str(n.get("label", "")).strip() == "REA"), None)
    if hit:
        return hit, None
    vault = CTX["vault"]
    rel = "wiki/concepts/REA.md"
    path = os.path.join(vault, rel)
    body = ("# REA\n\n"
            "**REA (Reverse Engineer Anything)**, github.com/morluto/rea, MIT, npm `rea-agents`. An MCP server and "
            "CLI that lets an agent inspect software it has no source code for: websites (passive Chrome DevTools "
            "capture), JavaScript and Electron apps, .NET, Android and native binaries. Every finding comes back as "
            "Evidence with its provenance and limits.\n\n"
            "**In George OS:** [[Jarvis]]'s TEARDOWN ability (2026-10-13). \"Jarvis, reverse engineer igloo dot inc\" "
            "opens a clean Chrome window; REA captures the page, scripts and code bundle while Jarvis scrolls; Jarvis "
            "adds the browser's asset log and library fingerprints; the brain writes an evidence-cited teardown into "
            "`captures/teardowns/`, born live in the galaxy and linked here. Scope: websites only. REA is pinned at "
            "%s in ~/.jarvis-tools/rea.\n\n"
            "Related: [[Jarvis]] · [[Claude Code]] · [[AI Workshop]] · [[YouTube Channel]]\n" % REA_PIN)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    jarvis = _jarvis_anchor()
    idx = CTX["persist_node"](rel, "REA", "concept", body, (jarvis or {}).get("id") or "wiki/INDEX.md")
    anchor = {"id": rel, "label": "REA", "_idx": idx}
    return anchor, {"label": "REA", "rel": rel, "idx": idx, "group": "concept",
                    "text": "REA — Reverse Engineer Anything. Jarvis's teardown engine.",
                    "anchor_idx": (jarvis or {}).get("_idx"), "anchor_label": (jarvis or {}).get("label")}

def _write(job, facts):
    digest = _digest(facts)
    call = CTX.get("call_model")
    text, err = call([{"role": "user", "content": digest}], SYSTEM, 7000) if call else (None, "no brain")
    if err or not text or "---NOTE---" not in text:
        raise RuntimeError("the brain couldn't write the teardown (%s)" % (err or "unexpected format")[:120])
    label, spoken, summary, note = _parse(text)
    host = facts["host"][4:] if facts["host"].startswith("www.") else facts["host"]
    label = label or ("Teardown · " + host)
    if not label.lower().startswith("teardown"):
        label = "Teardown · " + host
    anchor, concept = _ensure_concept()

    vault = CTX["vault"]
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")[:48] or "site"
    day = time.strftime("%Y-%m-%d")
    ndir = os.path.join(vault, NOTE_DIR)
    os.makedirs(os.path.join(ndir, "assets"), exist_ok=True)
    shot_src = os.path.join(_home(), "shots", job["id"] + ".png")
    shot_name = None
    if os.path.exists(shot_src):
        shot_name = "%s-%s.png" % (slug, day)
        shutil.copyfile(shot_src, os.path.join(ndir, "assets", shot_name))

    related = []
    wl = CTX.get("wikilink")
    try:
        for n in (CTX.get("retrieve") or (lambda q, k=3: []))(host.split(".")[0], 3) or []:
            if n.get("id") and not str(n.get("id")).startswith(NOTE_DIR) and wl:
                related.append(wl(n))
    except Exception:
        pass
    stack_line = ", ".join(s["name"] + ((" " + s["version"]) if s["version"] else "") for s in facts["stack"][:10])
    md = ["# %s" % label, "",
          "Site: %s · captured %s with REA %s via [[Jarvis]]" % (facts["url"], time.strftime("%Y-%m-%d %H:%M"), facts["rea_version"]),
          "Asked: %s" % (facts["question"] or "How is this site built, and how do its signature effects work?"), ""]
    if shot_name:
        md += ["![[%s]]" % shot_name, ""]
    md += [note, "", "## Evidence", "",
           "- Stack fingerprints: %s" % (stack_line or "none conclusive"),
           "- Other license banners: %s" % (", ".join("%s %s" % (b["name"], b["version"]) for b in facts.get("banners") or []) or "none"),
           "- Scripts: %d (%s) · Assets: %d requests (%s)" % (len(facts["scripts"]), _mb(facts["script_bytes"]),
                                                               facts["assets"]["requests"], _mb(facts["assets"]["bytes"])),
           "- REA evidence IDs: %s" % (", ".join("`%s`" % e[:19] for e in facts["evidence"]) or "none"), "",
           "Related: [[REA]] · [[Jarvis]]" + ("".join(" · " + r for r in dict.fromkeys(related))), ""]
    body = "\n".join(md)
    path, i = os.path.join(ndir, "%s-%s.md" % (slug, day)), 2
    while os.path.exists(path):
        path = os.path.join(ndir, "%s-%s-%d.md" % (slug, day, i)); i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    rel = os.path.relpath(path, vault).replace(os.sep, "/")
    preview = (summary or "") + " Stack: " + stack_line
    idx = CTX["persist_node"](rel, label, "note", preview, anchor.get("id"))
    return {"label": label, "rel": rel, "idx": idx, "spoken": spoken or ("I've taken %s apart, sir. The full teardown is on screen." % host),
            "summary": summary, "host": host, "url": facts["url"], "title": facts["title"],
            "stack": facts["stack"][:12], "concept": concept, "rea_idx": anchor.get("_idx"),
            "counts": {"scripts": len(facts["scripts"]), "script_bytes": facts["script_bytes"],
                       "requests": facts["assets"]["requests"], "bytes": facts["assets"]["bytes"],
                       "dom": facts["page"].get("dom"), "canvases": facts["page"].get("canvases"),
                       "routes": len(facts["routes"])},
            "shot": ("/teardown/shot?id=" + job["id"]) if os.path.exists(shot_src) else None,
            "evidence": facts["evidence"], "took_s": round(time.time() - job["t0"], 1),
            "rea_version": facts["rea_version"]}


# ---------- the full note (the panel's "Read the full teardown" + "open the full teardown") ----------
def _vault_file(rel, sub, exts):
    """A vault path, only if it lives under captures/teardowns/<sub> with an allowed extension."""
    vault = CTX.get("vault") or ""
    if not vault or not rel:
        return None
    root = os.path.realpath(os.path.join(vault, NOTE_DIR, sub))
    path = os.path.realpath(os.path.join(vault, rel))
    if not path.startswith(root + os.sep) or not path.lower().endswith(exts) or not os.path.isfile(path):
        return None
    return path

def latest_note():
    vault = CTX.get("vault") or ""
    d = os.path.join(vault, NOTE_DIR)
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md")]
    except Exception:
        return None
    return os.path.relpath(max(files, key=os.path.getmtime), vault).replace(os.sep, "/") if files else None

_NOTE_STOP = {"the", "a", "an", "of", "for", "on", "my", "that", "this", "teardown", "tear", "down", "open", "show", "read", "me",
              "please", "previous", "last", "latest", "earlier", "recent", "full", "whole", "complete", "asked", "you", "i", "jarvis",
              "can", "app", "application", "up", "pull", "bring", "did", "you", "do", "again", "one"}
def pick_note(hint):
    """The teardown he means by name ('the Apple notes one' → apple-notes-macos-…), newest on ties, or None."""
    vault = CTX.get("vault") or ""
    d = os.path.join(vault, NOTE_DIR)
    words = [w for w in re.findall(r"[a-z0-9]+", (hint or "").lower()) if w not in _NOTE_STOP and len(w) > 1]
    if not words:
        return None
    best, score = None, 0
    try:
        for f in os.listdir(d):
            if not f.endswith(".md"):
                continue
            path = os.path.join(d, f)
            try:
                head = open(path, encoding="utf-8").read(400).lower()
            except OSError:
                continue
            s = sum(1 for w in words if w in f.lower() or w in head)
            if s > score or (s == score and s and best and os.path.getmtime(path) > os.path.getmtime(best)):
                best, score = path, s
    except OSError:
        return None
    return os.path.relpath(best, vault).replace(os.sep, "/") if best and score else None

def note(rel=None, hint=None):
    rel = rel or (pick_note(hint) if hint else None) or latest_note()
    path = _vault_file(rel, "", (".md",))
    if not path:
        return {"error": "no teardown note on file"}
    md = open(path, encoding="utf-8").read()
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return {"rel": rel, "label": (m.group(1).strip() if m else os.path.basename(path)), "markdown": md,
            "path": path, "assets": NOTE_DIR + "/assets/"}


# ---------- S29: Jarvis tests what he built ----------
def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def smoke_test(url, out_png=None, seconds=6.0):
    """Load a built app in a hidden Chrome and net every error: uncaught exceptions, console
    errors, failed or 404 loads. Returns {ok, errors[], shot, took_s}. Headless, no audio.
    S29h: its OWN port and profile root per call — two builds finishing together no longer
    kill each other's test browser."""
    t0 = time.time()
    proc = profile = cdp = None
    errors, seen, urls = [], set(), {}
    tag = uuid.uuid4().hex[:8]
    root = os.path.join(_home(), "profiles-smoke-" + tag)
    SMOKE_PORT = _free_port()
    host = (urlparse(url).hostname or "").lower()
    def add(line):
        if line and line not in seen:
            seen.add(line); errors.append(line)
    try:
        proc, profile = _launch_chrome(url, visible=False, jid="s" + uuid.uuid4().hex[:8], port=SMOKE_PORT, root=root)
        tgt = _page_target(host, timeout=15, port=SMOKE_PORT)
        if not tgt:
            return {"ok": False, "errors": ["the page never opened in the test browser"], "shot": False, "took_s": round(time.time() - t0, 1)}
        cdp = _CDP(tgt["webSocketDebuggerUrl"])
        for dom in ("Page", "Runtime", "Log", "Network"):
            cdp.call(dom + ".enable")
        cdp.call("Page.reload", {"ignoreCache": True})          # start clean so load-time errors are netted too
        # S29h: keep netting while the page is still fetching (a 3D site's loader pulled a library 8 s in and 404'd
        # after the old 6 s window) — slices of 2 s until the network has been quiet for one slice, 25 s at most
        events, quiet, t_start = [], 0, time.time()
        while time.time() - t_start < max(seconds, 25.0):
            batch = cdp.drain(2.0)
            events += batch
            fetched = any(e.get("method") == "Network.requestWillBeSent" for e in batch)
            quiet = 0 if fetched else quiet + 1
            if time.time() - t_start >= seconds and quiet >= 1:
                break
        for ev in events:
            m, p = ev.get("method"), ev.get("params") or {}
            if m == "Network.requestWillBeSent":
                urls[p.get("requestId")] = ((p.get("request") or {}).get("url") or "")
            elif m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails") or {}
                ex = d.get("exception") or {}
                line = "exception: " + str(ex.get("description") or d.get("text") or "").split("\n")[0][:220]
                if d.get("url"):
                    line += " @ %s:%s" % (os.path.basename(d["url"]).split("?")[0], d.get("lineNumber"))
                add(line)
            elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
                add("console.error: " + " ".join(str(a.get("value", a.get("description", "")))[:160] for a in p.get("args") or [])[:220])
            elif m == "Log.entryAdded":
                e = p.get("entry") or {}
                if e.get("level") == "error" and e.get("source") not in ("network",):   # network errors come via Network.*
                    add("%s: %s" % (e.get("source", "log"), str(e.get("text") or "")[:220]))
            elif m == "Network.responseReceived":
                r = p.get("response") or {}
                name = os.path.basename(str(r.get("url") or "")).split("?")[0]
                if int(r.get("status") or 0) >= 400 and name not in ("favicon.ico",) and not name.endswith(".map"):   # the browser asks for these itself
                    add("HTTP %s: %s" % (r.get("status"), name or r.get("url")))
            elif m == "Network.loadingFailed" and not p.get("canceled"):
                name = os.path.basename(urls.get(p.get("requestId"), "")).split("?")[0]
                if name not in ("favicon.ico",) and not name.endswith(".map"):
                    add("failed load: %s (%s)" % (name or "request", str(p.get("errorText") or "")[:80]))
        shot = False
        if out_png:
            try:
                data = cdp.call("Page.captureScreenshot", {"format": "png"}, timeout=20).get("data")
                if data:
                    with open(out_png, "wb") as f:
                        f.write(base64.b64decode(data))
                    shot = True
            except Exception:
                pass
        return {"ok": not errors, "errors": errors[:12], "shot": shot, "took_s": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "errors": ["test browser failed: %s" % str(e)[:160]], "shot": False, "took_s": round(time.time() - t0, 1)}
    finally:
        try:
            if cdp:
                cdp.close()
        except Exception:
            pass
        _close_chrome(proc, profile)
        shutil.rmtree(root, ignore_errors=True)


# ---------- S29f: what did he MEAN? (one dispatcher for both doors) ----------
# 2026-10-13 evening: the recognizer heard "igloo.inc" as "Igloo ink", the brain wrote "Igloo Inc website", and
# "reverse engineer it for me" captured "for me" — four REA missions ran on garbage targets. Now spoken site names
# are resolved with a DNS check, pronouns are read from the sentence, and a target nobody can resolve gets a
# question back instead of a job.
_SAID_TLD = {"ink": "inc", "inc": "inc", "com": "com", "calm": "com", "io": "io", "ai": "ai", "app": "app", "co": "co",
             "org": "org", "net": "net", "dev": "dev", "so": "so", "me": "me", "tv": "tv", "gg": "gg", "sh": "sh", "fm": "fm", "xyz": "xyz"}
_SITE_WORDS = ("website", "web site", "site", "homepage", "home page", "web page", "webpage", "landing page", "url", "domain")
_APP_WORDS = ("app", "application", "program", "software", "mac", "desktop", "zip", "dmg", "package", "file", "folder", "bundle", "binary", "installed")
_TARGET_STOP = {"the", "a", "an", "this", "that", "it", "my", "for", "me", "please", "now", "again", "website", "web", "site",
                "homepage", "page", "called", "named", "which", "is", "one", "their", "its", "of", "on", "to", "go", "ahead", "and"}

def _dns(host, timeout=2.5):
    out = []
    def go():
        try:
            socket.getaddrinfo(host, 443); out.append(True)
        except Exception:
            pass
    th = threading.Thread(target=go, daemon=True); th.start(); th.join(timeout)
    return bool(out)

def brain_domain(name):
    """A bare company/product name → its real address, from the brain ('igloo' → igloo.inc), DNS-validated.
    A DNS guess alone picked igloo.io for 'the igloo website' (2026-10-13), so the brain goes first."""
    call = CTX.get("call_model")
    if not call or not (name or "").strip():
        return None
    try:
        text, err = call([{"role": "user", "content": "The user named this website or company: \"%s\". If that clearly refers to one "
                           "specific public website, reply with ONLY its domain name (like igloo.inc or stripe.com), nothing else. "
                           "If you are not sure, reply NONE." % name.strip()[:80]}],
                         "You map spoken company or product names to their real web domain. One token, no prose.", 30)
    except Exception:
        return None
    if err or not text:
        return None
    m = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", text.strip().lower())
    if not m or m.group(1).endswith((".none",)) or text.strip().upper().startswith("NONE"):
        return None
    host = m.group(1).strip(".")
    return host if _dns(host) else None

def spoken_site(text, guess=True):
    """'igloo ink' / 'Igloo Inc website' / 'stripe' → a URL whose host actually resolves, or None.
    guess=False: only a spoken ending (ink→inc, dot com…) or a confident brain answer count — no .com/.io roulette
    (a guess turned 'the igloo website' into igloo.io on 2026-10-13; members get a question instead)."""
    t = re.sub(r"'s\b", "", (text or "").lower())
    t = re.sub(r"[^a-z0-9 .'-]+", " ", t)
    words = [w.strip(".'-") for w in t.split()]
    words = [w for w in words if w and w not in _TARGET_STOP]
    if not words:
        return None
    cands = []
    tld = _SAID_TLD.get(words[-1])
    if not tld:                                            # no TLD was spoken: the brain names it, or nobody does
        host = brain_domain(" ".join(words))
        if host:
            return "https://" + host
        if not guess:
            return None
    if tld and len(words) >= 2:
        cands += ["%s.%s" % ("".join(words[:-1]), tld), "%s.%s" % ("-".join(words[:-1]), tld)]
    name = "".join(w for w in words if not (w == words[-1] and tld)) if (tld and len(words) >= 2) else "".join(words)
    cands += ["%s.%s" % (name, x) for x in ("com", "io", "ai", "app", "co")]
    if len(words) > 1:
        cands.append("%s.com" % words[0])
    seen = set()
    for h in cands:
        if h in seen or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", h):
            continue
        seen.add(h)
        if _dns(h):
            return "https://" + h
    return None

WANTS_BUILD = re.compile(r"\b(?:and|then|after that|afterwards|,)\s*(?:then\s+)?(?:build|make|create|code|recreate|clone|replicate|copy|rebuild)\b"
                         r"|\b(?:clone|recreate|re-?create|replicate|rebuild|re-?build)\b", re.I)
def wants_build(text):
    return bool(WANTS_BUILD.search(text or ""))

def build_request(target, question):
    """What the follow-up build is told (the teardown note becomes its blueprint)."""
    t = re.sub(r"^https?://", "", (target or "").strip()).rstrip("/") or "the thing I just took apart"
    q = re.sub(r"\s+", " ", (question or "")).strip()
    return {"brief": "My own ORIGINAL version of %s — the same techniques and structure as the teardown, with a different "
                     "name, theme, copy and visuals.%s" % (t, (" The user's words: \"%s\"" % q[:240]) if q else "")}

def classify(target, question=""):
    """('web', url) | ('this', None) | ('app', path-or-None) | ('ask', line) — what he meant."""
    raw, q = (target or "").strip(), (question or "").strip()
    t = re.sub(r"\s+(?:for me|please|now|again|too|real quick|quickly)\s*[.?!]*$", "", raw, flags=re.I).strip(" .,!?")
    tl, ql = t.lower(), q.lower()
    if t.startswith(("/", "~")) or re.search(_FILE_EXT, t, re.I) or re.search(r"[A-Z][\w -]*\.app\b", t):
        return ("app", resolve_app(t))                  # a path, an archive, Notes.app — .app/.zip are domains too, never here
    url = normalize_target(t) if t else None
    if url:
        return ("web", url)
    if t and THIS_RE.match(t):
        return ("this", None)
    if not t or re.fullmatch(r"(?:it|this|that|this one|that one|them)", tl):
        m = re.search(r"\b(?:which is|called|named|at)\s+([A-Za-z0-9][\w .'-]{1,40}?)(?=\s+(?:can|could|would|and|so|please|then|right)\b|[,.?!]|$)", q, re.I)
        if m:
            t, tl = m.group(1).strip(), m.group(1).strip().lower()
        elif any(w in ql for w in _SITE_WORDS) or re.search(r"\b(?:this|the current) (?:tab|page|site|website)\b", ql):
            return ("this", None)
        else:
            return ("ask", "Reverse engineer what, sir? A site address like igloo dot inc, or an app on your Mac.")
        url = normalize_target(t)
        if url:
            return ("web", url)
    appish = (any(re.search(r"\b%s\b" % re.escape(w), tl) for w in _APP_WORDS) or t.startswith(("/", "~"))
              or re.search(_FILE_EXT, t, re.I) or re.search(r"[A-Z][\w -]*\.app\b", t))
    siteish = any(w in tl for w in _SITE_WORDS) or any(w in ql for w in _SITE_WORDS)
    if appish and not siteish:
        return ("app", resolve_app(t))
    if siteish:
        u = spoken_site(t, guess=False)
        return ("web", u) if u else ("ask", "Which site, sir? Give me its address, like igloo dot inc.")
    app = resolve_app(t)                                   # a bare name: an installed app wins…
    if app:
        return ("app", app)
    words = [w for w in re.findall(r"[a-z0-9]+", tl) if w not in _TARGET_STOP]
    if len(words) == 1 or (len(words) >= 2 and _SAID_TLD.get(words[-1]) and words[-1] != "app"):
        u = spoken_site(t, guess=False)                     # …then a site: a spoken ending ("igloo ink" → igloo.inc) or the brain's
        if u:                                               # confident answer ("stripe" → stripe.com); never a .com/.io guess
            return ("web", u)
    return ("ask", "I couldn't find %s as an app or a site, sir. Give me the address, or the app's exact name." % (t or "that"))


# ---------- S29d: the picture of the thing (apps get a real snapshot, like sites do) ----------
APP_DIRS = ["/Applications", "/System/Applications", "/System/Applications/Utilities", "/Applications/Utilities",
            os.path.expanduser("~/Applications")]
if os.name == "nt":                                         # 7.2 ships on Windows too: programs are folders of .exe, not bundles
    APP_DIRS = [p for p in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")) if p and os.path.isdir(p)]
_APP_STOP = {"the", "my", "a", "an", "this", "that", "app", "application", "on", "mac", "macbook", "computer", "please",
             "now", "for", "me", "of", "in", "installed", "native", "desktop", "apple", "apple's", "program", "software"}
def resolve_app(target):
    """'the Notes app on my Mac' / 'Notes.app' / 'Obsidian' → the .app bundle path, or None (then the worker looks)."""
    t = (target or "").strip()
    if t.startswith(("/", "~")):
        p = os.path.expanduser(t.rstrip("/"))
        return p if p.lower().endswith(".app") and os.path.isdir(p) else None
    words = [w[:-4] if w.lower().endswith(".app") else w for w in re.findall(r"[A-Za-z0-9][\w'.+-]*", t)]
    words = [w for w in words if w.lower() not in _APP_STOP]
    if not words:
        return None
    apps = []
    for d in APP_DIRS:
        try:
            if os.name == "nt":                             # a program folder (or a bare .exe) named like the target
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if f.lower().endswith(".exe"):
                        apps.append(fp)
                    elif os.path.isdir(fp):
                        exes = [x for x in os.listdir(fp) if x.lower().endswith(".exe")]
                        if exes:
                            apps.append(os.path.join(fp, sorted(exes, key=len)[0]))
            else:
                apps += [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".app")]
        except OSError:
            pass
    def _nm(a):
        if os.name == "nt":
            d = os.path.basename(os.path.dirname(a))
            return (d if d.lower() not in ("program files", "program files (x86)", "programs") else os.path.basename(a)[:-4]).lower()
        return os.path.basename(a)[:-4].lower()
    by_name = {_nm(a): a for a in apps}
    spans = [" ".join(words[i:j]).lower() for i in range(len(words)) for j in range(len(words), i, -1)]   # longest first
    for c in spans:
        if c in by_name:
            return by_name[c]
    for c in spans:
        hit = [a for n, a in by_name.items() if n.startswith(c)]
        if len(hit) == 1:
            return hit[0]
    return None

def _bundle_info(app):
    try:
        import plistlib
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f)
    except Exception:
        return {}

def _icon_hero(app, out_png):
    """The app's icon on a dark 1600×916 card (sips only; no permissions involved)."""
    info = _bundle_info(app)
    res = os.path.join(app, "Contents", "Resources")
    icon = str(info.get("CFBundleIconFile") or info.get("CFBundleIconName") or "AppIcon")
    src = next((os.path.join(res, icon + ext) for ext in ("", ".icns") if os.path.isfile(os.path.join(res, icon + ext))), None)
    if not src:
        try:
            src = next((os.path.join(res, f) for f in sorted(os.listdir(res)) if f.lower().endswith(".icns")), None)
        except OSError:
            src = None
    if not src:
        return False
    tmp = out_png + ".icon.png"
    try:
        if subprocess.run(["sips", "-s", "format", "png", "--resampleWidth", "380", src, "--out", tmp],
                          capture_output=True, timeout=30).returncode != 0:
            return False
        ok = subprocess.run(["sips", "-p", "916", "1600", "--padColor", "0B1612", tmp, "--out", out_png],
                            capture_output=True, timeout=30).returncode == 0
    except Exception:
        ok = False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return ok and os.path.exists(out_png)

# on-screen windows, front to back — CoreGraphics through JXA: nothing is scripted, so no permission prompt
_JXA_WINDOWS = ('ObjC.import("CoreGraphics"); const l = $.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly | '
                '$.kCGWindowListExcludeDesktopElements, 0); const n = $.CFArrayGetCount(l); const out = []; '
                'for (let i = 0; i < n; i++) { const d = ObjC.deepUnwrap(ObjC.castRefToObject($.CFArrayGetValueAtIndex(l, i))); '
                'if (d && d.kCGWindowLayer === 0 && d.kCGWindowOwnerName) out.push({o: d.kCGWindowOwnerName, t: d.kCGWindowName || "", '
                'id: d.kCGWindowNumber, pid: d.kCGWindowOwnerPID, w: d.kCGWindowBounds.Width, h: d.kCGWindowBounds.Height}); } '
                'JSON.stringify(out)')
def _windows():
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", _JXA_WINDOWS], capture_output=True, text=True, timeout=15)
        return json.loads(r.stdout.strip() or "[]")
    except Exception:
        return []

def _blank(png):
    """Without Screen Recording permission a capture comes back flat; flat re-encodes to almost nothing."""
    tmp = png + ".probe.jpg"
    try:
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "20", png, "--out", tmp], capture_output=True, timeout=30)
        n = os.path.getsize(tmp)
        return n < 6000
    except Exception:
        return True
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

def app_visual(app, out_png, launch=True, wait_s=7.0):
    """The picture for an app teardown: its LIVE window (the app is opened — on camera that reads as
    'Jarvis takes a look'), else its icon on a dark card. Returns 'window' | 'icon' | None."""
    name = os.path.basename(app)[:-4]
    info = _bundle_info(app)
    owner = str(info.get("CFBundleName") or info.get("CFBundleDisplayName") or name)
    front = None
    if launch and _cfg().get("app_shot", True) is not False:
        try:
            wins = _windows()
            front = wins[0]["o"] if wins else None
            warm = any(w["o"] in (owner, name) for w in wins)   # already open → it's drawn; cold → it's still loading
            subprocess.run(["open", "-a", app], capture_output=True, timeout=20)
            win, end = None, time.time() + wait_s
            while time.time() < end and not win:
                time.sleep(0.8)
                win = next((w for w in _windows() if w["o"] in (owner, name) and (w.get("w") or 0) >= 400 and (w.get("h") or 0) >= 300), None)
            if win:
                time.sleep(1.2 if warm else 6.0)                  # S29h: a cold Electron app showed its "Loading workspace…" splash at 1.2 s
                subprocess.run(["screencapture", "-x", "-o", "-l", str(win["id"]), out_png], capture_output=True, timeout=30)
                if os.path.exists(out_png) and not _blank(out_png):
                    subprocess.run(["sips", "--resampleWidth", "1600", out_png, "--out", out_png], capture_output=True, timeout=30)
                    return "window"
                try:
                    os.remove(out_png)
                except OSError:
                    pass
        except Exception:
            pass
        finally:
            if front and front not in (owner, name, "Window Server", "Dock"):
                try:
                    subprocess.run(["open", "-a", front], capture_output=True, timeout=10)   # hand the desk back
                except Exception:
                    pass
    return "icon" if _icon_hero(app, out_png) else None


# ---------- S29: notes written by the REA worker (apps, files, packages — anything not a site) ----------
def write_note(label, target, question, note_md, spoken=None, summary=None, shot_src=None, shot_kind=None):
    """Save a worker-written teardown into captures/teardowns/, born under the [[REA]] concept.
    Returns the same shape the website path returns so the viewer births it identically."""
    anchor, concept = _ensure_concept()
    vault = CTX["vault"]
    short = re.sub(r"^teardown\s*·\s*", "", label or "", flags=re.I).strip() or (target or "target")[:60]
    label = "Teardown · " + short
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-")[:48] or "target"
    day = time.strftime("%Y-%m-%d")
    ndir = os.path.join(vault, NOTE_DIR)
    os.makedirs(os.path.join(ndir, "assets"), exist_ok=True)
    shot_name = None
    if shot_src and os.path.exists(shot_src):                  # S29d: the app's picture rides with the note, like a site's
        shot_name = "%s-%s.png" % (slug, day)
        i = 2
        while os.path.exists(os.path.join(ndir, "assets", shot_name)):
            shot_name = "%s-%s-%d.png" % (slug, day, i); i += 1
        shutil.copyfile(shot_src, os.path.join(ndir, "assets", shot_name))
    body = "\n".join(["# %s" % label, "",
                      "Target: %s · analyzed %s with REA %s via [[Jarvis]] (REA MCP worker)" % (target, time.strftime("%Y-%m-%d %H:%M"), _rea_version() or REA_PIN),
                      "Asked: %s" % (question or "How is this built, and how does it work?"), ""]
                     + (["![[%s]]" % shot_name, ""] if shot_name else [])
                     + (["> " + re.sub(r"\s+", " ", summary).strip(), ""] if summary else [])
                     + [(note_md or "").strip(), "", "Related: [[REA]] · [[Jarvis]]", ""])
    path, i = os.path.join(ndir, "%s-%s.md" % (slug, day)), 2
    while os.path.exists(path):
        path = os.path.join(ndir, "%s-%s-%d.md" % (slug, day, i)); i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    rel = os.path.relpath(path, vault).replace(os.sep, "/")
    idx = CTX["persist_node"](rel, label, "note", (summary or short)[:300], anchor.get("id"))
    try:
        CTX.get("log", lambda *a: None)("teardown", "Teardown (REA worker): %s → %s" % (short, rel))
    except Exception:
        pass
    return {"label": label, "rel": rel, "idx": idx, "host": short, "target": target,
            "spoken": spoken or ("I've taken %s apart, sir. The teardown is in your vault." % short),
            "summary": summary or "", "concept": concept, "rea_idx": anchor.get("_idx"),
            "shot": ("/teardown/asset?rel=%s/assets/%s" % (NOTE_DIR, shot_name)) if shot_name else None,
            "shot_kind": shot_kind if shot_name else None}

def rebuild_brief(rel=None):
    """The blueprint for 'build my own version of that': the latest (or named) teardown's answer,
    stack, mechanics and rebuild steps — techniques only, so the build stays original."""
    d = note(rel)
    if d.get("error"):
        return None
    md = d["markdown"]
    keep = []
    for sec in ("The answer", "The stack", "How the effect works", "How it works", "Rebuild it"):
        m = re.search(r"^##\s*%s\s*\n(.*?)(?=^##\s|\Z)" % re.escape(sec), md, re.M | re.S)
        if m and m.group(1).strip():
            keep.append("### %s\n%s" % (sec, m.group(1).strip()[:2200]))
    head = re.search(r"^(?:Site|Target):\s*(.+?)(?:\s+·|$)", md, re.M)
    return {"label": d["label"], "rel": d["rel"], "source": (head.group(1).strip() if head else d["label"]),
            "text": "\n\n".join(keep)[:7000]}


# ---------- S29e: the spoken walkthrough ("give me a summary of the teardown") ----------
WALK_SECTIONS = ["The answer", "The stack", "How the effect works", "How it works", "What it loads", "Rebuild it", "What the evidence can't show"]
WALK_SYSTEM = ("You are Jarvis, a dry, precise British butler, speaking to 'sir'. You are given one of his teardown notes. Write a "
               "SPOKEN walkthrough of it: for each section listed, one or two short spoken sentences in plain English — no file "
               "names, no identifiers, no version numbers unless they matter, no markdown, no lists. Say what the section found, not "
               "that it exists. Then one closing line. Reply with ONLY this JSON: {\"sections\": [{\"title\": \"<section title exactly as given>\", "
               "\"say\": \"<the sentences>\"}], \"closing\": \"<one short line>\"}")
def _walk_cache_path(rel):
    d = os.path.join(_home(), "summaries")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-")[:80] + ".json")

def summary(rel=None, hint=None):
    """A section-by-section spoken brief of a teardown note (the brain writes it once; cached by note mtime)."""
    d = note(rel, hint)
    if d.get("error"):
        return d
    md, rel = d["markdown"], d["rel"]
    try:
        mtime = os.path.getmtime(d["path"])
    except OSError:
        mtime = 0
    cp = _walk_cache_path(rel)
    try:
        c = json.load(open(cp, encoding="utf-8"))
        if c.get("mtime") == mtime and c.get("sections"):
            return {"rel": rel, "label": d["label"], "sections": c["sections"], "closing": c.get("closing", ""), "cached": True}
    except Exception:
        pass
    present, chunks = [], []
    for sec in WALK_SECTIONS:
        m = re.search(r"^##\s*%s\s*\n(.*?)(?=^##\s|\Z)" % re.escape(sec), md, re.M | re.S)
        if m and m.group(1).strip():
            present.append(sec)
            chunks.append("## %s\n%s" % (sec, m.group(1).strip()[:2600]))
    if not present:
        return {"error": "that note has no sections I can walk through"}
    call = CTX.get("call_model")
    if not call:
        return {"error": "no brain"}
    user = ("Note title: %s\nSections to cover, in this order: %s\n\n%s" % (d["label"], "; ".join(present), "\n\n".join(chunks)))
    text, err = call([{"role": "user", "content": user}], WALK_SYSTEM, 900)
    if err or not text:
        return {"error": "the brain couldn't write the walkthrough (%s)" % (err or "empty")[:80]}
    body = text
    fm = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.S)
    if fm:
        body = fm.group(1)
    i, j = body.find("{"), body.rfind("}")
    try:
        data = json.loads(body[i:j + 1])
    except Exception:
        return {"error": "the walkthrough came back unreadable"}
    secs = [{"title": str(x.get("title") or "")[:60], "say": str(x.get("say") or "").strip()[:600]}
            for x in (data.get("sections") or []) if isinstance(x, dict) and str(x.get("say") or "").strip()]
    out = {"rel": rel, "label": d["label"], "sections": secs, "closing": str(data.get("closing") or "").strip()[:240], "cached": False}
    try:
        json.dump({"mtime": mtime, "sections": secs, "closing": out["closing"]}, open(cp, "w", encoding="utf-8"))
    except Exception:
        pass
    return out


# ---------- doors ----------
def status(jid, since=0):
    j = JOBS.get(jid or LAST[0] or "") or (JOBS[list(JOBS)[-1]] if (JOBS and not jid) else None)
    if not j:
        return {"error": "no such teardown"}
    with _LOCK:
        evs = j["events"][int(since or 0):]
    return {"id": j["id"], "status": j["status"], "url": j["url"], "host": j["host"],
            "events": evs, "next": len(j["events"]), "result": j["result"], "error": j["error"]}

def handle(h, method, path, p):
    from urllib.parse import parse_qs
    route, _, qs = path.partition("?")
    q = {k: v[0] for k, v in parse_qs(qs).items()}
    if method == "GET" and route == "/teardown/diag":
        h._json(diag()); return True
    if method == "GET" and route == "/teardown/status":
        h._json(status(q.get("id"), q.get("since") or 0)); return True
    if method == "GET" and route == "/teardown/shot":
        jid = re.sub(r"[^a-f0-9]", "", q.get("id") or "")
        fp = os.path.join(_home(), "shots", jid + ".png")
        if not jid or not os.path.exists(fp):
            h._json({"error": "no snapshot"}, 404); return True
        data = open(fp, "rb").read()
        h.send_response(200)
        h.send_header("Content-Type", "image/png")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(data)
        return True
    if method == "GET" and route == "/teardown/note":
        h._json(note(q.get("rel"), q.get("hint"))); return True
    if method == "GET" and route == "/teardown/asset":
        fp = _vault_file(q.get("rel"), "assets", (".png", ".jpg", ".jpeg", ".webp"))
        if not fp:
            h._json({"error": "no such asset"}, 404); return True
        data = open(fp, "rb").read()
        h.send_response(200)
        h.send_header("Content-Type", "image/png" if fp.lower().endswith(".png") else "image/jpeg")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(data)
        return True
    if method == "POST" and route == "/teardown":
        tb = p.get("then_build")
        if tb is True or (tb and not isinstance(tb, dict)):
            tb = build_request(p.get("target") or p.get("url") or "", p.get("question") or "")
        res, err = start(p.get("target") or p.get("url") or "", p.get("question") or "", p.get("session"),
                         headless=bool(p.get("headless")), then_build=tb)
        h._json({"error": err} if err else res, 409 if err and "already" in err else 200); return True
    if method == "POST" and route == "/teardown/summary":        # S29e: the spoken walkthrough
        res = summary(p.get("rel"), p.get("hint"))
        h._json(res, 404 if res.get("error") else 200); return True
    if method == "POST" and route == "/teardown/cancel":
        j = JOBS.get(p.get("id") or "")
        if j and j["status"] == "running":
            j["cancel"] = True
        h._json({"ok": True}); return True
    return False
