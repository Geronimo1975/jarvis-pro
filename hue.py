"""Philips Hue link — the room is Jarvis's body.

Emerald glow while he speaks, red flash on errors, warm dim in focus mode.
Talks straight to the bridge's local v1 API (millisecond latency, no cloud, no LLM).
Completely silent no-op until a bridge is paired: /hue_setup runs discovery + pairing
(press the round bridge button first). State lives in jarvis-hue.json.

Python 3 stdlib only. Config (optional, in config.json):
  "hue": { "bridge_ip": "192.168.x.x", "app_key": "...", "lights": ["1","2"] }
"""
import json, os, threading, urllib.request

_CFG = {}
_ROOT = "."
_STATE_FILE = None
_LOCK = threading.Lock()
_SAVED_SPEAK = {}
_SAVED_FOCUS = {}
_SPEAKING = [False]


def init(cfg, root):
    global _CFG, _ROOT, _STATE_FILE
    _CFG, _ROOT = dict(cfg or {}), root
    _STATE_FILE = os.path.join(root, "jarvis-hue.json")


def _stored():
    try:
        if _STATE_FILE and os.path.exists(_STATE_FILE):
            return json.load(open(_STATE_FILE))
    except Exception:
        pass
    return {}


def _save_stored(d):
    try:
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, _STATE_FILE)
    except OSError:
        pass


def _conn():
    """(bridge_ip, app_key, light_ids) or (None, None, [])."""
    st = _stored()
    ip = _CFG.get("bridge_ip") or st.get("bridge_ip")
    key = _CFG.get("app_key") or st.get("app_key")
    lights = _CFG.get("lights") or st.get("lights") or []
    return (ip, key, lights) if ip and key else (None, None, [])


def _req(url, data=None, method=None, timeout=3):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method or ("PUT" if body else "GET"))
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)


def status():
    ip, key, lights = _conn()
    if not ip:
        return {"state": "absent", "lights": 0}
    return {"state": "ready", "lights": len(lights)}


def setup(ip=None):
    """Pair with the bridge. Returns (result, None) or (None, spoken-error)."""
    if not ip:
        try:
            found = _req("https://discovery.meethue.com/", timeout=6)
            ip = (found or [{}])[0].get("internalipaddress")
        except Exception:
            ip = None
        if not ip:
            return None, ("I can't find a Hue bridge on this network, sir — if you have one, "
                          "tell me its IP; if not, a bridge and a bulb or two (~$70) give me a body.")
    try:
        res = _req(f"http://{ip}/api", {"devicetype": "jarvis#brain-studio"}, method="POST", timeout=5)
    except Exception:
        return None, f"the bridge at {ip} isn't answering, sir."
    err = (res or [{}])[0].get("error") or {}
    if err.get("type") == 101:
        return None, ("press the round button on the bridge, sir, then ask me to set up the lights "
                      "again within 30 seconds.")
    key = ((res or [{}])[0].get("success") or {}).get("username")
    if not key:
        return None, "the bridge refused the handshake, sir."
    try:
        lights = list(_req(f"http://{ip}/api/{key}/lights", timeout=5).keys())
    except Exception:
        lights = []
    _save_stored({"bridge_ip": ip, "app_key": key, "lights": lights})
    return {"answer": f"Lights linked, sir — {len(lights)} of them. The room is mine now.",
            "bridge_ip": ip, "lights": len(lights)}, None


def _light_states(ip, key, lights):
    out = {}
    for lid in lights:
        try:
            s = _req(f"http://{ip}/api/{key}/lights/{lid}")["state"]
            out[lid] = {k: s[k] for k in ("on", "bri", "hue", "sat") if k in s}
        except Exception:
            pass
    return out


def _put(ip, key, lid, state):
    try:
        _req(f"http://{ip}/api/{key}/lights/{lid}/state", state)
    except Exception:
        pass


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


def speak_start():
    ip, key, lights = _conn()
    if not ip or _SPEAKING[0]:
        return
    _SPEAKING[0] = True

    def go():
        with _LOCK:
            _SAVED_SPEAK.clear()
            _SAVED_SPEAK.update(_light_states(ip, key, lights))
            for lid in lights:
                prev = _SAVED_SPEAK.get(lid, {})
                _put(ip, key, lid, {"on": True, "hue": 25500, "sat": 210,
                                    "bri": min(254, prev.get("bri", 160) + 60), "transitiontime": 2})
    _spawn(go)


def speak_end():
    ip, key, lights = _conn()
    if not ip or not _SPEAKING[0]:
        return
    _SPEAKING[0] = False

    def go():
        with _LOCK:
            for lid, prev in _SAVED_SPEAK.items():
                if prev:
                    _put(ip, key, lid, dict(prev, transitiontime=4))
            _SAVED_SPEAK.clear()
    _spawn(go)


def error_flash():
    ip, key, lights = _conn()
    if not ip:
        return

    def go():
        with _LOCK:
            saved = _light_states(ip, key, lights)
            for lid in lights:
                _put(ip, key, lid, {"on": True, "hue": 0, "sat": 254, "bri": 254, "alert": "select"})
            for lid, prev in saved.items():
                if prev:
                    _put(ip, key, lid, dict(prev, transitiontime=6))
    _spawn(go)


def focus(on):
    ip, key, lights = _conn()
    if not ip:
        return

    def go():
        with _LOCK:
            if on:
                _SAVED_FOCUS.clear()
                _SAVED_FOCUS.update(_light_states(ip, key, lights))
                for lid in lights:
                    _put(ip, key, lid, {"on": True, "hue": 8000, "sat": 140, "bri": 70,
                                        "transitiontime": 10})
            else:
                for lid, prev in _SAVED_FOCUS.items():
                    if prev:
                        _put(ip, key, lid, dict(prev, transitiontime=10))
                _SAVED_FOCUS.clear()
    _spawn(go)
