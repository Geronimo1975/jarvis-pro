// fx.js — V5 visual-effects bay for the Jarvis brain viewer.
// Loaded as the last module; the graph (__os) and the butler (__jarvis) are already at their posts.
// Everything in here is garnish — any single failure is swallowed and the viewer carries on unbothered.
// Hooks the host calls (all optional): __fx.audio(ev) · __fx.think(on) · __fx.wake() · __fx.brainTheme(model, isDefault)
import * as THREE from 'three';

const T0 = performance.now();
const now = () => (performance.now() - T0) / 1000;          // one clock for shaders, waves and fades
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const hex2rgb = h => { h = String(h || '').trim().replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
  const n = parseInt(h || '888888', 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const dim = (h, k) => { const [r, g, b] = hex2rgb(h); return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})`; };
const rgba = (h, a) => { const [r, g, b] = hex2rgb(h); return `rgba(${r},${g},${b},${a})`; };
const col3 = h => { const [r, g, b] = hex2rgb(h); return new THREE.Color(r / 255, g / 255, b / 255); };

// ---------------------------------------------------------------- shared state
let os = null, J = null, Graph = null, scene = null;
let booted = false, bootMs = 0;
let bloomPass = null, bloomBase = 1.1, bloomPulse = 0, bloomTau = 0.3;
let auraPts = null, auraGeo = null, auraMat = null, auraCap = 0, hitIds = null, dimTarget = 0, sonarTimer = 0;
let skyMesh = null, dustPts = null, dustN = 40000;
let coreGroup = null, coreMat = null, shaftMat = null, coreFade = 0, coreTarget = 0, thinkOn = false;
let savedParticles = null;                                   // the ORIGINAL accessor + speed, restored EXACTLY
let exploded = null;                                          // the current broken-down cluster, if any
const tweens = [];                                            // {node, from, to, t0, dur} — pinned-grid choreography
let glitchCtor = null;                                        // GlitchPass class, fetched lazily
let themeKey = 'default';
let ORIG = { hud: '#62dbff', hud2: '#2f9fd0', glow: 'rgba(70,200,255,.5)', accent: '#f4a93a' };
let voiceEnv = 0, voiceGate = 0, gateT = 0, flash = 0;
let fps = 0, fpsFrames = 0, fpsT = 0;

// palette per brain vendor — 'claude' wears the reactor's own stock colours (read from CSS at init)
const PALETTES = {
  grok:     { hud: '#ff5c5c', accent: '#ff8a3d' },
  gpt:      { hud: '#7de8d8', accent: '#e8f6f2' },
  gemini:   { hud: '#7aa2ff', accent: '#b58cff' },
  deepseek: { hud: '#b58cff', accent: '#ff7ad9' },
  // Fable 5 is the one Claude flagship with its own suit. Opus 5 wears the HOUSE cyan by
  // user decree (2026-07-28: it became the boot default and he kept the blue skin — the
  // 2026-07-21 molten-gold experiment is retired).
  fable5:   { hud: '#c084fc', accent: '#f0abfc' },     // violet
};
function vendorOf(model) {
  const s = String(model || '').toLowerCase();
  if (/grok|x-ai|xai\//.test(s)) return 'grok';
  if (/gpt|openai|\bo[134]\b/.test(s)) return 'gpt';
  if (/gemini|google/.test(s)) return 'gemini';
  if (/deepseek/.test(s)) return 'deepseek';
  if (/fable[-\s]?5\b/.test(s)) return 'fable5';      // must beat the generic claude test below
  if (/claude|anthropic|opus|sonnet|haiku|fable/.test(s)) return 'claude';
  return 'unknown';
}

// ---------------------------------------------------------------- public face (safe before init)
const FX = {
  audio(ev) { try {
    if (ev === 'speak_start') gateT = 1;
    else if (ev === 'speak_end') gateT = 0;
    else if (ev === 'error') { flash = 1; if (auraMat) auraMat.uniforms.uFlashColor.value.set(1, 0.22, 0.22); }
  } catch (e) {} },
  wake() { try {
    let origin = null;
    try { origin = Graph && Graph.controls().target.clone(); } catch (e) {}
    fireWave(origin || new THREE.Vector3(), themeCols.wave, { speed: 2600, thick: 110, maxR: 1800 });
    bloomPulse = Math.max(bloomPulse, 0.4); bloomTau = 0.11;                 // +0.4 flash, ~300ms decay
  } catch (e) {} },
  think(on) { try {
    on = !!on;
    if (on === thinkOn) return;
    thinkOn = on; coreTarget = on ? 1 : 0;
    if (!Graph) return;
    if (on) {
      if (!savedParticles) savedParticles = { fn: Graph.linkDirectionalParticles(), speed: Graph.linkDirectionalParticleSpeed() };
      Graph.linkDirectionalParticles(() => 3).linkDirectionalParticleSpeed(0.02);
    } else if (savedParticles) {
      // restore the ORIGINAL accessor fn — it reads the flow checkbox, so that keeps working
      Graph.linkDirectionalParticles(savedParticles.fn).linkDirectionalParticleSpeed(savedParticles.speed);
      savedParticles = null;
    }
  } catch (e) {} },
  brainTheme(model, isDefault) { try { applyTheme(model, isDefault); } catch (e) {} },
  // current suit, so the HUD chrome outside fx.js (brain chip, etc.) can match the ring
  palette() { const p = PALETTES[themeKey];
    return p ? { hud: p.hud, accent: p.accent, key: themeKey }
             : { hud: ORIG.hud || '#62dbff', accent: '#34d399', key: themeKey }; },
  sonar(ids) { try { sonarHits(ids); } catch (e) {} },
  state() {
    return { booted, bloom: bloomPass ? +(bloomPass.strength).toFixed(3) : 0, fps: Math.round(fps), theme: themeKey, bootMs,
      effects: { bloom: !!bloomPass, aura: !!auraPts, deepField: !!skyMesh, dust: !!dustPts, dustCount: dustN,
        core: !!coreGroup, thinking: thinkOn, sonar: dimTarget > 0, exploded: !!exploded,
        glitch: !!glitchCtor, routes: routesInstalled } };
  },
};
window.__fx = FX;
let routesInstalled = false;
const themeCols = { wave: col3('#34d399'), aura: col3('#34d399'), core: col3('#62dbff') };

// ================================================================ 1 · CINEMATIC BOOT — REMOVED per user (2026-07-06)
// The boot overlay is retired: the page loads straight into the stock viewer, no card, no typewriter.
// Do NOT re-enable without an explicit ask. (Body kept for reference; the guard below skips it entirely.)
(function bootSequence() {
  booted = true;                      // page is "booted" immediately — theme glitch-cuts stay armed
  if (true) return;                   // ← boot retired here
  try {
    const bootT0 = performance.now();
    const ov = document.createElement('div');
    ov.id = 'fx-boot';
    ov.innerHTML = `<style>
      #fx-boot{position:fixed;inset:0;z-index:200;background:#020409;display:flex;align-items:center;justify-content:center;
        font-family:'SF Mono',ui-monospace,monospace;transition:opacity .55s ease;cursor:pointer;}
      #fx-boot .fxb-rings{position:absolute;width:340px;height:340px;}
      #fx-boot .fxb-rings circle{fill:none;stroke-linecap:round;transition:stroke-dashoffset 2.5s cubic-bezier(.3,.6,.3,1);}
      #fx-boot pre{position:relative;z-index:1;margin:0;color:#62dbff;font-size:13px;line-height:2.05;letter-spacing:.08em;
        text-shadow:0 0 12px rgba(98,219,255,.5);min-width:340px;min-height:135px;}
      #fx-boot .fxb-cur{display:inline-block;width:8px;height:14px;background:#62dbff;vertical-align:-2px;animation:fxbc .7s steps(1) infinite;}
      @keyframes fxbc{50%{opacity:0;}}
      #fx-boot .fxb-skip{position:absolute;bottom:26px;left:50%;transform:translateX(-50%);color:#26414f;font-size:10px;letter-spacing:.2em;}
    </style>
    <svg class="fxb-rings" viewBox="0 0 200 200">
      <circle id="fxb-r1" cx="100" cy="100" r="88" stroke="#1c4f66" stroke-width="1.4"/>
      <circle id="fxb-r2" cx="100" cy="100" r="72" stroke="#34d399" stroke-width="1" opacity=".7"/>
    </svg>
    <pre id="fxb-type"></pre><div class="fxb-skip">CLICK TO SKIP</div>`;
    (document.body ? Promise.resolve() : new Promise(r => addEventListener('DOMContentLoaded', r))).then(() => {
      if (!document.body) return;
      document.body.appendChild(ov);
      // rings draw themselves
      for (const [id, r] of [['fxb-r1', 88], ['fxb-r2', 72]]) {
        const c = ov.querySelector('#' + id), C = (2 * Math.PI * r).toFixed(1);
        if (c) { c.style.strokeDasharray = C; c.style.strokeDashoffset = C;
          requestAnimationFrame(() => requestAnimationFrame(() => { c.style.strokeDashoffset = '0'; })); }
      }
    });
    // real checks, fetched in parallel; placeholders if the wires are slow — the 4s budget is sacred
    const vals = { model: 'STANDBY', voice: 'BROWSER', uplink: 'OFFLINE' };
    try { fetch('/api/model').then(r => r.json()).then(m => { if (m && m.model) vals.model = String(m.model).split('/').pop().toUpperCase(); }).catch(() => {}); } catch (e) {}
    try { fetch('/api/voice').then(r => r.json()).then(v => {
      if (v && v.voices && v.voices.length) vals.voice = (v.name && v.name !== 'default') ? v.name.split(' - ')[0].toUpperCase() : 'ELEVENLABS';
    }).catch(() => {}); } catch (e) {}
    try { fetch('/api/brand').then(r => { if (r.ok) vals.uplink = 'SECURE'; }).catch(() => {}); } catch (e) {}

    const pad = s => (s + ' ').padEnd(21, '.') + ' ';
    const lines = [
      () => pad('ARC REACTOR') + 'ONLINE',
      () => { let n = 0; try { n = window.__os.data.nodes.length; } catch (e) {} return pad('VAULT INDEX') + (n ? n + ' NOTES' : 'INDEXING'); },
      () => pad('BRAIN') + vals.model,
      () => pad('VOICE') + vals.voice,
      () => pad('UPLINK') + vals.uplink,
    ];
    const typeEl = () => ov.querySelector('#fxb-type');
    let done = false; const timers = [];
    const later = (fn, ms) => timers.push(setTimeout(fn, ms));
    function finish(skipped) {
      if (done) return; done = true;
      timers.forEach(clearTimeout);
      bootMs = Math.round(performance.now() - bootT0); booted = true;
      removeEventListener('keydown', onSkip, true);
      if (skipped) { ov.remove(); return; }                       // a click means "get on with it"
      ov.style.opacity = '0';
      try {                                                       // the galaxy ignites, centre-out
        bloomPulse = Math.max(bloomPulse, 1.4); bloomTau = 0.28;  // strength spikes ~2.5 → settles
        fireWave(new THREE.Vector3(), themeCols.wave, { speed: 950, thick: 150, maxR: 1900 });
      } catch (e) {}
      later(() => ov.remove(), 620);
    }
    const onSkip = () => finish(true);
    ov.addEventListener('pointerdown', onSkip);
    addEventListener('keydown', onSkip, true);
    // typewriter: ~250ms a line, five lines, start at 300ms → text done ~1.9s
    let t = 300;
    lines.forEach(mk => {
      later(() => {
        if (done) return; const el = typeEl(); if (!el) return;
        const txt = mk(); let i = 0; const base = el.textContent;
        const step = () => { if (done) return; i += 2; el.textContent = base + txt.slice(0, i) + (i < txt.length ? '' : '\n');
          if (i < txt.length) timers.push(setTimeout(step, Math.max(6, 230 / txt.length * 2))); };
        step();
      }, t);
      t += 310;
    });
    later(() => finish(false), 2950);                             // finale beat: fade + bloom spike + ignition
    later(() => { try { ov.remove(); } catch (e) {} }, 4200);     // watchdog — the card NEVER outstays 4.2s
  } catch (e) { booted = true; }
})();

// ================================================================ wait for the host, then arm everything
// (polled by setTimeout, not rAF — a hidden tab never fires rAF and we must arm regardless;
//  always deferred one beat so the module consts below finish initialising before init() runs)
function waitForHost(tries) {
  if (window.__os && window.__jarvis) { try { init(); } catch (e) { console.warn('fx: init failed —', e); } return; }
  if ((tries || 0) > 2400) return;                                // ~2 minutes and we bow out quietly
  setTimeout(() => waitForHost((tries || 0) + 1), 50);
}
setTimeout(() => waitForHost(0), 0);

function init() {
  os = window.__os; J = window.__jarvis; Graph = os.Graph; scene = Graph.scene();
  try { const cam = Graph.camera(); if (cam && cam.far < 8000) { cam.far = 8000; cam.updateProjectionMatrix(); } } catch (e) {}
  try { readOriginalTheme(); } catch (e) {}
  try { buildAura(); } catch (e) { console.warn('fx: aura skipped —', e); }
  // buildDeepField() + initBloom() RETIRED per user (2026-07-06): the landing look stays exactly stock —
  // no nebula skybox, no dust field, no bloom pass. (Code kept below for possible re-enable by request.)
  try { buildCore(); } catch (e) { console.warn('fx: core skipped —', e); }
  try { import('three/addons/postprocessing/GlitchPass.js').then(m => { glitchCtor = m.GlitchPass; }).catch(() => {}); } catch (e) {}
  try { installRoutes(); } catch (e) { console.warn('fx: routes skipped —', e); }
  startLoop();
}

// ================================================================ 2 · NEON BLOOM
async function initBloom() {
  try {
    if (typeof Graph.postProcessingComposer !== 'function') return; // older build — no composer, no bloom, no drama
    const composer = Graph.postProcessingComposer();
    if (!composer || !composer.addPass) return;
    const { UnrealBloomPass } = await import('three/addons/postprocessing/UnrealBloomPass.js');
    const el = Graph.renderer().domElement;
    const w = Math.max(2, el.clientWidth || el.width), h = Math.max(2, el.clientHeight || el.height);
    bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), bloomBase, 0.5, 0.1);
    composer.addPass(bloomPass);
  } catch (e) { bloomPass = null; console.warn('fx: bloom unavailable —', e); }
}

// ================================================================ 3 · AURA LAYER (one Points cloud, three effects)
// A halo point per node. uVoice makes the whole galaxy breathe out from the centre while Jarvis
// speaks (#18); two wavefront slots carry the wake ripple (#7) and the sonar sweep (#19).
const AURA_VERT = `
  attribute float aSize;
  attribute float aHit;
  attribute float aSeed;
  uniform float uPx;
  varying vec3 vPos; varying float vHit; varying float vSeed;
  void main(){
    vPos = position; vHit = aHit; vSeed = aSeed;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = clamp(aSize * (uPx / max(1.0, -mv.z)), 0.0, 72.0);
    gl_Position = projectionMatrix * mv;
  }`;
const AURA_FRAG = `
  uniform float uTime; uniform float uVoice; uniform vec3 uCenter; uniform vec3 uColor;
  uniform float uDim; uniform float uFlash; uniform vec3 uFlashColor;
  uniform vec3 uWOrigin[2]; uniform float uWStart[2]; uniform float uWSpeed[2]; uniform float uWThick[2]; uniform vec3 uWColor[2];
  varying vec3 vPos; varying float vHit; varying float vSeed;
  void main(){
    vec2 c = gl_PointCoord - 0.5;
    float d2 = dot(c, c);
    if (d2 > 0.25) discard;
    float sprite = pow(smoothstep(0.25, 0.0, d2), 1.6);
    // steady-state glow REMOVED per user (2026-07-06): no idle shimmer, no voice swell —
    // the halo layer is invisible at rest and only lights for wavefront events (wake ripple / sonar).
    float shimmer = 0.0;
    float swell = 0.0;
    float b = shimmer + swell;
    vec3 col = uColor * b;
    for (int i = 0; i < 2; i++) {                               // the two wavefront slots
      if (uWStart[i] < 0.0) continue;
      float r = (uTime - uWStart[i]) * uWSpeed[i];
      float band = 1.0 - smoothstep(0.0, uWThick[i], abs(distance(vPos, uWOrigin[i]) - r));
      float fade = clamp(1.0 - r / 1600.0, 0.0, 1.0);
      col += uWColor[i] * band * fade * 1.7;
      b += band * fade;
    }
    float flare = vHit * (0.9 + 0.5 * sin(uTime * 6.0));        // sonar verdict: hits flare…
    col *= mix(1.0, mix(0.15, 1.0 + flare, vHit), uDim);        // …misses sink to 15%
    col += uFlashColor * uFlash;
    col = min(col * sprite, vec3(1.6));
    gl_FragColor = vec4(col, sprite);
  }`;

function makeAuraArrays(cap) {
  const g = new THREE.BufferGeometry();
  const seed = new Float32Array(cap);
  for (let i = 0; i < cap; i++) seed[i] = Math.random();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(cap * 3), 3));
  g.setAttribute('aSize', new THREE.BufferAttribute(new Float32Array(cap), 1));
  g.setAttribute('aHit', new THREE.BufferAttribute(new Float32Array(cap), 1));
  g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  return g;
}
function buildAura() {
  auraCap = os.data.nodes.length + 64;
  auraGeo = makeAuraArrays(auraCap);
  auraMat = new THREE.ShaderMaterial({
    vertexShader: AURA_VERT, fragmentShader: AURA_FRAG,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 }, uVoice: { value: 0 }, uPx: { value: 300 },
      uCenter: { value: new THREE.Vector3() }, uColor: { value: themeCols.aura.clone() },
      uDim: { value: 0 }, uFlash: { value: 0 }, uFlashColor: { value: new THREE.Color(1, 0.22, 0.22) },
      uWOrigin: { value: [new THREE.Vector3(), new THREE.Vector3()] },
      uWStart: { value: [-1, -1] }, uWSpeed: { value: [900, 900] },
      uWThick: { value: [110, 110] }, uWColor: { value: [themeCols.wave.clone(), themeCols.wave.clone()] },
    },
  });
  auraPts = new THREE.Points(auraGeo, auraMat);
  auraPts.frustumCulled = false; auraPts.renderOrder = 2;
  scene.add(auraPts);
}
// two overlapping wavefronts, round-robin — a wake ripple mid-sonar is perfectly acceptable behaviour
function fireWave(origin, color, opt) {
  if (!auraMat) return;
  const o = opt || {}; const u = auraMat.uniforms;
  const slot = (u.uWStart.value[0] < 0) ? 0 : (u.uWStart.value[1] < 0) ? 1
    : (u.uWStart.value[0] <= u.uWStart.value[1] ? 0 : 1);
  u.uWOrigin.value[slot].copy(origin || new THREE.Vector3());
  u.uWStart.value[slot] = now();
  u.uWSpeed.value[slot] = o.speed || 900;
  u.uWThick.value[slot] = o.thick || 110;
  u.uWColor.value[slot].copy(color || themeCols.wave);
  u.uWColor.value[slot].__maxR = 0;                              // (kept simple — expiry below uses maxR list)
  waveMaxR[slot] = o.maxR || 1700;
}
const waveMaxR = [1700, 1700];
function sonarHits(ids) {
  hitIds = new Set((ids || []).map(Number).filter(i => i >= 0));
  const a = auraGeo && auraGeo.attributes.aHit;
  if (a) { const n = os.data.nodes.length;
    for (let i = 0; i < n && i < a.array.length; i++) a.array[i] = hitIds.has(i) ? 1 : 0;
    a.needsUpdate = true; }
  dimTarget = 1;
  clearTimeout(sonarTimer);
  sonarTimer = setTimeout(() => { dimTarget = 0;                 // verdict holds 12s, then the lights come back
    setTimeout(() => { hitIds = null; if (a) { a.array.fill(0); a.needsUpdate = true; } }, 900);
  }, 12000);
}

// ================================================================ 4 · DEEP FIELD (#11) — nebula skybox + dust
function buildDeepField() {
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(3600, 32, 24),
    new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: { uTime: { value: 0 },
        uCA: { value: new THREE.Color(0.11, 0.05, 0.19) },       // dark violet…
        uCB: { value: new THREE.Color(0.03, 0.13, 0.14) } },     // …to abyssal teal, ≤~12% luminance
      vertexShader: `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform vec3 uCA; uniform vec3 uCB; varying vec3 vP;
        float h3(vec3 p){ return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453); }
        float vn(vec3 p){ vec3 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
          float a=h3(i), b=h3(i+vec3(1,0,0)), c=h3(i+vec3(0,1,0)), d=h3(i+vec3(1,1,0));
          float e=h3(i+vec3(0,0,1)), g=h3(i+vec3(1,0,1)), hh=h3(i+vec3(0,1,1)), k=h3(i+vec3(1,1,1));
          return mix(mix(mix(a,b,f.x), mix(c,d,f.x), f.y), mix(mix(e,g,f.x), mix(hh,k,f.x), f.y), f.z); }
        float fbm(vec3 p){ float v=0.0, a=0.5; for(int i=0;i<3;i++){ v += a*vn(p); p *= 2.13; a *= 0.5; } return v; }
        void main(){
          vec3 d = normalize(vP);
          float n1 = fbm(d*3.0 + vec3(uTime*0.008, uTime*0.005, 0.0));
          float n2 = fbm(d*6.5 - vec3(0.0, uTime*0.006, uTime*0.004));
          float neb = smoothstep(0.42, 0.85, n1) * (0.45 + 0.55*n2);
          gl_FragColor = vec4(mix(uCA, uCB, n2) * neb * 0.85, 1.0);   // very quiet — the nodes are the heroes
        }`,
    }));
  sky.renderOrder = -1; sky.frustumCulled = false;
  scene.add(sky); skyMesh = sky;

  const pos = new Float32Array(dustN * 3);
  for (let i = 0; i < dustN; i++) {
    const r = 140 + Math.pow(Math.random(), 0.72) * 1500, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = r * Math.sin(ph) * Math.cos(th); pos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th); pos[i * 3 + 2] = r * Math.cos(ph);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  dustPts = new THREE.Points(g, new THREE.PointsMaterial({
    color: 0x5f7ea0, size: 1.5, sizeAttenuation: true, transparent: true, opacity: 0.10,
    blending: THREE.AdditiveBlending, depthWrite: false }));       // fog applies — dust sits IN the room
  dustPts.frustumCulled = false;
  scene.add(dustPts);
}

// ================================================================ 5 · THE CORE + SYNAPSE FIRE (#15+#8, "thinking")
function buildCore() {
  coreGroup = new THREE.Group();
  coreMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uOpacity: { value: 0 }, uColor: { value: themeCols.core.clone() } },
    vertexShader: `
      uniform float uTime; varying vec3 vN; varying vec3 vV;
      void main(){
        vec3 p = position + normal * (sin(uTime*2.2 + position.y*0.7 + position.x*0.5) * 0.8);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vN = normalMatrix * normal; vV = -mv.xyz;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform float uTime; uniform float uOpacity; uniform vec3 uColor; varying vec3 vN; varying vec3 vV;
      void main(){
        float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 1.7);
        float pulse = 0.72 + 0.28 * sin(uTime * 3.1);
        gl_FragColor = vec4(uColor * (f * 1.7 + 0.22) * pulse, uOpacity * (f + 0.16));
      }`,
  });
  coreGroup.add(new THREE.Mesh(new THREE.IcosahedronGeometry(16, 2), coreMat));

  // eight light shafts — fake god rays, a soft gradient sliver each, spun slowly by the loop
  const cv = document.createElement('canvas'); cv.width = 32; cv.height = 256;
  const cx = cv.getContext('2d');
  const grad = cx.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, 'rgba(255,255,255,0)'); grad.addColorStop(0.5, 'rgba(255,255,255,0.85)'); grad.addColorStop(1, 'rgba(255,255,255,0)');
  cx.fillStyle = grad; cx.fillRect(0, 0, 32, 256);
  const gx = cx.createLinearGradient(0, 0, 32, 0);
  gx.addColorStop(0, 'rgba(0,0,0,0)'); gx.addColorStop(0.5, 'rgba(0,0,0,1)'); gx.addColorStop(1, 'rgba(0,0,0,0)');
  cx.globalCompositeOperation = 'destination-in'; cx.fillStyle = gx; cx.fillRect(0, 0, 32, 256);
  const tex = new THREE.CanvasTexture(cv);
  shaftMat = new THREE.MeshBasicMaterial({ map: tex, color: themeCols.core.clone(), transparent: true, opacity: 0,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
  for (let i = 0; i < 8; i++) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(6, 260), shaftMat);
    p.rotation.y = (i / 8) * Math.PI; p.rotation.z = (Math.random() - 0.5) * 0.5;
    coreGroup.add(p);
  }
  coreGroup.visible = false;
  scene.add(coreGroup);
}

// ================================================================ 6 · GLITCH-CUT BRAIN THEME (#9)
function orbEl() { return document.getElementById('j-orb'); }
function readOriginalTheme() {
  const el = orbEl(); if (!el) return;
  const cs = getComputedStyle(el);
  const rd = (k, fb) => (cs.getPropertyValue(k) || '').trim() || fb;
  ORIG = { hud: rd('--hud', ORIG.hud), hud2: rd('--hud2', ORIG.hud2), glow: rd('--glow', ORIG.glow), accent: rd('--accent', ORIG.accent) };
}
function tintFx(hud, accent) {
  themeCols.core = col3(hud); themeCols.wave = col3(accent); themeCols.aura = col3(accent);
  try { if (coreMat) coreMat.uniforms.uColor.value.copy(themeCols.core); } catch (e) {}
  try { if (shaftMat) shaftMat.color.copy(themeCols.core); } catch (e) {}
  try { if (auraMat) auraMat.uniforms.uColor.value.copy(themeCols.aura); } catch (e) {}
}
function applyTheme(model, isDefault) {
  const v = vendorOf(model);
  // a brain with its OWN suit wears it even when it's the boot default (so making Opus 5 the
  // default doesn't quietly send the ring back to house colours)
  const key = PALETTES[v] ? v : (isDefault ? 'default' : v);
  if (key === 'unknown') return;                                  // an unrecognised brain keeps the current wardrobe
  if (key === themeKey) { paintTheme(key); return; }              // same suit — no theatrics
  const changed = themeKey; themeKey = key;
  paintTheme(key);
  if (booted && changed !== key) glitchCut();                     // the wardrobe change gets a hard cut
}
function paintTheme(key) {
  const el = orbEl(); if (!el) return;
  if (key === 'default' || key === 'claude') {                    // claude wears the house colours (from the CSS itself)
    ['--hud', '--hud2', '--glow', '--accent'].forEach(k => el.style.removeProperty(k));
    tintFx(ORIG.hud, '#34d399');                                  // fx defaults: house cyan + workshop emerald
    return;
  }
  const p = PALETTES[key]; if (!p) return;
  el.style.setProperty('--hud', p.hud);
  el.style.setProperty('--hud2', dim(p.hud, 0.62));
  el.style.setProperty('--glow', rgba(p.hud, 0.5));
  el.style.setProperty('--accent', p.accent);
  tintFx(p.hud, p.accent);
}
function glitchCut() {
  // (a) composer glitch, briefly wild
  try {
    if (glitchCtor && typeof Graph.postProcessingComposer === 'function') {
      const composer = Graph.postProcessingComposer();
      if (composer && composer.addPass) {
        const g = new glitchCtor(); g.goWild = true;
        composer.addPass(g);
        setTimeout(() => { try { composer.removePass ? composer.removePass(g) : composer.passes.splice(composer.passes.indexOf(g), 1); g.dispose && g.dispose(); } catch (e) {} }, 380);
      }
    }
  } catch (e) {}
  // (b) three sliced DOM bars with clip-path jitter + hue-rotate — the broadcast-interference look
  try {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;inset:0;z-index:190;pointer-events:none;';
    const bars = [];
    for (let i = 0; i < 3; i++) {
      const b = document.createElement('div');
      b.style.cssText = `position:absolute;left:0;right:0;top:${i * 33}%;height:34%;backdrop-filter:hue-rotate(${60 + i * 90}deg) saturate(2.4) contrast(1.2);`;
      wrap.appendChild(b); bars.push(b);
    }
    document.body.appendChild(wrap);
    const jit = setInterval(() => {
      for (const b of bars) {
        const dx = (Math.random() - 0.5) * 46;
        const a = Math.random() * 30, z = 70 + Math.random() * 30;
        b.style.transform = `translateX(${dx}px)`;
        b.style.clipPath = `polygon(0 ${a}%, 100% ${a}%, 100% ${z}%, 0 ${z}%)`;
      }
    }, 42);
    setTimeout(() => { clearInterval(jit); wrap.remove(); }, 420);
  } catch (e) {}
}

// ================================================================ 7 · EXPLODED VIEW (#20) + 8 · SONAR (#19) routes
function idOf(x) { return (x && x.id !== undefined) ? x.id : x; }
function bestNode(topic) {                                        // token-overlap scoring, same spirit as navigate()
  if (!os || !topic) return null;
  const t = String(topic).toLowerCase().replace(/\b(everything|about|my|the|all|on|stuff|notes?|node|note)\b/g, '').replace(/\s+/g, ' ').trim();
  const words = t.split(' ').filter(w => w.length > 1);
  if (!words.length) return null;
  let best = null, bs = 0;
  os.data.nodes.forEach(n => {
    const lab = String(n.label || '').toLowerCase(); let s = 0;
    words.forEach(w => { if (lab.indexOf(w) >= 0) s += 2; });
    if (lab === t) s += 6;
    if (s > bs) { bs = s; best = n; }
  });
  return bs > 0 ? best : null;
}
function unpin(reheat) {
  if (!exploded) return;
  tweens.length = 0;
  for (const n of exploded.nodes) { try { delete n.fx; delete n.fy; delete n.fz; } catch (e) {} }
  exploded = null;
  if (reheat !== false) { try { Graph.d3ReheatSimulation(); } catch (e) {} }
}
async function doBreakdown(topic) {
  const anchor = topic ? bestNode(topic) : (os.focusNode || null);
  if (!anchor) { await J.say(topic ? `I can't place "${topic}" in the vault, sir.` : 'Name a note, sir — or focus one — and I shall take it apart.'); return; }
  if (exploded) unpin(false);                                     // one exhibition at a time
  // 1-hop neighbours off the live link objects (source/target are node objects at runtime)
  const nbrs = []; const seen = new Set([anchor.id]);
  for (const l of os.data.links) {
    const s = idOf(l.source), t = idOf(l.target);
    const other = s === anchor.id ? t : t === anchor.id ? s : null;
    if (other != null && !seen.has(other)) { seen.add(other); const nd = os.data.nodes[other]; if (nd) nbrs.push(nd); }
    if (nbrs.length >= 24) break;
  }
  const items = [anchor, ...nbrs];
  // camera-facing grid centred on the anchor, ~40u spacing
  const cam = Graph.camera(); const m = cam.matrixWorld.elements;
  const right = new THREE.Vector3(m[0], m[1], m[2]).normalize();
  const up = new THREE.Vector3(m[4], m[5], m[6]).normalize();
  const centerP = new THREE.Vector3(anchor.x || 0, anchor.y || 0, anchor.z || 0);
  const S = 40, cols = Math.ceil(Math.sqrt(items.length)), rows = Math.ceil(items.length / cols);
  const cells = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) if (cells.length < items.length) cells.push([c, r]);
  let mid = 0, md = 1e9;                                          // the anchor takes the centre-most cell
  cells.forEach(([c, r], i) => { const d = Math.abs(c - (cols - 1) / 2) + Math.abs(r - (rows - 1) / 2); if (d < md) { md = d; mid = i; } });
  [cells[0], cells[mid]] = [cells[mid], cells[0]];
  const t0 = now();
  items.forEach((n, i) => {
    const [c, r] = cells[i];
    const to = centerP.clone()
      .addScaledVector(right, (c - (cols - 1) / 2) * S)
      .addScaledVector(up, ((rows - 1) / 2 - r) * S);
    tweens.push({ node: n, t0, dur: 1.0,
      from: { x: n.x || centerP.x, y: n.y || centerP.y, z: n.z || centerP.z },
      to: { x: to.x, y: to.y, z: to.z } });
  });
  exploded = { nodes: items, anchor };
  try { os.lightNodes(items.map(n => n.id)); } catch (e) {}
  try { Graph.d3ReheatSimulation(); } catch (e) {}                // hot sim honours the fx pins during the tween
  setTimeout(() => {                                              // then pull back to frame the exhibit
    try {
      const dir = new THREE.Vector3().subVectors(Graph.camera().position, centerP).normalize();
      const dist = Math.max(280, Math.max(cols, rows) * S * 1.5 + 180);
      const p = centerP.clone().addScaledVector(dir, dist);
      Graph.cameraPosition({ x: p.x, y: p.y, z: p.z }, { x: centerP.x, y: centerP.y, z: centerP.z }, 900);
    } catch (e) {}
  }, 1050);
  await J.say(`Broken down, sir — ${anchor.label}, ${nbrs.length} component${nbrs.length === 1 ? '' : 's'} on display. Say 'reassemble' when you're done.`);
}
async function doReassemble() {
  if (!exploded) { await J.say("Nothing's in pieces, sir — the vault is fully assembled."); return; }
  unpin(true);
  try { os.clearFocus(); } catch (e) {}
  await J.say('Reassembled, sir — every thought back where physics wants it. No screws left over.');
}
async function doSonar(topic) {
  let origin = new THREE.Vector3();
  try { if (auraMat) origin.copy(auraMat.uniforms.uCenter.value); } catch (e) {}
  fireWave(origin, themeCols.wave, { speed: 850, thick: 130, maxR: 1900 });
  J.status('● scanning the vault…');
  if (!topic) {                                                   // pure sweep — no model call, just theatre
    await new Promise(r => setTimeout(r, 1200));
    J.status('');
    let n = 0; try { n = os.data.nodes.length; } catch (e) {}
    await J.say(`Full-spectrum sweep complete, sir — all ${n} thoughts present and accounted for.`);
    return;
  }
  try {
    const d = await J.post('/chat', { question: 'what do I have on ' + topic, session: J.session }, 60000);
    J.status('');
    if (d && d.nodes && d.nodes.length) sonarHits(d.nodes);
    if (d && d.answer) { J.setLastNote(d.answer); await J.say(d.answer); }
    else if (d && d.error) await J.say(d.error);
    else await J.say('The sonar came back empty, sir.');
  } catch (e) { J.status(''); await J.say("The sonar came back empty, sir — the vault isn't answering."); }
}
function installRoutes() {
  window.__jarvisRoutes = window.__jarvisRoutes || [];
  window.__jarvisRoutes.push(
    { re: /^(?:jarvis[,!\s]+)?(?:scan|sweep) (?:the |my )?(?:vault|brain|graph|notes|mind)(?: for (.+?))?[?.!]*$/i,
      handler: async (q, m) => doSonar(((m && m[1]) || '').trim()) },
    { re: /(?:^|\b)(reassemble|put (?:it|them) back|collapse it)\b/i,
      handler: async () => doReassemble() },
    { re: /^(?!.*\b(?:website|web ?site|site|web ?page|homepage|landing page|url|domain|app|application|program|software|on my (?:mac|computer|pc|laptop)|dot (?:com|inc|io|ai|app|co|org|net)|\.(?:com|inc|io|ai|app|co|org|net|dev)\b)\b)(?:jarvis[,!\s]+)?break (?:it |that |this )?down[\s:,]*(.*)$/i,   // S29g: a site/app sentence belongs to the teardown organ
      handler: async (q, m) => doBreakdown(((m && m[1]) || '').trim()) },
    { re: /^(?:jarvis[,!\s]+)?(?:explode|unfold) (?:the |my )?(.+?)[?.!]*$/i,
      handler: async (q, m) => doBreakdown(((m && m[1]) || '').trim()) },
  );
  routesInstalled = true;
}

// ================================================================ 9/10 · THE ONE LOOP — envelope, waves, tweens, fps
// ONE loop, two drivers: rAF at full rate while the tab is visible, and an always-alive interval
// watchdog that keeps state ticking at ~10Hz when the tab is hidden (rAF simply stops firing there —
// and a rAF queued during a brief visible flicker would otherwise strand the chain forever).
const centroid = new THREE.Vector3();
let lastT = 0, lastTickMs = 0, loopStarted = false;
function startLoop() {
  if (loopStarted) return; loopStarted = true;
  const chain = ts => { loop(ts); requestAnimationFrame(chain); };
  try { requestAnimationFrame(chain); } catch (e) {}
  const stalled = () => { if (performance.now() - lastTickMs > 300) loop(performance.now()); };
  try {                                                           // worker timers dodge Chrome's hidden-tab
    const w = new Worker(URL.createObjectURL(new Blob(          //  intensive throttling (1 tick/min after 5 min)
      ['setInterval(function(){postMessage(0)},100)'], { type: 'text/javascript' })));
    w.onmessage = stalled;
  } catch (e) { setInterval(stalled, 100); }                      // plain interval if workers are off the menu
}
function loop(ts) {
  lastTickMs = performance.now();
  const t = now();
  const dt = Math.min(0.15, t - lastT || 0.016); lastT = t;
  fpsFrames++;
  if (ts - fpsT > 900) { fps = fpsFrames * 1000 / Math.max(1, ts - fpsT); fpsFrames = 0; fpsT = ts; }

  try {                                                           // voice envelope: eased, gated, never jittery
    voiceGate += (gateT - voiceGate) * Math.min(1, dt * 8);
    let lvl = (typeof window.__voiceLevel === 'number') ? window.__voiceLevel : 0;
    if (voiceGate > 0.5 && lvl < 0.02) lvl = 0.28 + 0.22 * Math.sin(t * 7.3);   // analyser-less TTS still breathes
    voiceEnv += (lvl * Math.max(voiceGate, lvl > 0.02 ? 1 : 0) - voiceEnv) * Math.min(1, dt * 9);
    flash = Math.max(0, flash - dt * 1.8);
  } catch (e) {}

  try {                                                           // bloom pulse decay (wake flash / boot ignition)
    if (bloomPass) { bloomPulse *= Math.exp(-dt / bloomTau); if (bloomPulse < 0.004) bloomPulse = 0;
      bloomPass.strength = bloomBase + bloomPulse; }
  } catch (e) {}

  try {                                                           // grid tweens → fx/fy/fz pins (physics-friendly)
    for (let i = tweens.length - 1; i >= 0; i--) {
      const w = tweens[i];
      const p = clamp((t - w.t0) / w.dur, 0, 1);
      const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;      // easeInOutCubic
      w.node.fx = w.from.x + (w.to.x - w.from.x) * e;
      w.node.fy = w.from.y + (w.to.y - w.from.y) * e;
      w.node.fz = w.from.z + (w.to.z - w.from.z) * e;
      if (p >= 1) tweens.splice(i, 1);
    }
  } catch (e) {}

  try {                                                           // aura sync: positions, sizes, centroid, uniforms
    if (auraPts && os) {
      const nodes = os.data.nodes;
      if (nodes.length > auraCap) {                               // the vault grew — give the halo more seats
        auraCap = nodes.length + 64;
        const g = makeAuraArrays(auraCap);
        auraGeo.dispose(); auraGeo = g; auraPts.geometry = g;
      }
      const pos = auraGeo.attributes.position.array, siz = auraGeo.attributes.aSize.array;
      let cx = 0, cy = 0, cz = 0, cN = 0;
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        if (Number.isFinite(n.x) && Number.isFinite(n.y) && Number.isFinite(n.z)) {
          pos[i * 3] = n.x; pos[i * 3 + 1] = n.y; pos[i * 3 + 2] = n.z;
          siz[i] = 6 + (n.val || 2) * 2.1;
          cx += n.x; cy += n.y; cz += n.z; cN++;
        } else siz[i] = 0;
      }
      auraGeo.attributes.position.needsUpdate = true;
      auraGeo.attributes.aSize.needsUpdate = true;
      auraGeo.setDrawRange(0, nodes.length);
      if (cN) { centroid.set(cx / cN, cy / cN, cz / cN); auraMat.uniforms.uCenter.value.lerp(centroid, 0.06); }
      const u = auraMat.uniforms;
      u.uTime.value = t; u.uVoice.value = voiceEnv; u.uFlash.value = flash;
      u.uDim.value += (dimTarget - u.uDim.value) * Math.min(1, dt * 5);
      for (let i = 0; i < 2; i++)                                 // retire spent wavefronts
        if (u.uWStart.value[i] >= 0 && (t - u.uWStart.value[i]) * u.uWSpeed.value[i] > waveMaxR[i]) u.uWStart.value[i] = -1;
      try {                                                       // perspective-correct point sizing
        const el = Graph.renderer().domElement, cam = Graph.camera();
        const h = el.clientHeight || el.height || 800;
        u.uPx.value = h / (2 * Math.tan((cam.fov || 50) * Math.PI / 360)) * 0.32;
      } catch (e) {}
    }
  } catch (e) {}

  try { if (skyMesh) skyMesh.material.uniforms.uTime.value = t; } catch (e) {}
  try { if (dustPts) dustPts.rotation.y = t * 0.004; } catch (e) {}

  try {                                                           // the core fades in/out around think()
    if (coreGroup) {
      coreFade += (coreTarget - coreFade) * Math.min(1, dt / 0.4 * 2.2);
      if (coreTarget === 0 && coreFade < 0.01) coreFade = 0;
      coreGroup.visible = coreFade > 0.01;
      if (coreGroup.visible) {
        coreGroup.position.copy(auraMat ? auraMat.uniforms.uCenter.value : centroid);
        coreGroup.rotation.y = t * 0.12; coreGroup.rotation.x = Math.sin(t * 0.21) * 0.18;
        const s = 1 + 0.07 * Math.sin(t * 3.2);
        coreGroup.scale.set(s, s, s);
        coreMat.uniforms.uTime.value = t; coreMat.uniforms.uOpacity.value = coreFade;
        shaftMat.opacity = 0.16 * coreFade;
      }
    }
  } catch (e) {}

  try {                                                           // headless-friendly: an FPS collapse halves the dust
    if (dustPts && !dustPts.__halved && fps > 1 && fps < 24 && ts > 20000) {
      dustPts.__halved = true; dustN = Math.floor(dustN / 2);
      dustPts.geometry.setDrawRange(0, dustN);
    }
  } catch (e) {}
}
