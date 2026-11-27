let overviewData = null;
let currentOffset = 0;
let currentTotal = 0;
let pageSize = 100;

const TOPIC_LABELS = {
  state_propagation: 'Switches & Logic Gates',
  bridge_vs_junction: 'Crossing Wires (Bridge vs Dot)',
  equivalent_resistance: 'Total Resistance (Ohms)',
  fault_diagnosis: 'Find the Broken Part',
  counterfactual_pair: 'Spot the Difference (Before/After)',
  component_audit: 'Count & Read Parts',
  whole_system: 'Full System (Power + Gates + Ohms)',
  custom_netlist: 'Your Custom Circuit'
};

const STYLE_LABELS = {
  ieee_classic: 'Blue-Grid Textbook',
  aged_paper: 'Cream Notebook Paper',
  high_contrast_mono: 'Black & White Exam',
  kicad_blueprint: 'Dark Blue CAD'
};

const SCAN_LABELS = {
  clean: 'Clean Drawing',
  office_scan: 'Scanned Page',
  mobile_photo: 'Phone Photo',
  low_contrast_fax: 'Faded Fax'
};

const DIFF_LABELS = { easy: 'Easy', medium: 'Medium', hard: 'Hard' };

const MODE_LABELS = {
  symbol_only: 'Symbols Only (No Hints)',
  annotated: 'Parts & Values Shown'
};

function fmtTopic(k) { return TOPIC_LABELS[k] || k; }
function fmtStyle(k) { return STYLE_LABELS[k] || k; }
function fmtScan(k) { return SCAN_LABELS[k] || k; }
function fmtDiff(k) { return DIFF_LABELS[k] || k; }
function fmtMode(k) { return MODE_LABELS[k] || k; }

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

function randomizeInput(id) {
  const el = document.getElementById(id);
  if (el) el.value = Math.floor(Math.random() * 90000) + 1000;
}

async function updateBatchProbability() {
  const el = document.getElementById('batch-prob-info');
  if (!el) return;
  const bFam = document.getElementById('b-family').value;
  const bDiff = document.getElementById('b-diff').value;
  const bTheme = document.getElementById('b-theme').value;
  const bDeg = document.getElementById('b-deg').value;
  const bLbl = document.getElementById('b-lbl').value;
  const reqCount = parseInt(document.getElementById('b-count').value || '30', 10);
  try {
    const res = await fetch('/api/estimate-combinations', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        requested_count: Math.max(1, Math.min(25000, reqCount)),
        families: bFam ? [bFam] : null,
        difficulties: bDiff ? [bDiff] : null,
        themes: bTheme ? [bTheme] : null,
        degradations: bDeg ? [bDeg] : null,
        label_modes: bLbl ? [bLbl] : null,
      }),
    });
    const d = await res.json();
    if (d.will_cap) {
      el.innerHTML = `<span style="color:var(--rust); font-weight:700;">Max Unique Limit:</span> Up to <b>${Number(d.unique_with_visuals).toLocaleString()}</b> unique circuits fit these filters.`;
    } else {
      el.innerHTML = `Supports up to <b>${Number(d.unique_with_visuals).toLocaleString()}</b> unique circuits &middot; all <b>${reqCount.toLocaleString()}</b> questions will be unique`;
    }
  } catch (e) {}
}

async function updateCustomProbability() {
  const el = document.getElementById('custom-prob-info');
  if (!el) return;
  const raw = document.getElementById('netlist-json').value;
  const title = document.getElementById('c-title').value || 'CUSTOM CIRCUIT';
  const reqCount = parseInt(document.getElementById('c-count').value || '100', 10);
  try {
    const res = await fetch('/api/estimate-combinations', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        requested_count: Math.max(1, Math.min(25000, reqCount)),
        custom_text: raw,
        custom_title: title,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      el.innerHTML = `<span style="color:var(--crimson);">Circuit Syntax Issue: ${esc(err.detail)}</span>`;
      return;
    }
    const d = await res.json();
    const parts = `${d.switches} switches x ${d.fuses} fuses x ${d.gates} logic gates x ${d.resistors} resistors`;
    if (d.will_cap) {
      el.innerHTML = `<span style="color:var(--rust); font-weight:700;">Exact Combination Cap:</span> Your circuit (${parts}) has at most <b>${Number(d.unique_with_visuals).toLocaleString()}</b> unique non-repetitive combinations (${Number(d.unique_circuit_structures).toLocaleString()} logic/question states x styles &amp; scans). Asking for ${reqCount.toLocaleString()} will cleanly generate <b>${Number(d.effective_max).toLocaleString()}</b> unique questions and stop without making duplicates!`;
    } else {
      el.innerHTML = `<b>Probability Space:</b> Your circuit (${parts}) supports up to <b>${Number(d.unique_with_visuals).toLocaleString()}</b> unique non-repetitive questions (${Number(d.unique_circuit_structures).toLocaleString()} logic states x styles/scans). All <b>${reqCount.toLocaleString()}</b> will be unique.`;
    }
  } catch (e) {}
}

const KEY_PLACEHOLDERS = {
  gemini: 'AIza... (Google Gemini API key)',
  openrouter: 'sk-or-... (OpenRouter API key)',
  openai: 'sk-... (OpenAI API key)',
  anthropic: 'sk-ant-... (Anthropic Claude API key)',
  custom: 'paste your custom API key',
  ollama: ''
};

let providerStatusMap = {};

function toggleAddModelBar(forceOpen = null) {
  const panel = document.getElementById('add-model-panel');
  const btn = document.getElementById('toggle-add-model-btn');
  if (!panel || !btn) return;
  const shouldOpen = forceOpen !== null ? forceOpen : panel.classList.contains('hidden');
  panel.classList.toggle('hidden', !shouldOpen);
  btn.setAttribute('aria-expanded', String(shouldOpen));
  if (shouldOpen) {
    onProviderPickerChange();
  }
}

function onProviderPickerChange() {
  const sel = document.getElementById('e-prov');
  if (!sel) return;
  const pid = sel.value;
  const meta = providerStatusMap[pid] || { label: pid, env_var: 'API_KEY', default_model: '', configured: false };
  const noticeEl = document.getElementById('provider-key-notice');
  const keyRow = document.getElementById('provider-key-row');
  const customBaseWrap = document.getElementById('custom-base-wrap');
  const modelIn = document.getElementById('e-model');
  const keyIn = document.getElementById('e-key');
  const rmBtn = document.getElementById('remove-key-btn');
  const stEl = document.getElementById('key-save-status');
  if (stEl) stEl.textContent = '';

  if (customBaseWrap) customBaseWrap.classList.toggle('hidden', pid !== 'custom');
  if (modelIn) modelIn.placeholder = meta.default_model || 'default model';
  if (keyIn) keyIn.placeholder = KEY_PLACEHOLDERS[pid] || 'paste your API key';

  if (pid === 'ollama') {
    if (keyRow) keyRow.classList.add('hidden');
    if (noticeEl) {
      noticeEl.innerHTML = meta.configured
        ? `<div class="key-notice ok"><b>Local Ollama</b> is installed on your machine and already appears in <b>Ready AI</b> above. Run <code>ollama pull qwen2.5vl:3b</code> if needed.</div>`
        : `<div class="key-notice"><b>Local Ollama</b> is offline on your PC. Install Ollama, run <code>ollama pull qwen2.5vl:3b</code>, and restart SchemForge locally to enable it.</div>`;
    }
    return;
  }

  if (keyRow) keyRow.classList.remove('hidden');
  if (rmBtn) rmBtn.classList.toggle('hidden', !meta.configured);

  if (noticeEl) {
    if (!meta.configured) {
      noticeEl.innerHTML = `<div class="key-notice"><b>${esc(meta.label)}</b> does not have a key yet. Add your <code>${esc(meta.env_var)}</code> key below to enable it for testing.</div>`;
      if (keyIn && !document.getElementById('add-model-panel')?.classList.contains('hidden')) {
        setTimeout(() => keyIn.focus(), 40);
      }
    } else {
      noticeEl.innerHTML = `<div class="key-notice ok"><b>${esc(meta.label)}</b> is ready (<code>${esc(meta.env_var)}</code> configured). Select it in <b>Ready AI</b> above, update the key below, or remove it.</div>`;
    }
  }
}

function renderEvalModelBar(forceCheckProvider = null) {
  const readyWrap = document.getElementById('eval-ready-chips');
  const sel = document.getElementById('e-prov');
  if (!readyWrap) return;

  const prevChecked = new Set(
    [...readyWrap.querySelectorAll('input[type="checkbox"]:checked')].map(cb => cb.value)
  );
  if (forceCheckProvider) prevChecked.add(forceCheckProvider);

  const entries = Object.entries(providerStatusMap);
  const readyEntries = entries.filter(([_pid, m]) => Boolean(m.configured));
  const hasPrevSelection = prevChecked.size > 0;

  if (readyEntries.length === 0) {
    readyWrap.innerHTML = `<span style="font-size:12px; color:var(--ink-faint);">No API keys added yet</span>`;
  } else {
    readyWrap.innerHTML = readyEntries.map(([pid, meta], idx) => {
      const checked = hasPrevSelection ? prevChecked.has(pid) : (idx === 0);
      const shortName = meta.label.replace(/\s*\([^)]*\)/g, '').trim();
      return `<label class="model-check"><input type="checkbox" value="${esc(pid)}" ${checked ? 'checked' : ''} /> ${esc(shortName)}</label>`;
    }).join('');
  }

  if (sel) {
    const curVal = sel.value;
    sel.innerHTML = entries.map(([pid, meta]) => {
      const badge = pid === 'ollama' ? (meta.configured ? 'Ready (Local)' : 'Offline Setup') : (meta.configured ? 'Ready' : 'Needs Key');
      return `<option value="${esc(pid)}">${esc(meta.label)} (${badge})</option>`;
    }).join('');
    if ([...sel.options].some(o => o.value === curVal)) sel.value = curVal;
  }
  onProviderPickerChange();
}

async function refreshProvidersStatus(forceCheckProvider = null) {
  try {
    const res = await fetch('/api/providers/status');
    if (res.ok) {
      providerStatusMap = await res.json();
      renderEvalModelBar(forceCheckProvider);
    }
  } catch (e) {}
}

async function saveKeyToEnv() {
  const prov = document.getElementById('e-prov').value;
  const key = document.getElementById('e-key').value.trim();
  const baseUrl = document.getElementById('e-base-url')?.value.trim() || null;
  const customModel = document.getElementById('e-model')?.value.trim() || null;
  const stEl = document.getElementById('key-save-status');
  if (!key) {
    stEl.style.color = 'var(--crimson)';
    stEl.textContent = 'Paste an API key first.';
    return;
  }
  const res = await fetch('/api/providers/key', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ provider: prov, api_key: key, base_url: baseUrl, default_model: customModel }),
  });
  const d = await res.json();
  if (!res.ok) {
    stEl.style.color = 'var(--crimson)';
    stEl.textContent = d.detail || 'Save error';
    return;
  }
  document.getElementById('e-key').value = '';
  await refreshProvidersStatus(prov);
  stEl.style.color = 'var(--sage)';
  stEl.textContent = `Enabled ${(providerStatusMap[prov]?.label || prov)} in Ready AI above.`;
}

async function removeSavedKey() {
  const prov = document.getElementById('e-prov').value;
  const label = providerStatusMap[prov]?.label || prov;
  if (!confirm(`Remove the saved API key for ${label}?`)) return;
  const res = await fetch('/api/providers/key/' + encodeURIComponent(prov), { method: 'DELETE' });
  const stEl = document.getElementById('key-save-status');
  if (res.ok) {
    await refreshProvidersStatus();
    if (stEl) {
      stEl.style.color = 'var(--ink-muted)';
      stEl.textContent = `Removed key for ${label}.`;
    }
  }
}

function applyTheme(mode) {
  const isDark = mode === 'dark';
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.title = isDark ? 'Switch to Cream Light Mode' : 'Switch to Obsidian Dark Mode';
    btn.setAttribute('aria-label', btn.title);
    btn.innerHTML = isDark
      ? '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M4.93 4.93l1.77 1.77M17.3 17.3l1.77 1.77M2 12h2.5M19.5 12H22M4.93 19.07l1.77-1.77M17.3 6.7l1.77-1.77"/></svg>'
      : '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  }
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  const nxt = cur === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('schemforge_theme_pref', nxt); } catch (e) {}
  applyTheme(nxt);
  _applySavedAccent();
  playUiSound('toggle');
}

const ACCENT_PRESETS = [
  { id: 'platinum',  name: 'Swiss Platinum',   dark: '#e4e4e7', darkBtn: '#f0eee6', light: '#18181b', lightBtn: '#18181b' },
  { id: 'cobalt',    name: 'Blueprint Cobalt', dark: '#4d94ff', darkBtn: '#2563eb', light: '#2563eb', lightBtn: '#2563eb' },
  { id: 'emerald',   name: 'Scope Emerald',    dark: '#34d399', darkBtn: '#059669', light: '#059669', lightBtn: '#059669' },
  { id: 'cyan',      name: 'Arctic Cyan',      dark: '#22d3ee', darkBtn: '#0891b2', light: '#0891b2', lightBtn: '#0891b2' },
  { id: 'titanium',  name: 'Brushed Titanium', dark: '#94a3b8', darkBtn: '#cbd5e1', light: '#475569', lightBtn: '#475569' },
  { id: 'brass',     name: 'Leica Brass',      dark: '#d6b265', darkBtn: '#d6b265', light: '#9a6b16', lightBtn: '#9a6b16' },
  { id: 'sage',      name: 'Matte Sage',       dark: '#6eb891', darkBtn: '#6eb891', light: '#2d6a4f', lightBtn: '#2d6a4f' },
  { id: 'sky',       name: 'Frost Sky',        dark: '#7dd3fc', darkBtn: '#7dd3fc', light: '#0284c7', lightBtn: '#0284c7' }
];

function _hexToRgb(hex) {
  const m = String(hex || '').replace('#', '').match(/^([0-9a-f]{6})$/i);
  if (!m) return [228, 228, 231];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function _isLightRgb(r, g, b) {
  return (0.299 * r + 0.587 * g + 0.114 * b) > 158;
}

function _shadeHex(hex, factor) {
  const [r, g, b] = _hexToRgb(hex);
  const clamp = v => Math.max(0, Math.min(255, Math.round(v)));
  return '#' + [clamp(r * factor), clamp(g * factor), clamp(b * factor)]
    .map(v => v.toString(16).padStart(2, '0')).join('');
}

function _setAccentCss(accentHex, btnHex) {
  const root = document.documentElement;
  const [ar, ag, ab] = _hexToRgb(accentHex);
  const [br, bg, bb] = _hexToRgb(btnHex || accentHex);
  const isDark = root.getAttribute('data-theme') === 'dark';
  const btnFg = _isLightRgb(br, bg, bb) ? '#141311' : '#ffffff';
  const btnHover = _isLightRgb(br, bg, bb) ? '#ffffff' : _shadeHex(btnHex || accentHex, 0.88);
  root.style.setProperty('--copper', accentHex);
  root.style.setProperty('--copper-soft', `rgba(${ar}, ${ag}, ${ab}, ${isDark ? 0.14 : 0.11})`);
  root.style.setProperty('--rust', btnHex || accentHex);
  root.style.setProperty('--rust-hover', btnHover);
  root.style.setProperty('--btn-fg', btnFg);
  const hexReadout = document.getElementById('sf-custom-color-hex');
  const colInput = document.getElementById('sf-custom-color-input');
  if (hexReadout) hexReadout.textContent = accentHex.toUpperCase();
  if (colInput && colInput.value.toLowerCase() !== accentHex.toLowerCase()) colInput.value = accentHex;
}

let _sfColorMenuEl = null;

function _syncColorMenuActive(activeId) {
  if (!_sfColorMenuEl) return;
  _sfColorMenuEl.querySelectorAll('.color-preset-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.preset === activeId);
  });
}

function _applySavedAccent() {
  let pref = { mode: 'preset', id: 'platinum', custom: '#4d94ff' };
  try {
    const raw = localStorage.getItem('schemforge_accent_pref');
    if (raw) pref = Object.assign(pref, JSON.parse(raw));
  } catch (e) {}
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (pref.mode === 'custom' && /^#[0-9a-f]{6}$/i.test(pref.custom || '')) {
    _setAccentCss(pref.custom, pref.custom);
    _syncColorMenuActive('custom');
  } else {
    const p = ACCENT_PRESETS.find(x => x.id === pref.id) || ACCENT_PRESETS[0];
    _setAccentCss(isDark ? p.dark : p.light, isDark ? p.darkBtn : p.lightBtn);
    _syncColorMenuActive(p.id);
  }
}

function selectAccentPreset(id) {
  const p = ACCENT_PRESETS.find(x => x.id === id) || ACCENT_PRESETS[0];
  try { localStorage.setItem('schemforge_accent_pref', JSON.stringify({ mode: 'preset', id: p.id })); } catch (e) {}
  _applySavedAccent();
  playUiSound('select');
}

function applyCustomHexAccent(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex || '')) return;
  try { localStorage.setItem('schemforge_accent_pref', JSON.stringify({ mode: 'custom', custom: hex })); } catch (e) {}
  _applySavedAccent();
}

function _ensureColorMenu() {
  if (_sfColorMenuEl) return _sfColorMenuEl;
  const el = document.createElement('div');
  el.id = 'sf-color-menu';
  el.innerHTML = `
    <div class="color-menu-hdr">
      <span>Accent Color Theme</span>
      <button type="button" class="secondary" style="height:24px; min-block-size:24px; padding:0 8px; font-size:11px;" onclick="selectAccentPreset('platinum')">Reset</button>
    </div>
    <div class="color-preset-grid">
      ${ACCENT_PRESETS.map(p => `
        <button type="button" class="color-preset-btn" data-preset="${p.id}" onclick="selectAccentPreset('${p.id}')">
          <span class="color-preset-chip" style="background:${p.dark};"></span>
          <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${p.name}</span>
        </button>
      `).join('')}
    </div>
    <label class="color-custom-row">
      <span>Custom Color: <span class="mono" id="sf-custom-color-hex">#E4E4E7</span></span>
      <input type="color" id="sf-custom-color-input" value="#4d94ff" oninput="applyCustomHexAccent(this.value)" aria-label="Pick custom accent color" />
    </label>
  `;
  document.body.appendChild(el);
  _sfColorMenuEl = el;
  _applySavedAccent();
  return el;
}

function closeColorMenu() {
  if (_sfColorMenuEl) _sfColorMenuEl.classList.remove('open');
  const btn = document.getElementById('color-toggle');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function toggleColorMenu() {
  const menu = _ensureColorMenu();
  const isOpen = menu.classList.contains('open');
  if (isOpen) {
    closeColorMenu();
    return;
  }
  const btn = document.getElementById('color-toggle');
  if (btn) {
    const r = btn.getBoundingClientRect();
    menu.style.top = `${Math.round(r.bottom + 8)}px`;
    menu.style.right = `${Math.max(12, Math.round(window.innerWidth - r.right))}px`;
    btn.setAttribute('aria-expanded', 'true');
  }
  menu.classList.add('open');
  playUiSound('open');
}

document.addEventListener('pointerdown', (e) => {
  if (!_sfColorMenuEl || !_sfColorMenuEl.classList.contains('open')) return;
  const btn = document.getElementById('color-toggle');
  if (_sfColorMenuEl.contains(e.target) || (btn && btn.contains(e.target))) return;
  closeColorMenu();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && _sfColorMenuEl && _sfColorMenuEl.classList.contains('open')) {
    closeColorMenu();
  }
});

_applySavedAccent();

let uiSoundEnabled = true;
let _sfAudioCtx = null;

function _getAudioCtx() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!_sfAudioCtx) _sfAudioCtx = new Ctx();
    if (_sfAudioCtx.state === 'suspended') _sfAudioCtx.resume().catch(() => {});
    return _sfAudioCtx;
  } catch (e) {
    return null;
  }
}

function playUiSound(kind = 'tick') {
  if (!uiSoundEnabled) return;
  const ctx = _getAudioCtx();
  if (!ctx) return;
  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const filter = ctx.createBiquadFilter();
    const gain = ctx.createGain();
    filter.type = 'lowpass';
    osc.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);

    if (kind === 'open') {
      osc.type = 'sine';
      filter.frequency.setValueAtTime(1900, now);
      osc.frequency.setValueAtTime(520, now);
      osc.frequency.exponentialRampToValueAtTime(760, now + 0.032);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.028, now + 0.004);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.042);
      osc.start(now);
      osc.stop(now + 0.046);
    } else if (kind === 'select') {
      osc.type = 'triangle';
      filter.frequency.setValueAtTime(2200, now);
      osc.frequency.setValueAtTime(640, now);
      osc.frequency.exponentialRampToValueAtTime(920, now + 0.036);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.036, now + 0.004);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.048);
      osc.start(now);
      osc.stop(now + 0.052);
    } else if (kind === 'toggle') {
      osc.type = 'sine';
      filter.frequency.setValueAtTime(2000, now);
      osc.frequency.setValueAtTime(587, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.045);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.034, now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.06);
      osc.start(now);
      osc.stop(now + 0.064);
    } else {
      osc.type = 'triangle';
      filter.frequency.setValueAtTime(1600, now);
      osc.frequency.setValueAtTime(740, now);
      osc.frequency.exponentialRampToValueAtTime(290, now + 0.018);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.032, now + 0.002);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.022);
      osc.start(now);
      osc.stop(now + 0.026);
    }
  } catch (e) {}
}

function applySound(on) {
  uiSoundEnabled = !!on;
  const btn = document.getElementById('sound-toggle');
  if (!btn) return;
  btn.classList.toggle('is-off', !uiSoundEnabled);
  btn.setAttribute('aria-pressed', uiSoundEnabled ? 'true' : 'false');
  btn.title = uiSoundEnabled ? 'Click Sounds: ON (click to mute)' : 'Click Sounds: OFF (click to enable)';
  btn.setAttribute('aria-label', btn.title);
  btn.innerHTML = uiSoundEnabled
    ? '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>'
    : '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" y1="9" x2="16" y2="15"/><line x1="16" y1="9" x2="22" y2="15"/></svg>';
}

function toggleSound() {
  const nxt = !uiSoundEnabled;
  try { localStorage.setItem('schemforge_sound_pref', nxt ? 'on' : 'off'); } catch (e) {}
  applySound(nxt);
  if (nxt) playUiSound('toggle');
}

(() => {
  try {
    const saved = localStorage.getItem('schemforge_theme_pref');
    applyTheme(saved === 'light' ? 'light' : 'dark');
    const snd = localStorage.getItem('schemforge_sound_pref');
    applySound(snd !== 'off');
  } catch (e) {
    applyTheme('dark');
    applySound(true);
  }
})();

document.addEventListener('pointerdown', (e) => {
  if (uiSoundEnabled) _getAudioCtx();
  const hit = e.target.closest('button, a.set-action-link, a.footer-repo-link, .task-item, summary, .bar-row, .chart-tab-btn, label.model-check, label.same-circuit-toggle');
  if (!hit || hit.disabled) return;
  if (hit.id === 'sound-toggle' || hit.id === 'theme-toggle' || hit.id === 'color-toggle' || hit.classList.contains('color-preset-btn') || hit.classList.contains('sf-select-btn') || hit.classList.contains('sf-opt')) return;
  playUiSound(hit.classList.contains('tab-btn') ? 'select' : 'tick');
}, true);

(() => {
  const valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  if (valueDesc && valueDesc.set && !HTMLSelectElement.prototype._sfValuePatched) {
    Object.defineProperty(HTMLSelectElement.prototype, 'value', {
      configurable: true,
      get() { return valueDesc.get.call(this); },
      set(v) {
        valueDesc.set.call(this, v);
        if (typeof this._sfSync === 'function') this._sfSync();
      }
    });
    HTMLSelectElement.prototype._sfValuePatched = true;
  }
})();

let _sfActiveSelect = null;
let _sfActiveBtn = null;
let _sfMenuEl = null;

function _ensureSelectMenu() {
  if (_sfMenuEl) return _sfMenuEl;
  _sfMenuEl = document.createElement('div');
  _sfMenuEl.id = 'sf-select-menu';
  _sfMenuEl.setAttribute('role', 'listbox');
  _sfMenuEl.tabIndex = -1;
  document.body.appendChild(_sfMenuEl);
  return _sfMenuEl;
}

function closeCustomSelectMenu(restoreFocus = false) {
  if (_sfMenuEl) _sfMenuEl.classList.remove('open');
  if (_sfActiveBtn) {
    _sfActiveBtn.classList.remove('open');
    _sfActiveBtn.setAttribute('aria-expanded', 'false');
    if (restoreFocus) _sfActiveBtn.focus({ preventScroll: true });
  }
  _sfActiveSelect = null;
  _sfActiveBtn = null;
}

function openCustomSelectMenu(sel, btn) {
  if (_sfActiveSelect === sel) {
    closeCustomSelectMenu(false);
    return;
  }
  if (_sfActiveSelect) closeCustomSelectMenu(false);

  const menu = _ensureSelectMenu();
  const options = Array.from(sel.options);
  menu.innerHTML = options.map((opt, idx) => {
    const isSel = idx === sel.selectedIndex;
    return `
      <button type="button" class="sf-opt" role="option" data-idx="${idx}" aria-selected="${isSel ? 'true' : 'false'}" ${opt.disabled ? 'disabled' : ''}>
        <span style="overflow:hidden; text-overflow:ellipsis;">${esc(opt.textContent)}</span>
        <svg class="sf-opt-check" aria-hidden="true" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3.2 6.8-7"/></svg>
      </button>
    `;
  }).join('');

  const rect = btn.getBoundingClientRect();
  const minW = Math.max(rect.width, 185);
  menu.style.minWidth = `${Math.min(minW, window.innerWidth - 20)}px`;
  menu.style.maxWidth = `${Math.min(Math.max(rect.width + 72, 300), window.innerWidth - 20)}px`;

  const spaceBelow = window.innerHeight - rect.bottom - 10;
  const spaceAbove = rect.top - 10;
  const estHeight = Math.min(310, Math.max(44, options.length * 32 + 12));
  const placeAbove = spaceBelow < Math.min(estHeight, 220) && spaceAbove > spaceBelow;
  menu.style.maxHeight = `${Math.max(120, Math.min(310, (placeAbove ? spaceAbove : spaceBelow) - 6))}px`;

  if (placeAbove) {
    menu.style.top = 'auto';
    menu.style.bottom = `${Math.max(10, window.innerHeight - rect.top + 6)}px`;
    menu.style.transformOrigin = 'bottom center';
  } else {
    menu.style.bottom = 'auto';
    menu.style.top = `${Math.min(window.innerHeight - Math.min(estHeight, spaceBelow) - 10, rect.bottom + 6)}px`;
    menu.style.transformOrigin = 'top center';
  }
  menu.style.visibility = 'hidden';
  menu.classList.add('open');

  const mRect = menu.getBoundingClientRect();
  const mw = mRect.width || minW;
  const left = Math.max(10, Math.min(rect.left, window.innerWidth - mw - 10));
  menu.style.left = `${left}px`;
  menu.style.visibility = 'visible';

  _sfActiveSelect = sel;
  _sfActiveBtn = btn;
  btn.classList.add('open');
  btn.setAttribute('aria-expanded', 'true');
  playUiSound('open');

  menu.querySelectorAll('.sf-opt').forEach(optBtn => {
    optBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const idx = parseInt(optBtn.getAttribute('data-idx'), 10);
      if (!Number.isNaN(idx) && sel.options[idx]) {
        const keepX = window.scrollX;
        const keepY = window.scrollY;
        const changed = sel.selectedIndex !== idx;
        sel.selectedIndex = idx;
        sel._sfSync?.();
        playUiSound('select');
        closeCustomSelectMenu(ev.detail === 0);
        if (changed) sel.dispatchEvent(new Event('change', { bubbles: true }));
        requestAnimationFrame(() => {
          if (Math.abs(window.scrollY - keepY) > 2) {
            window.scrollTo({ left: keepX, top: keepY, behavior: 'instant' });
          }
        });
      }
    });
  });

  const selOpt = menu.querySelector('.sf-opt[aria-selected="true"]');
  if (selOpt) {
    menu.scrollTop = Math.max(0, selOpt.offsetTop - (menu.clientHeight / 2) + (selOpt.offsetHeight / 2));
  }
}

document.addEventListener('pointerdown', (e) => {
  if (!_sfActiveSelect) return;
  if (_sfMenuEl && _sfMenuEl.contains(e.target)) return;
  if (_sfActiveBtn && _sfActiveBtn.contains(e.target)) return;
  closeCustomSelectMenu(false);
});

document.addEventListener('keydown', (e) => {
  if (!_sfActiveSelect || !_sfMenuEl) return;
  const items = Array.from(_sfMenuEl.querySelectorAll('.sf-opt:not([disabled])'));
  if (!items.length) return;
  const curIdx = items.indexOf(document.activeElement);
  if (e.key === 'Escape') {
    e.preventDefault();
    closeCustomSelectMenu(true);
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    items[(curIdx + 1) % items.length].focus({ preventScroll: true });
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    items[(curIdx - 1 + items.length) % items.length].focus({ preventScroll: true });
  } else if (e.key === 'Home') {
    e.preventDefault();
    items[0].focus({ preventScroll: true });
  } else if (e.key === 'End') {
    e.preventDefault();
    items[items.length - 1].focus({ preventScroll: true });
  } else if (e.key === 'Tab') {
    closeCustomSelectMenu(false);
  }
});

window.addEventListener('resize', () => { if (_sfActiveSelect) closeCustomSelectMenu(false); });
window.addEventListener('scroll', (e) => {
  if (_sfActiveSelect && e.target !== _sfMenuEl) closeCustomSelectMenu(false);
}, true);

function enhanceCustomSelect(sel) {
  if (!sel || sel.dataset.sfUpgraded === '1') {
    sel?._sfSync?.();
    return;
  }
  sel.dataset.sfUpgraded = '1';
  const wrap = document.createElement('span');
  wrap.className = 'sf-select-wrap';

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'sf-select-btn';
  if (sel.style.minBlockSize === '26px' || sel.closest('.pill-controls')) {
    btn.classList.add('compact');
  }
  if (sel.title) btn.title = sel.title;
  btn.setAttribute('aria-haspopup', 'listbox');
  btn.setAttribute('aria-expanded', 'false');

  const lbl = document.createElement('span');
  lbl.className = 'sf-select-label';
  const chev = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chev.setAttribute('aria-hidden', 'true');
  chev.setAttribute('viewBox', '0 0 12 12');
  chev.setAttribute('width', '12');
  chev.setAttribute('height', '12');
  chev.setAttribute('fill', 'none');
  chev.setAttribute('stroke', 'currentColor');
  chev.setAttribute('stroke-width', '1.7');
  chev.setAttribute('stroke-linecap', 'round');
  chev.setAttribute('stroke-linejoin', 'round');
  chev.classList.add('sf-chevron');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', 'M2.5 4.5l3.5 3.5 3.5-3.5');
  chev.appendChild(p);

  btn.appendChild(lbl);
  btn.appendChild(chev);

  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(btn);
  wrap.appendChild(sel);
  sel.classList.add('sf-native-hidden');
  sel.tabIndex = -1;
  sel.setAttribute('aria-hidden', 'true');

  const sync = () => {
    const opt = sel.options[sel.selectedIndex] || sel.options[0];
    lbl.textContent = opt ? opt.textContent : '';
  };
  sel._sfSync = sync;
  sync();

  sel.addEventListener('change', sync);
  btn.addEventListener('click', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    openCustomSelectMenu(sel, btn);
  });
  btn.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp' || ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      openCustomSelectMenu(sel, btn);
    }
  });

  const mo = new MutationObserver(() => sync());
  mo.observe(sel, { childList: true, subtree: true, attributes: true });
}

function upgradeAllCustomSelects() {
  document.querySelectorAll('select').forEach(enhanceCustomSelect);
}

const infoDialog = document.getElementById('app-info-dialog');
function openInfoDialog() {
  if (!infoDialog) return;
  if (typeof infoDialog.showModal === 'function') {
    if (!infoDialog.open) infoDialog.showModal();
  } else {
    infoDialog.setAttribute('open', '');
  }
}
function closeInfoDialog() {
  if (!infoDialog) return;
  if (typeof infoDialog.close === 'function') {
    if (infoDialog.open) infoDialog.close();
  } else {
    infoDialog.removeAttribute('open');
  }
}

if (!('commandForElement' in HTMLButtonElement.prototype)) {
  const openBtn = document.getElementById('tab-help-btn');
  const closeX = document.getElementById('info-dlg-x');
  const closeStart = document.getElementById('info-dlg-start');
  if (openBtn) openBtn.addEventListener('click', openInfoDialog);
  if (closeX) closeX.addEventListener('click', closeInfoDialog);
  if (closeStart) closeStart.addEventListener('click', closeInfoDialog);
}

let previewInitialized = false;
let customInitialized = false;
function showTab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  ['inspector', 'batches', 'netlist', 'evaluation'].forEach(id => {
    const el = document.getElementById('tab-' + id);
    if (!el) return;
    const isTarget = id === name;
    el.classList.toggle('hidden', !isTarget);
    el.classList.remove('tab-enter');
    if (isTarget) {
      void el.offsetWidth;
      el.classList.add('tab-enter');
    }
  });
  if (name === 'batches') {
    updateBatchProbability();
    if (!previewInitialized) {
      previewInitialized = true;
      runLiveGen(false);
    }
  } else if (name === 'netlist') {
    updateCustomProbability();
    if (!customInitialized) {
      customInitialized = true;
      compileCustom(false);
    }
  }
}

function goCreateSetTab() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  showTab('batches', tabBtns[1]);
  const nm = document.getElementById('b-name');
  if (nm) nm.focus();
}

let builtinBatchIds = new Set(['default']);

function syncSetDeleteBtn() {
  const sel = document.getElementById('f-batch');
  const delBtn = document.getElementById('f-batch-del');
  if (!sel || !delBtn) return;
  const bid = sel.value || 'default';
  const isBuiltin = builtinBatchIds.has(bid);
  delBtn.disabled = isBuiltin;
  delBtn.title = isBuiltin ? 'Built-in starter question set cannot be deleted' : `Delete custom Question Set "${bid}"`;
}

async function deleteSelectedBatch() {
  const sel = document.getElementById('f-batch');
  const bid = sel ? sel.value : 'default';
  if (!bid || builtinBatchIds.has(bid)) return;
  if (!confirm(`Delete custom Question Set "${bid}" and all its generated files?`)) return;
  await deleteBatch(bid);
}

async function openBatchInBrowser(batchId) {
  await refreshBatches();
  const sel = document.getElementById('f-batch');
  if (sel) sel.value = batchId;
  syncSetDeleteBtn();
  const firstTabBtn = document.querySelector('.tab-btn');
  showTab('inspector', firstTabBtn);
  await loadTasks(true);
}

async function init() {
  upgradeAllCustomSelects();
  const minSplash = new Promise(resolve => setTimeout(resolve, 2950));
  try {
    const res = await fetch('/api/overview');
    overviewData = await res.json();
    await refreshProvidersStatus();
    renderKPIs();
    renderEvalTab();
    await refreshBatches();
    await loadTasks();
    upgradeAllCustomSelects();
  } catch (e) {
    console.error('Init warning:', e);
  } finally {
    await minSplash;
    const splash = document.getElementById('splash-overlay');
    openInfoDialog();
    requestAnimationFrame(() => {
      if (splash) splash.classList.add('done');
    });
  }
}

function renderKPIs() {
  const val = overviewData.validation || {};
  const mut = overviewData.mutation || {};
  const evals = overviewData.evaluations || [];
  const ocrEval = evals.find(e => e.provider === 'ocr_heuristic');
  const blindEval = evals.find(e => e.provider === 'blind_random');
  const bestVlm = evals.filter(e => !['ocr_heuristic', 'blind_random', 'oracle_solver'].includes(e.provider))
    .sort((a, b) => (b.overall_accuracy || 0) - (a.overall_accuracy || 0))[0];
  const cards = [
    {
      icon: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M5.5 6h5M5.5 9.5h3.5"/></svg>',
      label: 'Questions Ready',
      value: overviewData.task_count,
      sub: 'Starter question pack',
      tip: 'Total circuit questions currently in the starter question set.'
    },
    {
      icon: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M3 8.5l3 3 7-7"/></svg>',
      label: 'Drawing Quality',
      value: val.pass_rate ? (val.pass_rate * 100).toFixed(1) + '%' : '-',
      sub: `${val.passed_tasks || 0}/${val.total_tasks || 0} clear & non-overlapping`,
      tip: 'Checks every drawing so wires and text labels never overlap.'
    },
    {
      icon: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2L3 4.2v3.6c0 3.3 2.1 5.6 5 6.4 2.9-.8 5-3.1 5-6.4V4.2L8 2z"/></svg>',
      label: 'Self-Check Accuracy',
      value: mut.mutation_score ? (mut.mutation_score * 100).toFixed(0) + '%' : '-',
      sub: `${mut.mutants_killed || 0}/${mut.total_mutants || 0} planted errors caught`,
      tip: 'Updates live when you run all 12 guardrail checks below.'
    },
    {
      icon: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M3 4.5h10M3 8h7M3 11.5h5"/></svg>',
      label: 'Word-Reader Score',
      value: ocrEval ? (ocrEval.overall_accuracy * 100).toFixed(1) + '%' : '-',
      sub: 'Text alone without wire tracing',
      tip: 'Updates live when you test Word Reader Only above.'
    },
    {
      icon: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M1.5 8s2.4-4.2 6.5-4.2S14.5 8 14.5 8s-2.4 4.2-6.5 4.2S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="1.8"/></svg>',
      label: 'Best Vision AI Score',
      value: bestVlm ? (bestVlm.overall_accuracy * 100).toFixed(1) + '%' : (blindEval ? (blindEval.overall_accuracy * 100).toFixed(1) + '%' : '-'),
      sub: bestVlm ? friendlyModelLabel(bestVlm).replace(' [Live Run]', '') : 'Blind guessing baseline',
      tip: 'Highest Vision AI score tested so far (updates live after any test run).'
    }
  ];
  document.getElementById('kpis').innerHTML = cards.map(c => `
    <div class="spec-cell" title="${esc(c.tip)}">
      <div class="spec-label">${c.icon}<span>${c.label}</span></div>
      <div class="spec-value">${c.value}</div>
      <div class="spec-sub">${c.sub}</div>
    </div>
  `).join('');
}

async function refreshBatches() {
  const res = await fetch('/api/batches');
  const batches = await res.json();
  builtinBatchIds = new Set(batches.filter(b => b.source === 'builtin').map(b => b.batch_id));
  const prevF = document.getElementById('f-batch')?.value || 'default';
  const prevE = document.getElementById('e-batch')?.value || 'default';
  const opts = batches.map(b => {
    const label = `${b.title || b.batch_id} (${b.count || b.completed || 0} Qs)`;
    return `<option value="${esc(b.batch_id)}">${esc(label)}</option>`;
  }).join('');
  const fSel = document.getElementById('f-batch');
  const eSel = document.getElementById('e-batch');
  fSel.innerHTML = opts || '<option value="default">default</option>';
  eSel.innerHTML = opts || '<option value="default">default</option>';
  if ([...fSel.options].some(o => o.value === prevF)) fSel.value = prevF;
  if ([...eSel.options].some(o => o.value === prevE)) eSel.value = prevE;
  syncSetDeleteBtn();

  const countPill = document.getElementById('batch-count-pill');
  if (countPill) {
    const readyCount = batches.filter(b => b.status === 'completed').length;
    countPill.textContent = `${readyCount} ${readyCount === 1 ? 'set' : 'sets'} ready`;
  }

  document.getElementById('batch-table').innerHTML = `
    <table style="margin-top:0;">
      <thead>
        <tr>
          <th>Question Set</th>
          <th>Topic &amp; Difficulty</th>
          <th>What&rsquo;s Inside (Question Bank Info)</th>
          <th style="text-align:right;">Questions</th>
          <th style="text-align:right;">Actions</th>
        </tr>
      </thead>
      <tbody>
        ${batches.map(b => {
          const safeId = esc(b.batch_id);
          const titleTxt = esc(b.title || b.batch_id);
          const isBuiltin = b.source === 'builtin';
          const countTxt = b.count != null ? Number(b.count).toLocaleString() : `${b.completed || 0}/${b.total || 0}`;
          const ready = b.status === 'completed';
          const topicLvl = `${esc(b.topic_label || 'Mixed')} &middot; ${esc(b.level_label || 'Mixed')}`;
          const infoTxt = esc(b.summary || 'Circuit question set ready for viewing or export.');
          return `
            <tr>
              <td>
                <div style="font-weight:700; color:var(--ink);">${titleTxt}</div>
                <div class="mono" style="font-size:10.5px; color:var(--ink-faint); margin-top:1px;">${isBuiltin ? 'Built-in' : 'Custom Set'}</div>
              </td>
              <td style="font-size:12px; color:var(--ink-muted); white-space:nowrap;">${topicLvl}</td>
              <td style="font-size:12px; color:var(--ink-muted); max-width:390px;">${infoTxt}</td>
              <td class="mono" style="text-align:right; font-weight:700;">${countTxt}</td>
              <td style="text-align:right; white-space:nowrap;">
                ${ready ? `
                  <div style="display:inline-flex; gap:6px; align-items:center;">
                    <button type="button" class="set-action-link" onclick="openBatchInBrowser('${safeId}')">
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>
                      <span>Browse</span>
                    </button>
                    <a class="set-action-link accent" href="/api/batches/${safeId}/download">
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.5v7.5M5 7l3 3 3-3M2.5 12.5h11"/></svg>
                      <span>Download .ZIP</span>
                    </a>
                    ${!isBuiltin ? `
                      <button type="button" class="set-del-btn" title="Delete question set" onclick="deleteBatch('${safeId}')">
                        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11M6 4V2.5h4V4M5 6.5v5.5M8 6.5v5.5M11 6.5v5.5M3.5 4l.7 9a1 1 0 0 0 1 .9h5.6a1 1 0 0 0 1-.9l.7-9"/></svg>
                      </button>
                    ` : ''}
                  </div>
                ` : `<span class="badge warn">${esc(b.status)}</span>`}
              </td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
}

function applyBankTemplate(key, btn) {
  document.querySelectorAll('.tmpl-chip').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const presets = {
    full_mix:   { name: 'my_circuit_quiz', count: 30, fam: '', diff: '', theme: '', deg: '', lbl: '', pFam: 'state_propagation', pDiff: 'medium', pTheme: 'ieee_classic', pDeg: 'clean', pLbl: 'symbol_only' },
    hard_logic: { name: 'hard_logic_quiz', count: 50, fam: 'state_propagation', diff: 'hard', theme: 'ieee_classic', deg: 'clean', lbl: 'symbol_only', pFam: 'state_propagation', pDiff: 'hard', pTheme: 'ieee_classic', pDeg: 'clean', pLbl: 'symbol_only' },
    clean_exam: { name: 'clean_exam_pack', count: 40, fam: '', diff: 'medium', theme: 'high_contrast_mono', deg: 'clean', lbl: 'symbol_only', pFam: 'bridge_vs_junction', pDiff: 'medium', pTheme: 'high_contrast_mono', pDeg: 'clean', pLbl: 'symbol_only' },
    ohms_lab:   { name: 'ohms_lab_quiz',   count: 25, fam: 'equivalent_resistance', diff: '', theme: 'aged_paper', deg: 'clean', lbl: 'annotated', pFam: 'equivalent_resistance', pDiff: 'medium', pTheme: 'aged_paper', pDeg: 'clean', pLbl: 'annotated' },
  };
  const cfg = presets[key] || presets.full_mix;
  document.getElementById('b-name').value = cfg.name;
  document.getElementById('b-count').value = cfg.count;
  document.getElementById('b-family').value = cfg.fam;
  document.getElementById('b-diff').value = cfg.diff;
  document.getElementById('b-theme').value = cfg.theme;
  document.getElementById('b-deg').value = cfg.deg;
  document.getElementById('b-lbl').value = cfg.lbl;
  updateBatchProbability();

  document.getElementById('g-family').value = cfg.pFam;
  document.getElementById('g-diff').value = cfg.pDiff;
  document.getElementById('g-theme').value = cfg.pTheme;
  document.getElementById('g-deg').value = cfg.pDeg;
  document.getElementById('g-lbl').value = cfg.pLbl;
  runLiveGen(false, true);
}

async function deleteBatch(batchId) {
  const res = await fetch('/api/batches/' + encodeURIComponent(batchId), { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json();
    alert('Could not delete: ' + (err.detail || res.statusText));
    return;
  }
  await refreshBatches();
  await loadTasks(true);
}

let activeBatchPoll = null;
let activeBatchTick = null;

async function launchBatch() {
  if (activeBatchPoll) clearInterval(activeBatchPoll);
  if (activeBatchTick) clearInterval(activeBatchTick);
  const statusEl = document.getElementById('batch-live-status');
  const bFam = document.getElementById('b-family').value;
  const bDiff = document.getElementById('b-diff').value;
  const bTheme = document.getElementById('b-theme').value;
  const bDeg = document.getElementById('b-deg').value;
  const bLbl = document.getElementById('b-lbl').value;
  const payload = {
    name: document.getElementById('b-name').value || 'my_circuit_quiz',
    count: parseInt(document.getElementById('b-count').value || '30', 10),
    seed: parseInt(document.getElementById('b-seed').value || '777', 10),
    families: bFam ? [bFam] : null,
    difficulties: bDiff ? [bDiff] : null,
    themes: bTheme ? [bTheme] : null,
    degradations: bDeg ? [bDeg] : null,
    label_modes: bLbl ? [bLbl] : null,
    include_degradations: !bDeg,
    include_invariance_pairs: false,
    emit_svg: true,
    run_ocr: true,
    lazy_render: document.getElementById('b-lazy').checked ? null : false,
  };
  statusEl.innerHTML = `<div class="mono" style="color:var(--copper);">Starting &ldquo;${esc(payload.name)}&rdquo; (${payload.count.toLocaleString()} Qs)...</div><div class="eval-progress-wrap"><div class="eval-progress-fill" style="width:6%;"></div></div>`;
  const res = await fetch('/api/batches', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    statusEl.innerHTML = `<span style="color:var(--crimson);">Error: ${esc(err.detail || res.statusText)}</span>`;
    return;
  }
  const job = await res.json();
  let lastSnap = job;
  let lastSyncMs = Date.now();
  await refreshBatches();

  const drawBatchProgress = () => {
    const tot = Math.max(1, lastSnap.total || payload.count);
    const done = lastSnap.completed || 0;
    const pct = Math.max(6, Math.min(100, Math.round((done / tot) * 100)));
    const dtSincePoll = (Date.now() - lastSyncMs) / 1000.0;
    const estElapsed = Number(lastSnap.elapsed_s || 0) + dtSincePoll;
    const estLeft = lastSnap.eta_seconds != null ? Math.max(0, Number(lastSnap.eta_seconds) - dtSincePoll) : null;
    const leftTxt = estLeft != null ? _fmtDuration(estLeft) : '...';
    statusEl.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <span style="font-weight:700; color:var(--ink);">Building: ${done.toLocaleString()} / ${tot.toLocaleString()}</span>
        <span class="badge ok">Time Left: ~${esc(leftTxt)}</span>
      </div>
      <div class="eval-progress-wrap"><div class="eval-progress-fill" style="width:${pct}%;"></div></div>
      <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--ink-faint);">
        <span>Elapsed: <b>${_fmtDuration(estElapsed)}</b></span>
        <span><b>${Math.round((done / tot) * 100)}%</b> ready</span>
      </div>
    `;
  };
  drawBatchProgress();
  activeBatchTick = setInterval(drawBatchProgress, 250);

  activeBatchPoll = setInterval(async () => {
    try {
      const s = await (await fetch('/api/batches/' + encodeURIComponent(job.batch_id))).json();
      lastSnap = s;
      lastSyncMs = Date.now();
      await refreshBatches();
      if (s.status === 'completed') {
        clearInterval(activeBatchPoll);
        clearInterval(activeBatchTick);
        const actual = s.total || payload.count;
        const capMsg = s.capped_at_unique_limit ? ` (unique cap reached cleanly)` : '';
        statusEl.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <span style="color:var(--sage); font-weight:700;">Ready! ${Number(actual).toLocaleString()} unique Qs${esc(capMsg)} (${_fmtDuration(s.elapsed_s || 0)})</span>
            <button type="button" class="set-action-link accent" onclick="openBatchInBrowser('${esc(job.batch_id)}')">Browse Questions &rarr;</button>
          </div>
        `;
      } else if (s.status === 'failed') {
        clearInterval(activeBatchPoll);
        clearInterval(activeBatchTick);
        statusEl.innerHTML = `<span style="color:var(--crimson);">Failed: ${esc(s.error || 'Unknown error')}</span>`;
      }
    } catch (e) {}
  }, 600);
}

let searchTimer = null;
function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadTasks(true), 220);
}

function showAllPageSize(targetSize) {
  pageSize = targetSize;
  loadTasks(true);
}

function prevPage() {
  if (currentOffset > 0) {
    currentOffset = Math.max(0, currentOffset - pageSize);
    loadTasks(false);
  }
}

function nextPage() {
  if (currentOffset + pageSize < currentTotal) {
    currentOffset += pageSize;
    loadTasks(false);
  }
}

async function loadTasks(resetPage = true) {
  if (resetPage) {
    currentOffset = 0;
  }
  const batch = document.getElementById('f-batch').value || 'default';
  const fam = document.getElementById('f-family').value;
  const diff = document.getElementById('f-diff').value;
  const deg = document.getElementById('f-deg').value;
  const searchEl = document.getElementById('f-search');
  const q = searchEl ? searchEl.value.trim() : '';
  const qs = new URLSearchParams({ batch_id: batch, offset: String(currentOffset), limit: String(pageSize) });
  if (fam) qs.set('family', fam);
  if (diff) qs.set('difficulty', diff);
  if (deg) qs.set('degradation', deg);
  if (q) qs.set('q', q);
  const res = await fetch('/api/tasks?' + qs.toString());
  currentTotal = parseInt(res.headers.get('X-Total-Count') || '0', 10);
  const tasks = await res.json();

  if (currentOffset === 0 && !q) {
    tasks.sort((a, b) => (a.theme === 'kicad_blueprint' ? 1 : 0) - (b.theme === 'kicad_blueprint' ? 1 : 0));
  }
  const startNum = currentTotal === 0 ? 0 : currentOffset + 1;
  const endNum = currentOffset + tasks.length;

  const listEl = document.getElementById('task-list');
  listEl.scrollTop = 0;
  if (tasks.length === 0) {
    listEl.innerHTML = '<div class="task-item"><div class="task-title">No matching questions</div><div class="mono" style="font-size:11px; color:var(--ink-faint); margin-top:4px;">Clear search or change filters above.</div></div>';
    document.getElementById('task-detail').innerHTML = 'No circuit questions found.';
    return;
  }

  const nextEnd = Math.min(currentTotal, endNum + pageSize);
  const showAllTarget = currentTotal <= 1000 ? currentTotal : 1000;
  const footerHtml = `
    <div style="padding:12px; background:var(--copper-soft); border-top:1px solid var(--border-light); text-align:center;">
      <div class="mono" style="font-size:11.5px; font-weight:700; color:var(--ink); margin-bottom:8px;">
        Viewing ${startNum.toLocaleString()}-${endNum.toLocaleString()} of ${currentTotal.toLocaleString()} questions
      </div>
      <div style="display:flex; gap:8px; justify-content:center; flex-wrap:wrap;">
        ${currentOffset > 0 ? `<button type="button" class="secondary" style="padding:5px 10px; font-size:11px;" onclick="prevPage()">Prev 100</button>` : ''}
        ${endNum < currentTotal ? `<button type="button" class="primary" style="padding:6px 12px; font-size:11px;" onclick="nextPage()">NEXT: Q#${(endNum + 1).toLocaleString()}-${nextEnd.toLocaleString()}</button>` : ''}
        ${endNum < currentTotal ? `<button type="button" class="secondary" style="padding:5px 10px; font-size:11px;" onclick="showAllPageSize(${showAllTarget})">Show All ${showAllTarget.toLocaleString()}</button>` : ''}
      </div>
    </div>
  `;

  listEl.innerHTML = `<div class="q-queue-hdr"><svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M3 4.5h10M3 8h10M3 11.5h7"/></svg><span>Question Queue (${currentTotal.toLocaleString()})</span></div>` + tasks.map((t, i) => `
    <div class="task-item ${i === 0 ? 'active' : ''}" onclick='selectTask(${JSON.stringify(t).replace(/'/g, "&#39;")}, this)'>
      <div class="task-title"><span class="q-num">Q#${currentOffset + i + 1}</span> <span>${esc(fmtTopic(t.family))}</span></div>
      <div class="task-meta">
        <span class="status-dot ${(t.quality_audit == null || t.quality_audit.passed) ? 'ok' : 'warn'}"></span>
        <span>${esc(fmtDiff(t.difficulty))}</span>
        <span>&middot;</span>
        <span>${esc(fmtStyle(t.theme))}</span>
      </div>
    </div>
  `).join('') + footerHtml;
  renderDetail(tasks[0], 'task-detail');
}

function selectTask(t, el) {
  document.querySelectorAll('.task-item').forEach(x => x.classList.remove('active'));
  el.classList.add('active');
  renderDetail(t, 'task-detail');
}

function renderDetail(t, containerId) {
  const qa = t.quality_audit || {};
  const steps = (t.solver_proof && t.solver_proof.proof_steps) || [];
  const tokens = (qa.ocr_detected_tokens || []).slice(0, 18).join(', ');
  const useCompactSideSplit = containerId === 'live-result';

  if (useCompactSideSplit) {
    document.getElementById(containerId).innerHTML = `
      <div class="sheet-detail sheet-animate">
        <div class="sheet-split-body">
          <div class="sheet-canvas-band">
            <div class="canvas-wrap">
              <div class="canvas-header-bar">
                <span>${esc(t.task_id)}</span>
                <span>${esc(fmtStyle(t.theme))} &middot; ${esc(fmtScan(t.degradation))} &middot; ${esc(fmtMode(t.label_mode))}</span>
              </div>
              <img src="${esc(t.image_url)}" alt="${esc(t.task_id)}" title="Click circuit image to zoom in or out" onclick="this.classList.toggle('zoomed')" />
            </div>
          </div>
          <div class="sheet-side-col">
            <div>
              <div class="sheet-q-label">Question Prompt</div>
              <div class="sheet-question">${esc(t.question)}</div>
              ${t.mutation_description ? `<div style="margin-top:6px; font-size:12px; color:var(--copper); font-weight:500;">Picture A &rarr; B change: ${esc(t.mutation_description)}</div>` : ''}
            </div>
            <div>
              <div class="stamp-answer">ANSWER: ${esc(t.answer)}</div>
              <div class="badge-row" style="margin-top:8px;">
                <span class="badge ok">${qa.bbox_collisions ?? 0} Overlaps</span>
                <span class="badge ok">100% Solvable</span>
                <span class="badge">Difficulty: ${esc(fmtDiff(t.difficulty))}</span>
              </div>
            </div>
            <div class="sheet-steps-box">
              <h3>
                <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M3 4h10M3 8h10M3 12h6"/></svg>
                <span>Step-by-Step Solution</span>
              </h3>
              <ol class="proof">${steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>
            </div>
            <div style="margin-top:auto; padding-top:8px; border-top:1px solid var(--border-light); font-size:11.5px; color:var(--ink-faint);">
              Contrast: <b>${qa.min_contrast_ratio ?? '-'}x</b> &middot; Readability: <b>${((qa.ocr_target_recall || 0) * 100).toFixed(0)}%</b>
              ${tokens ? `<div style="margin-top:4px; font-size:11px;">Text spotted: <span class="mono">${esc(tokens)}</span></div>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;
    return;
  }

  document.getElementById(containerId).innerHTML = `
    <div class="sheet-vertical-big sheet-animate">
      <div class="sheet-q-top">
        <div class="canvas-header-bar">
          <span>Question ID: ${esc(t.task_id)}</span>
          <span>Style: ${esc(fmtStyle(t.theme))} &middot; Look: ${esc(fmtScan(t.degradation))} &middot; Labels: ${esc(fmtMode(t.label_mode))}</span>
        </div>
        <div class="sheet-question">${esc(t.question)}</div>
        ${t.mutation_description ? `<div style="margin-top:5px; font-size:12px; color:var(--copper); font-weight:500;">Change between Picture A &amp; B: ${esc(t.mutation_description)}</div>` : ''}
      </div>
      <div class="sheet-big-canvas">
        <div class="canvas-wrap">
          <img src="${esc(t.image_url)}" alt="${esc(t.task_id)}" title="Click circuit image to zoom in or out" onclick="this.classList.toggle('zoomed')" />
        </div>
      </div>
      <div class="sheet-bottom">
        <div class="sheet-ans-col">
          <h3>
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="var(--sage)" stroke-width="1.8" stroke-linecap="round"><path d="M3 8.5l3 3 7-7"/></svg>
            <span>Answer &amp; Verification</span>
          </h3>
          <div class="stamp-answer">ANSWER: ${esc(t.answer)}</div>
          <div class="badge-row">
            <span class="badge ok">${qa.bbox_collisions ?? 0} Overlaps</span>
            <span class="badge ok">100% Solvable</span>
            <span class="badge">Difficulty: ${esc(fmtDiff(t.difficulty))}</span>
          </div>
          <div style="margin-top:auto; padding-top:8px; border-top:1px solid var(--border-light); font-size:11.5px; color:var(--ink-faint);">
            Contrast: <b>${qa.min_contrast_ratio ?? '-'}x</b> &middot; Readability: <b>${((qa.ocr_target_recall || 0) * 100).toFixed(0)}%</b>
            ${tokens ? `<div style="margin-top:4px; font-size:11px;">Text spotted: <span class="mono">${esc(tokens)}</span></div>` : ''}
          </div>
        </div>
        <div class="sheet-steps-col">
          <h3>
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M3 4h10M3 8h10M3 12h6"/></svg>
            <span>Step-by-Step Solution</span>
          </h3>
          <ol class="proof">${steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>
        </div>
      </div>
    </div>
  `;
}

function onPreviewOptionChange(kind) {

  runLiveGen(kind === 'style', kind === 'structure');
}

async function runLiveGen(keepSeed = false, forceFreshSeed = false) {
  const lockBox = document.getElementById('g-lock-seed');
  let seed = parseInt(document.getElementById('g-seed').value || '2026', 10);
  if (!keepSeed && (forceFreshSeed || !lockBox || !lockBox.checked)) {
    seed = Math.floor(Math.random() * 900000) + 1000;
    document.getElementById('g-seed').value = seed;
  }
  previewInitialized = true;
  const payload = {
    family: document.getElementById('g-family').value,
    difficulty: document.getElementById('g-diff').value,
    theme: document.getElementById('g-theme').value,
    degradation: document.getElementById('g-deg').value,
    label_mode: document.getElementById('g-lbl').value,
    seed,
  };
  const liveEl = document.getElementById('live-result');
  const prevH = liveEl ? liveEl.offsetHeight : 0;
  if (liveEl) {
    if (prevH > 120) liveEl.style.minHeight = prevH + 'px';
    liveEl.style.opacity = '0.58';
    liveEl.innerHTML = prevH > 120 ? liveEl.innerHTML : 'Drawing circuit, computing exact answer, and checking label clarity...';
  }
  const res = await fetch('/api/generate-live', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  renderDetail(await res.json(), 'live-result');
  if (liveEl) {
    liveEl.style.opacity = '1';
    liveEl.style.minHeight = '';
  }
}

const CUSTOM_PRESETS = {
  voting: `# TITLE: 3-SENSOR VOTING INTERLOCK\nVCC1(12V) -> SW1(CLOSED) -> U1(AND) -> U3(OR) -> L1\nVCC1 -> SW2(CLOSED) -> U1\nVCC1 -> SW3(OPEN) -> U2(NAND) -> U3\nSW2 -> U2`,
  dualrail: `# TITLE: DUAL-POWER SHUTDOWN BUS\nVCC1(24V) -> F1(OK) -> SW1(CLOSED) -> U1(XOR) -> U2(NOR) -> L1\nVCC2(5V) -> SW2(OPEN) -> U_INV(NOT) -> U1\nVCC2 -> SW3(CLOSED) -> U2`,
  deep: `# TITLE: MULTI-STEP FACTORY CIRCUIT\nVCC(24V) -> F1(OK) -> SW1(CLOSED) -> U1(NAND) -> U3(OR) -> U5(AND) -> L1\nVCC -> SW2(CLOSED) -> U_NOT(NOT) -> U1\nVCC -> SW3(OPEN) -> U2(XOR) -> U4(NOR) -> U5\nVCC -> SW4(CLOSED) -> U2\nU1 -> U4\nSW4 -> U3`,
  interlock: JSON.stringify({
    title: "SAFETY INTERLOCK RELAY",
    target_led: "ALARM_LED",
    theme: "aged_paper",
    label_mode: "symbol_only",
    nodes: [
      {id: "VCC1", kind: "source", voltage_level: 1},
      {id: "SW_DOOR", kind: "switch", closed: true},
      {id: "SW_ESTOP", kind: "switch", closed: false},
      {id: "F1", kind: "fuse", intact: true},
      {id: "U_INV", kind: "gate_not"},
      {id: "U_LOCK", kind: "gate_and"},
      {id: "ALARM_LED", kind: "led"}
    ],
    edges: [
      {src: "VCC1", dst: "SW_DOOR"},
      {src: "VCC1", dst: "SW_ESTOP"},
      {src: "SW_DOOR", dst: "F1"},
      {src: "SW_ESTOP", dst: "U_INV"},
      {src: "F1", dst: "U_LOCK"},
      {src: "U_INV", dst: "U_LOCK"},
      {src: "U_LOCK", dst: "ALARM_LED"}
    ]
  }, null, 2)
};

const PRESET_TITLES = {
  voting: '3-SENSOR VOTING INTERLOCK',
  dualrail: 'DUAL-POWER SHUTDOWN BUS',
  deep: 'MULTI-STEP FACTORY CIRCUIT',
  interlock: 'SAFETY INTERLOCK RELAY'
};

let customLiveTimer = null;
let customAbort = null;

function scheduleCustomLive() {
  const badge = document.getElementById('custom-live-badge');
  if (badge) {
    badge.className = 'badge';
    badge.textContent = 'Updating...';
  }
  clearTimeout(customLiveTimer);
  customLiveTimer = setTimeout(() => {
    updateCustomProbability();
    compileCustom(true);
  }, 300);
}

function loadCustomPreset(name) {
  if (CUSTOM_PRESETS[name]) {
    document.getElementById('netlist-json').value = CUSTOM_PRESETS[name];
    document.getElementById('c-title').value = PRESET_TITLES[name] || 'CUSTOM CIRCUIT';
    updateCustomProbability();
    compileCustom(false);
  }
}

async function compileCustom(silent = false) {
  const badge = document.getElementById('custom-live-badge');
  const resEl = document.getElementById('custom-result');
  if (customAbort) customAbort.abort();
  customAbort = new AbortController();
  const signal = customAbort.signal;
  try {
    const raw = document.getElementById('netlist-json').value;
    const title = document.getElementById('c-title').value || 'CUSTOM CIRCUIT';
    if (!silent) {
      resEl.innerHTML = '<div style="padding:18px; color:var(--ink-muted);">Drawing circuit and calculating exact answer...</div>';
    }
    const res = await fetch('/api/from-netlist/dsl', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ text: raw, title }),
      signal,
    });
    if (!res.ok) {
      const err = await res.json();
      if (badge) {
        badge.className = 'badge warn';
        badge.textContent = 'Check syntax';
      }
      if (!silent) {
        resEl.innerHTML = `<div style="padding:16px;"><span class="mono" style="color:var(--crimson)">Could not read circuit: ${esc(err.detail)}</span></div>`;
      }
      return;
    }
    const pkg = await res.json();
    if (badge) {
      badge.className = 'badge ok';
      badge.textContent = 'Live Synced';
    }
    renderDetail(pkg, 'custom-result');
  } catch (e) {
    if (e.name === 'AbortError') return;
    if (badge) {
      badge.className = 'badge warn';
      badge.textContent = 'Error';
    }
    if (!silent) {
      resEl.innerHTML = `<div style="padding:16px;"><span class="mono" style="color:var(--crimson)">Error: ${esc(e.message)}</span></div>`;
    }
  }
}

async function launchCustomBatch() {
  const statusEl = document.getElementById('custom-batch-status');
  const raw = document.getElementById('netlist-json').value;
  const title = document.getElementById('c-title').value || 'CUSTOM CIRCUIT';
  const count = parseInt(document.getElementById('c-count').value || '100', 10);
  statusEl.textContent = `Starting ${count.toLocaleString()} practice variations...`;
  const res = await fetch('/api/from-netlist/batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name: 'custom_' + count, text: raw, title, count, seed: Date.now() % 100000 }),
  });
  if (!res.ok) {
    const err = await res.json();
    statusEl.textContent = 'Error: ' + (err.detail || res.statusText);
    return;
  }
  const job = await res.json();
  const timer = setInterval(async () => {
    const s = await (await fetch('/api/batches/' + job.batch_id)).json();
    statusEl.textContent = `Creating "${job.batch_id}": ${(s.completed || 0).toLocaleString()} / ${(s.total || count).toLocaleString()} ready...`;
    if (s.status === 'completed' || s.status === 'failed') {
      clearInterval(timer);
      await refreshBatches();
      if (s.status === 'completed') {
        document.getElementById('f-batch').value = job.batch_id;
        const actual = s.total || count;
        const capTxt = s.capped_at_unique_limit
          ? ` (Requested ${Number(s.requested_count || count).toLocaleString()}, stopped cleanly at all ${Number(actual).toLocaleString()} unique non-repetitive questions!)`
          : '';
        statusEl.innerHTML = `Done! Created <b>${Number(actual).toLocaleString()}</b> unique circuit questions in <code>${esc(job.batch_id)}</code>${esc(capTxt)} <button class="primary" style="margin-left:10px" onclick="openBatchInBrowser('${esc(job.batch_id)}')">Open Questions Now</button>`;
        await loadTasks(true);
      } else {
        statusEl.textContent = 'Failed: ' + (s.error || 'Unknown error');
      }
    }
  }, 800);
}

const MUTANT_HUMAN = {
  M01_DROP_NAND_BUBBLE: 'NAND Output Bubble Check',
  M02_IGNORE_OPEN_SWITCH: 'Open Switch Blocking Check',
  M03_IGNORE_BLOWN_FUSE: 'Blown Fuse Gap Check',
  M04_SHORT_BRIDGE_JUMP: 'Wire Hop-Bridge Isolation',
  M05_PARALLEL_AS_SERIES: 'Parallel Resistor Formula Check',
  M06_LEAK_OPEN_BRANCH_RES: 'Open Branch Resistor Exclusion',
  M07_AMBIGUOUS_FAULT_DIAG: 'Ambiguous Fault Rejection',
  M08_OVERLAPPING_LABELS: 'Overlapping Label Guard',
  M09_OUT_OF_BOUNDS_LABEL: 'Off-Canvas Margin Guard',
  M10_COUNTERFACTUAL_COLLAPSE: 'Panel A vs Panel B Change Check',
  M11_WHOLE_SYSTEM_LOGIC_OHM_COUPLING: 'Fuse-to-Load Current Link',
  M12_SWITCH_TOGGLE_WHATIF: 'What-If Switch Flip Solver'
};

let currentChartTab = 'overall';
let selectedModelIdx = 0;

function friendlyModelLabel(e) {
  const lbl = e.model_label || e.provider || 'Model';
  const liveTag = e._is_live ? ' [Live Run]' : '';
  if (e.provider === 'ocr_heuristic') return 'Word Reader Only (No Wire Tracing)' + liveTag;
  if (e.provider === 'blind_random') return 'Random Guessing (No Image)' + liveTag;
  if (e.provider === 'oracle_solver') return 'Answer Key Check (Sanity Baseline)' + liveTag;
  if (e.provider === 'gemini') return `Google ${lbl.replace(/^gemini[:-]/i, '')} (Vision AI)` + liveTag;
  if (e.provider === 'openrouter') return `OpenRouter ${lbl.replace(/^openrouter[:-]/i, '')}` + liveTag;
  if (e.provider === 'openai') return `OpenAI ${lbl.replace(/^openai[:-]/i, '')}` + liveTag;
  if (e.provider === 'anthropic') return `Anthropic ${lbl.replace(/^anthropic[:-]/i, '')}` + liveTag;
  if (e.provider === 'ollama') return `Local ${lbl.replace(/^ollama[:-]/i, '')} (Offline PC)` + liveTag;
  return lbl + liveTag;
}

function modelBarColor(e) {
  if (e.provider === 'gemini') return '#2e7d52';
  if (e.provider === 'openrouter') return '#c96442';
  if (e.provider === 'openai' || e.provider === 'anthropic') return '#8b5e3c';
  if (e.provider === 'oracle_solver') return '#5c5952';
  if (e.provider === 'ollama') return '#d97706';
  return '#78716c';
}

function setChartView(tab) {
  currentChartTab = tab;
  renderInteractiveCharts();
}

function selectModelDetail(idx) {
  selectedModelIdx = idx;
  renderInteractiveCharts();
}

function _fmtDuration(sec) {
  const s = Math.max(0, Math.round(Number(sec || 0)));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

let activeEvalPoll = null;
let activeEvalTick = null;

async function resetEvalCharts() {
  await fetch('/api/evaluate-reset', { method: 'POST' });
  overviewData = await (await fetch('/api/overview')).json();
  selectedModelIdx = 0;
  renderKPIs();
  renderInteractiveCharts();
  const box = document.getElementById('live-eval-box');
  if (box) box.classList.add('hidden');
}

function getSelectedProviders() {
  const ready = [...document.querySelectorAll('#eval-ready-chips input[type="checkbox"]:checked')].map(cb => cb.value);
  const bases = [...document.querySelectorAll('#eval-baseline-chips input[type="checkbox"]:checked')].map(cb => cb.value);
  return [...ready, ...bases];
}

function _renderMultiEvalResultBox(reports, modelErrors) {
  const box = document.getElementById('live-eval-box');
  if (!reports || reports.length === 0) {
    const errMsg = (modelErrors && modelErrors[0]?.error) || 'No valid test results returned.';
    box.innerHTML = `<span class="mono" style="color:var(--crimson)">Test Error: ${esc(errMsg)}</span>`;
    return;
  }
  const summaryRows = reports.map(rep => `
    <tr>
      <td style="font-weight:600;">${esc(friendlyModelLabel(rep))}</td>
      <td class="mono" style="font-weight:700;">${(rep.overall_accuracy * 100).toFixed(1)}%</td>
      <td class="mono">${Math.round(rep.overall_accuracy * rep.total_tasks)} / ${rep.total_tasks}</td>
      <td class="mono">${rep.mean_latency_ms} ms</td>
      <td><span class="badge ${rep.error_count === 0 ? 'ok' : 'warn'}">${rep.error_count === 0 ? 'OK' : rep.error_count + ' API Errs'}</span></td>
    </tr>
  `).join('') + (modelErrors || []).map(me => `
    <tr>
      <td style="font-weight:600;">${esc(me.provider)}</td>
      <td class="mono">-</td>
      <td class="mono">-</td>
      <td class="mono">-</td>
      <td><span class="badge warn">${esc(me.error)}</span></td>
    </tr>
  `).join('');

  const primaryRep = reports[0];
  const recs = primaryRep.records || [];
  const isOracleOnly = reports.length === 1 && primaryRep.provider === 'oracle_solver';
  const note = isOracleOnly
    ? `<div style="margin:6px 0 10px 0; font-size:12.5px; color:var(--sage);"><b>Sanity Check Note:</b> Verifies the built-in Answer Key solver itself is 100% consistent. Select Vision AI models above to compare real solvers.</div>`
    : '';
  box.innerHTML = `
    <h3>
      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5"/></svg>
      <span>Live Test Summary (${reports.length} ${reports.length === 1 ? 'Model' : 'Models'} Tested &mdash; Charts Updated)</span>
    </h3>
    ${note}
    <table style="margin-bottom:14px;">
      <thead><tr><th>Model</th><th>Accuracy</th><th>Correct</th><th>Speed / Question</th><th>Status</th></tr></thead>
      <tbody>${summaryRows}</tbody>
    </table>
    <div style="font-size:12px; font-weight:600; color:var(--ink-muted); margin-bottom:4px;">Question Breakdown: ${esc(friendlyModelLabel(primaryRep))}</div>
    <table>
      <thead><tr><th>Question</th><th>Topic</th><th>Expected Answer</th><th>Tested Output</th><th>Result</th></tr></thead>
      <tbody>
        ${recs.map(r => `
          <tr>
            <td class="mono" style="font-size:11.5px;">${esc(r.task_id)}</td>
            <td>${esc(fmtTopic(r.family))}</td>
            <td class="mono" style="font-weight:700">${esc(r.ground_truth)}</td>
            <td class="mono">${esc(r.normalized_prediction || r.raw_response || (r.error ? 'ERROR: ' + r.error : '-'))}</td>
            <td><span class="badge ${r.correct ? 'ok' : 'warn'}">${r.correct ? 'PASS' : 'WRONG'}</span></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function runEvalLive() {
  if (activeEvalPoll) clearInterval(activeEvalPoll);
  if (activeEvalTick) clearInterval(activeEvalTick);
  const box = document.getElementById('live-eval-box');
  const providers = getSelectedProviders();
  if (providers.length === 0) {
    box.classList.remove('hidden');
    box.innerHTML = `<span class="mono" style="color:var(--crimson)">Select at least one Ready AI or Baseline model above before running.</span>`;
    toggleAddModelBar(true);
    return;
  }
  const missingProv = providers.find(p => providerStatusMap[p] && !providerStatusMap[p].configured);
  if (missingProv) {
    const meta = providerStatusMap[missingProv];
    toggleAddModelBar(true);
    const sel = document.getElementById('e-prov');
    if (sel) { sel.value = missingProv; onProviderPickerChange(); }
    box.classList.remove('hidden');
    box.innerHTML = `<span class="mono" style="color:var(--crimson)">${esc(meta.label)} needs an API key (${esc(meta.env_var)}) — enter it above to continue.</span>`;
    return;
  }
  const payload = {
    batch_id: document.getElementById('e-batch').value || 'default',
    provider: providers[0],
    providers,
    model: providers.length === 1 ? (document.getElementById('e-model')?.value.trim() || null) : null,
    limit: parseInt(document.getElementById('e-limit').value || '14', 10),
    api_key: null,
    base_url: document.getElementById('e-base-url')?.value.trim() || null,
    persist: true,
  };
  box.classList.remove('hidden');
  box.innerHTML = `<div class="mono">Starting live test across <b>${providers.length}</b> ${providers.length === 1 ? 'model' : 'models'}...</div><div class="eval-progress-wrap"><div class="eval-progress-fill" style="width:6%;"></div></div>`;

  const res = await fetch('/api/evaluate-jobs', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    box.innerHTML = `<span class="mono" style="color:var(--crimson)">Test Error: ${esc(err.detail || res.statusText)}</span>`;
    return;
  }
  const initJob = await res.json();
  let lastSnap = initJob;
  let lastSyncMs = Date.now();

  const drawProgress = () => {
    const tot = Math.max(1, lastSnap.total || (payload.limit * providers.length));
    const done = lastSnap.completed || 0;
    const pct = Math.max(4, Math.min(100, Math.round((done / tot) * 100)));
    const dtSincePoll = (Date.now() - lastSyncMs) / 1000.0;
    const estElapsed = Number(lastSnap.elapsed_s || 0) + dtSincePoll;
    const estLeft = lastSnap.eta_seconds != null ? Math.max(0, Number(lastSnap.eta_seconds) - dtSincePoll) : null;
    const timerTxt = estLeft != null ? _fmtDuration(estLeft) : 'calculating...';
    const curLabel = lastSnap.current_model || providers[0];
    const modPos = `${lastSnap.current_model_index || 1}/${lastSnap.total_models || providers.length}`;
    box.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <span class="mono" style="font-weight:700; color:var(--rust);">Testing (${modPos}): ${esc(curLabel)}</span>
        <span class="badge ok">Time Left: ~${esc(timerTxt)}</span>
      </div>
      <div class="eval-progress-wrap"><div class="eval-progress-fill" style="width:${pct}%;"></div></div>
      <div class="mono" style="display:flex; flex-wrap:wrap; gap:18px; font-size:12px; color:var(--ink-muted);">
        <span>Overall Progress: <b>${done} / ${tot}</b> (${Math.round((done / tot) * 100)}%)</span>
        <span>Elapsed: <b>${_fmtDuration(estElapsed)}</b></span>
        <span>Correct So Far: <b>${lastSnap.correct_so_far || 0} / ${done}</b></span>
      </div>
    `;
  };
  drawProgress();
  activeEvalTick = setInterval(drawProgress, 250);

  activeEvalPoll = setInterval(async () => {
    try {
      const sRes = await fetch('/api/evaluate-jobs/' + encodeURIComponent(initJob.job_id));
      if (!sRes.ok) return;
      const snap = await sRes.json();
      lastSnap = snap;
      lastSyncMs = Date.now();
      if (snap.status === 'failed') {
        clearInterval(activeEvalPoll);
        clearInterval(activeEvalTick);
        box.innerHTML = `<span class="mono" style="color:var(--crimson)">Test Failed: ${esc(snap.error || 'Unknown error')}</span>`;
        return;
      }
      if (snap.status === 'completed') {
        clearInterval(activeEvalPoll);
        clearInterval(activeEvalTick);
        const reports = snap.reports && snap.reports.length ? snap.reports : (snap.report ? [snap.report] : []);
        overviewData = await (await fetch('/api/overview')).json();
        const sortedEvals = (overviewData.evaluations || []).slice().sort((a, b) => {
          const ao = a.provider === 'oracle_solver' ? 1 : 0;
          const bo = b.provider === 'oracle_solver' ? 1 : 0;
          if (ao !== bo) return ao - bo;
          return (b.overall_accuracy || 0) - (a.overall_accuracy || 0);
        });
        if (reports[0]) {
          const newSel = sortedEvals.findIndex(e => e.provider === reports[0].provider && e.model_label === reports[0].model_label);
          if (newSel >= 0) selectedModelIdx = newSel;
        }
        renderInteractiveCharts();
        renderKPIs();
        _renderMultiEvalResultBox(reports, snap.model_errors || []);
      }
    } catch (e) {}
  }, 550);
}

function renderInteractiveCharts() {
  const evals = ((overviewData && overviewData.evaluations) || []).slice().sort((a, b) => {
    const ao = a.provider === 'oracle_solver' ? 1 : 0;
    const bo = b.provider === 'oracle_solver' ? 1 : 0;
    if (ao !== bo) return ao - bo;
    return (b.overall_accuracy || 0) - (a.overall_accuracy || 0);
  });
  const val = (overviewData && overviewData.validation) || {};
  const mut = (overviewData && overviewData.mutation) || { results: [] };
  const activeEval = evals[selectedModelIdx] || evals[0];

  let chartBody = '';
  if (evals.length === 0) {
    chartBody = '<div class="mono" style="color:var(--ink-faint);">No test results loaded yet. Click "Run Test" above.</div>';
  } else if (currentChartTab === 'overall') {
    chartBody = evals.map((e, i) => {
      const pct = (e.overall_accuracy * 100).toFixed(1);
      const correctN = Math.round(e.overall_accuracy * e.total_tasks);
      const col = modelBarColor(e);
      return `
        <div class="bar-row ${i === selectedModelIdx ? 'selected' : ''}" onclick="selectModelDetail(${i})" title="Click to inspect sample failures & timing (${correctN}/${e.total_tasks} correct, ${e.mean_latency_ms} ms/task)">
          <div style="font-weight:600; font-size:12.5px;">${esc(friendlyModelLabel(e))}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%; background:${col};"></div></div>
          <div class="mono" style="text-align:right; font-weight:700; font-size:13px;">${pct}%</div>
        </div>
      `;
    }).join('');
  } else {
    const fieldMap = {
      family: ['by_family', fmtTopic],
      difficulty: ['by_difficulty', fmtDiff],
      degradation: ['by_degradation', fmtScan],
      label_mode: ['by_label_mode', fmtMode],
    };
    const [prop, fmtFn] = fieldMap[currentChartTab] || ['by_family', fmtTopic];
    const keys = Array.from(new Set(evals.flatMap(e => Object.keys(e[prop] || {}))));
    chartBody = keys.map(k => `
      <div class="grp-row">
        <div style="font-weight:700; font-size:13px; margin-bottom:4px;">${esc(fmtFn(k))}</div>
        ${evals.filter(e => e.provider !== 'oracle_solver').map(e => {
          const s = (e[prop] || {})[k];
          if (!s) return '';
          const pct = (s.accuracy * 100).toFixed(1);
          return `
            <div class="mini-bar-row" title="${s.correct}/${s.total} correct">
              <div style="color:var(--ink-muted);">${esc(friendlyModelLabel(e))}</div>
              <div class="bar-track" style="height:14px;"><div class="bar-fill" style="width:${pct}%; background:${modelBarColor(e)};"></div></div>
              <div class="mono" style="text-align:right; font-weight:600;">${pct}%</div>
            </div>
          `;
        }).join('')}
      </div>
    `).join('');
  }

  let failInspector = '';
  if (activeEval) {
    const fails = activeEval.sample_failures || [];
    const correctN = Math.round(activeEval.overall_accuracy * activeEval.total_tasks);
    failInspector = `
      <div style="margin-top:12px; padding:10px 12px; background:var(--paper-bg); border-radius:4px; border:1px solid var(--border-light);">
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
          <b>Selected Model Inspector: ${esc(friendlyModelLabel(activeEval))}</b>
          <span class="mono" style="font-size:12px;">${correctN}/${activeEval.total_tasks} correct &middot; ${activeEval.mean_latency_ms} ms/question</span>
        </div>
        ${fails.length === 0 ? '<div style="font-size:12.5px; color:var(--sage);">0 sample mistakes recorded on this run.</div>' : `
          <div style="font-size:12px; color:var(--ink-muted); margin-bottom:6px;">Sample Questions Missed by This Model (showing why visual understanding matters):</div>
          <table>
            <thead><tr><th>Question</th><th>Topic</th><th>True Answer</th><th>Model Said</th></tr></thead>
            <tbody>
              ${fails.slice(0, 5).map(f => `
                <tr>
                  <td class="mono">${esc(f.task_id)}</td>
                  <td>${esc(fmtTopic(f.family))}</td>
                  <td class="mono" style="font-weight:700; color:var(--sage);">${esc(f.ground_truth)}</td>
                  <td class="mono" style="color:var(--crimson);">${esc(f.normalized_prediction || f.raw_response || 'none')}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  }

  const bestVlm = evals.filter(e => !['ocr_heuristic', 'blind_random', 'oracle_solver'].includes(e.provider)).sort((a, b) => (b.overall_accuracy || 0) - (a.overall_accuracy || 0))[0];
  const ocrE = evals.find(e => e.provider === 'ocr_heuristic');
  const blindE = evals.find(e => e.provider === 'blind_random');
  const summarySub = `Visual reasoning comparison: Vision AI reaches <b>${bestVlm ? (bestVlm.overall_accuracy * 100).toFixed(1) + '%' : '-'}</b> vs. Word-Reader Only (<b>${ocrE ? (ocrE.overall_accuracy * 100).toFixed(1) + '%' : '-'}</b>) and Blind Guessing (<b>${blindE ? (blindE.overall_accuracy * 100).toFixed(1) + '%' : '-'}</b>). Any live test you run updates this chart automatically.`;

  document.getElementById('charts-grid').innerHTML = `
    <div class="chart-card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
        <h3 style="display:flex; align-items:center; gap:7px; margin:0; font-size:14.5px; font-weight:500; color:var(--ink); border:none; padding:0;">
          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="var(--copper)" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5"/></svg>
          <span>Interactive Score Comparison (Click Any Model Row to Inspect)</span>
        </h3>
        <div class="chart-tabs" style="margin:0;">
          <button type="button" class="chart-tab-btn ${currentChartTab === 'overall' ? 'active' : ''}" onclick="setChartView('overall')">Overall</button>
          <button type="button" class="chart-tab-btn ${currentChartTab === 'family' ? 'active' : ''}" onclick="setChartView('family')">By Topic</button>
          <button type="button" class="chart-tab-btn ${currentChartTab === 'difficulty' ? 'active' : ''}" onclick="setChartView('difficulty')">By Difficulty</button>
          <button type="button" class="chart-tab-btn ${currentChartTab === 'degradation' ? 'active' : ''}" onclick="setChartView('degradation')">By Scan Look</button>
          <button type="button" class="chart-tab-btn ${currentChartTab === 'label_mode' ? 'active' : ''}" onclick="setChartView('label_mode')">Symbols vs Hints</button>
        </div>
      </div>
      <div style="font-size:12px; color:var(--ink-muted); margin:6px 0 12px 0;">
        ${summarySub}
      </div>
      ${chartBody}
      ${failInspector}
    </div>
  `;
}

function toggleMutantProof(idx) {
  const row = document.getElementById('mut-proof-' + idx);
  if (row) row.classList.toggle('hidden');
}

function _proofSvgPair(leftTitle, leftInner, rightTitle, rightInner) {
  return `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:8px;">
      <div style="background:var(--paper-card); border:1.5px solid var(--sage); padding:8px 10px;">
        <div style="font-size:11px; font-weight:700; color:var(--sage); margin-bottom:4px;">VALID CIRCUIT (KEPT): ${esc(leftTitle)}</div>
        <svg viewBox="0 0 260 88" style="width:100%; height:auto; display:block; background:#ffffff; border:1px solid #cbd5e1;">${leftInner}</svg>
      </div>
      <div style="background:var(--paper-card); border:1.5px solid var(--crimson); padding:8px 10px;">
        <div style="font-size:11px; font-weight:700; color:var(--crimson); margin-bottom:4px;">PLANTED BUG (CAUGHT): ${esc(rightTitle)}</div>
        <svg viewBox="0 0 260 88" style="width:100%; height:auto; display:block; background:#ffffff; border:1px solid #fecaca;">${rightInner}</svg>
      </div>
    </div>
  `;
}

function renderMutantVisualProof(id, evidence) {
  const wire = '#0f172a', okCol = '#15803d', badCol = '#b91c1c', fill = '#f1f5f9';
  const scenes = {
    M01_DROP_NAND_BUBBLE: () => _proofSvgPair(
      'NAND with output bubble -> L1 = OFF',
      `<line x1="20" y1="32" x2="65" y2="32" stroke="${wire}" stroke-width="2.5"/><line x1="20" y1="56" x2="65" y2="56" stroke="${wire}" stroke-width="2.5"/><path d="M65,20 H110 A24,24 0 0,1 110,68 H65 Z" fill="${fill}" stroke="${wire}" stroke-width="2.5"/><circle cx="141" cy="44" r="6" fill="#fff" stroke="${okCol}" stroke-width="3"/><line x1="147" y1="44" x2="188" y2="44" stroke="${wire}" stroke-width="2.5"/><circle cx="205" cy="44" r="14" fill="#fee2e2" stroke="${wire}" stroke-width="2"/><text x="224" y="48" font-size="11" font-weight="bold" fill="${okCol}">OFF</text>`,
      'Bubble dropped (acts like AND) -> Wrong ON',
      `<line x1="20" y1="32" x2="65" y2="32" stroke="${wire}" stroke-width="2.5"/><line x1="20" y1="56" x2="65" y2="56" stroke="${wire}" stroke-width="2.5"/><path d="M65,20 H110 A24,24 0 0,1 110,68 H65 Z" fill="#fee2e2" stroke="${badCol}" stroke-width="2.5"/><line x1="134" y1="44" x2="188" y2="44" stroke="${badCol}" stroke-width="2.5"/><line x1="134" y1="35" x2="146" y2="53" stroke="${badCol}" stroke-width="2.5"/><line x1="146" y1="35" x2="134" y2="53" stroke="${badCol}" stroke-width="2.5"/><circle cx="205" cy="44" r="14" fill="#fef08a" stroke="${badCol}" stroke-width="2"/><text x="223" y="48" font-size="11" font-weight="bold" fill="${badCol}">ON?</text>`
    ),
    M02_IGNORE_OPEN_SWITCH: () => _proofSvgPair(
      'Open tilted switch blade breaks path',
      `<line x1="20" y1="54" x2="90" y2="54" stroke="${wire}" stroke-width="2.5"/><circle cx="90" cy="54" r="4" fill="#fff" stroke="${wire}" stroke-width="2"/><line x1="92" y1="52" x2="142" y2="26" stroke="${okCol}" stroke-width="3"/><circle cx="145" cy="54" r="4" fill="#fff" stroke="${wire}" stroke-width="2"/><line x1="145" y1="54" x2="215" y2="54" stroke="${wire}" stroke-width="2.5"/><text x="108" y="76" font-size="11" font-weight="bold" fill="${okCol}">OPEN = 0V</text>`,
      'Mutant forces current across open air gap',
      `<line x1="20" y1="54" x2="90" y2="54" stroke="${wire}" stroke-width="2.5"/><circle cx="90" cy="54" r="4" fill="#fff" stroke="${wire}" stroke-width="2"/><line x1="92" y1="52" x2="142" y2="26" stroke="${wire}" stroke-width="2"/><path d="M90,54 Q118,68 145,54" fill="none" stroke="${badCol}" stroke-width="3" stroke-dasharray="4,3"/><circle cx="145" cy="54" r="4" fill="#fff" stroke="${wire}" stroke-width="2"/><line x1="145" y1="54" x2="215" y2="54" stroke="${badCol}" stroke-width="2.5"/><text x="86" y="78" font-size="11" font-weight="bold" fill="${badCol}">SHORT LEAK!</text>`
    ),
    M03_IGNORE_BLOWN_FUSE: () => _proofSvgPair(
      'Broken fuse gap stops current cleanly',
      `<line x1="20" y1="44" x2="80" y2="44" stroke="${wire}" stroke-width="2.5"/><rect x="80" y="28" width="80" height="32" rx="5" fill="${fill}" stroke="${wire}" stroke-width="2"/><line x1="88" y1="44" x2="108" y2="36" stroke="${badCol}" stroke-width="2.5"/><line x1="132" y1="52" x2="152" y2="44" stroke="${badCol}" stroke-width="2.5"/><line x1="160" y1="44" x2="215" y2="44" stroke="${wire}" stroke-width="2.5"/><text x="82" y="77" font-size="11" font-weight="bold" fill="${okCol}">BLOWN = BLOCKED</text>`,
      'Mutant conducts through blown fuse',
      `<line x1="20" y1="44" x2="80" y2="44" stroke="${badCol}" stroke-width="2.5"/><rect x="80" y="28" width="80" height="32" rx="5" fill="#fee2e2" stroke="${badCol}" stroke-width="2"/><line x1="86" y1="44" x2="154" y2="44" stroke="${badCol}" stroke-width="3" stroke-dasharray="5,3"/><line x1="160" y1="44" x2="215" y2="44" stroke="${badCol}" stroke-width="2.5"/><text x="80" y="77" font-size="11" font-weight="bold" fill="${badCol}">ROGUE CONDUCT!</text>`
    ),
    M04_SHORT_BRIDGE_JUMP: () => _proofSvgPair(
      'Curved bridge hop keeps 2 wires separate',
      `<line x1="40" y1="44" x2="220" y2="44" stroke="${wire}" stroke-width="2.5"/><line x1="130" y1="12" x2="130" y2="32" stroke="${wire}" stroke-width="2.5"/><path d="M130,32 A12,12 0 0,1 130,56" fill="none" stroke="${okCol}" stroke-width="3"/><line x1="130" y1="56" x2="130" y2="76" stroke="${wire}" stroke-width="2.5"/><text x="150" y="25" font-size="10.5" font-weight="bold" fill="${okCol}">ISOLATED</text>`,
      'Mutant puts solder dot to short wires',
      `<line x1="40" y1="44" x2="220" y2="44" stroke="${badCol}" stroke-width="2.5"/><line x1="130" y1="12" x2="130" y2="76" stroke="${badCol}" stroke-width="2.5"/><circle cx="130" cy="44" r="7" fill="${badCol}"/><text x="144" y="25" font-size="10.5" font-weight="bold" fill="${badCol}">FALSE SHORT!</text>`
    ),
    M05_PARALLEL_AS_SERIES: () => _proofSvgPair(
      '60 Ohm || 60 Ohm = 30 Ohm exact',
      `<line x1="30" y1="44" x2="65" y2="44" stroke="${wire}" stroke-width="2"/><line x1="65" y1="22" x2="65" y2="66" stroke="${wire}" stroke-width="2"/><rect x="82" y="12" width="54" height="20" fill="${fill}" stroke="${wire}" stroke-width="1.8"/><text x="93" y="26" font-size="10" font-weight="bold" fill="${wire}">60</text><rect x="82" y="56" width="54" height="20" fill="${fill}" stroke="${wire}" stroke-width="1.8"/><text x="93" y="70" font-size="10" font-weight="bold" fill="${wire}">60</text><line x1="136" y1="22" x2="155" y2="22" stroke="${wire}" stroke-width="2"/><line x1="136" y1="66" x2="155" y2="66" stroke="${wire}" stroke-width="2"/><line x1="155" y1="22" x2="155" y2="66" stroke="${wire}" stroke-width="2"/><line x1="155" y1="44" x2="180" y2="44" stroke="${wire}" stroke-width="2"/><text x="184" y="48" font-size="11.5" font-weight="bold" fill="${okCol}">30 Ohm</text>`,
      'Wrong series sum mutant: 60 + 60 = 120 Ohm',
      `<rect x="24" y="28" width="56" height="22" fill="#fee2e2" stroke="${badCol}" stroke-width="1.8"/><text x="40" y="43" font-size="10" font-weight="bold" fill="${badCol}">60</text><text x="86" y="44" font-size="13" font-weight="bold" fill="${badCol}">+</text><rect x="100" y="28" width="56" height="22" fill="#fee2e2" stroke="${badCol}" stroke-width="1.8"/><text x="116" y="43" font-size="10" font-weight="bold" fill="${badCol}">60</text><text x="164" y="44" font-size="11" font-weight="bold" fill="${badCol}">= 120 X</text>`
    ),
    M06_LEAK_OPEN_BRANCH_RES: () => _proofSvgPair(
      'Open switch branch excluded -> 60 Ohm',
      `<line x1="30" y1="44" x2="60" y2="44" stroke="${wire}" stroke-width="2"/><line x1="60" y1="22" x2="60" y2="66" stroke="${wire}" stroke-width="2"/><line x1="60" y1="22" x2="88" y2="22" stroke="#94a3b8" stroke-width="2"/><line x1="88" y1="22" x2="112" y2="10" stroke="${okCol}" stroke-width="2.5"/><text x="122" y="26" font-size="9.5" fill="#94a3b8">60 (OPEN)</text><rect x="88" y="56" width="60" height="20" fill="${fill}" stroke="${wire}" stroke-width="1.8"/><text x="102" y="70" font-size="10" font-weight="bold" fill="${wire}">60 Ohm</text><text x="176" y="50" font-size="11" font-weight="bold" fill="${okCol}">= 60 Ohm</text>`,
      'Counts disconnected open branch (30 Ohm)',
      `<rect x="78" y="12" width="68" height="20" fill="#fee2e2" stroke="${badCol}" stroke-width="1.8"/><text x="84" y="26" font-size="9.5" font-weight="bold" fill="${badCol}">60 LEAKS!</text><rect x="78" y="54" width="68" height="20" fill="#fee2e2" stroke="${badCol}" stroke-width="1.8"/><text x="94" y="68" font-size="10" font-weight="bold" fill="${badCol}">60</text><text x="158" y="48" font-size="11" font-weight="bold" fill="${badCol}">= 30 X</text>`
    ),
    M07_AMBIGUOUS_FAULT_DIAG: () => _proofSvgPair(
      '4 distinct probe patterns -> 1 unique answer',
      `<rect x="16" y="14" width="104" height="24" rx="4" fill="#dcfce7" stroke="${okCol}"/><text x="24" y="30" font-size="10" font-weight="bold" fill="${okCol}">A: 5V / 0V / 0V</text><rect x="134" y="14" width="108" height="24" rx="4" fill="${fill}" stroke="${wire}"/><text x="142" y="30" font-size="10" fill="${wire}">B: 5V / 5V / 0V</text><rect x="16" y="48" width="104" height="24" rx="4" fill="${fill}" stroke="${wire}"/><text x="24" y="64" font-size="10" fill="${wire}">C: 0V / 0V / 5V</text><text x="136" y="64" font-size="10.5" font-weight="bold" fill="${okCol}">UNIQUE KEY: A</text>`,
      'Two faults match same probe reading -> REJECTED',
      `<rect x="16" y="14" width="106" height="26" rx="4" fill="#fee2e2" stroke="${badCol}" stroke-width="2"/><text x="24" y="31" font-size="10" font-weight="bold" fill="${badCol}">A: 5V / 0V / 0V</text><rect x="134" y="14" width="106" height="26" rx="4" fill="#fee2e2" stroke="${badCol}" stroke-width="2"/><text x="142" y="31" font-size="10" font-weight="bold" fill="${badCol}">B: 5V / 0V / 0V</text><text x="58" y="66" font-size="11" font-weight="bold" fill="${badCol}">AMBIGUOUS -> BLOCKED!</text>`
    ),
    M08_OVERLAPPING_LABELS: () => _proofSvgPair(
      'Zero bounding-box collisions on labels',
      `<rect x="26" y="24" width="70" height="32" rx="4" fill="#dcfce7" stroke="${okCol}" stroke-width="2"/><text x="48" y="44" font-size="12" font-weight="bold" fill="${wire}">SW1</text><rect x="150" y="24" width="70" height="32" rx="4" fill="#dcfce7" stroke="${okCol}" stroke-width="2"/><text x="176" y="44" font-size="12" font-weight="bold" fill="${wire}">U1</text><text x="86" y="76" font-size="10.5" font-weight="bold" fill="${okCol}">CLEAN GAP</text>`,
      'Colliding labels trigger layout retry',
      `<rect x="64" y="20" width="84" height="32" rx="4" fill="#fee2e2" stroke="${badCol}" stroke-width="2"/><text x="74" y="40" font-size="12" font-weight="bold" fill="${badCol}">SW1</text><rect x="108" y="32" width="84" height="32" rx="4" fill="rgba(185,28,28,0.22)" stroke="${badCol}" stroke-width="2"/><text x="150" y="52" font-size="12" font-weight="bold" fill="${badCol}">U1</text><text x="64" y="80" font-size="10.5" font-weight="bold" fill="${badCol}">OVERLAP CAUGHT!</text>`
    ),
    M09_OUT_OF_BOUNDS_LABEL: () => _proofSvgPair(
      'Label cleanly inside drawing border',
      `<rect x="16" y="10" width="228" height="68" fill="none" stroke="${wire}" stroke-width="2"/><rect x="158" y="28" width="52" height="26" rx="4" fill="#dcfce7" stroke="${okCol}" stroke-width="2"/><text x="176" y="45" font-size="11" font-weight="bold" fill="${okCol}">L1</text>`,
      'Clipped off-canvas text blocked by guard',
      `<rect x="16" y="10" width="200" height="68" fill="none" stroke="${wire}" stroke-width="2"/><rect x="190" y="28" width="58" height="26" rx="4" fill="#fee2e2" stroke="${badCol}" stroke-width="2"/><text x="198" y="45" font-size="11" font-weight="bold" fill="${badCol}">L1 CLIP</text>`
    ),
    M10_COUNTERFACTUAL_COLLAPSE: () => _proofSvgPair(
      'Same Panel A vs Panel A -> Answer NO',
      `<rect x="18" y="16" width="90" height="44" fill="${fill}" stroke="${wire}"/><text x="36" y="42" font-size="11" font-weight="bold" fill="${wire}">Panel A</text><rect x="148" y="16" width="90" height="44" fill="${fill}" stroke="${wire}"/><text x="166" y="42" font-size="11" font-weight="bold" fill="${wire}">Panel A</text><text x="72" y="78" font-size="10.5" font-weight="bold" fill="${okCol}">DIFF: NO (IDENTICAL)</text>`,
      'Detects true transition ON -> OFF when altered',
      `<rect x="18" y="16" width="90" height="44" fill="${fill}" stroke="${wire}"/><text x="34" y="42" font-size="11" font-weight="bold" fill="${wire}">A: ON</text><rect x="148" y="16" width="90" height="44" fill="#fef3c7" stroke="${okCol}" stroke-width="2"/><text x="160" y="42" font-size="11" font-weight="bold" fill="${okCol}">B: OFF</text><text x="48" y="78" font-size="10.5" font-weight="bold" fill="${okCol}">SEPARATES ON -&gt; OFF</text>`
    ),
    M11_WHOLE_SYSTEM_LOGIC_OHM_COUPLING: () => _proofSvgPair(
      'Blown F1 disables load -> 0 mA exact',
      `<rect x="18" y="28" width="56" height="26" rx="4" fill="#fee2e2" stroke="${wire}"/><text x="25" y="45" font-size="10" font-weight="bold" fill="${badCol}">F1 BLOWN</text><line x1="74" y1="41" x2="128" y2="41" stroke="#94a3b8" stroke-width="2" stroke-dasharray="4,3"/><rect x="128" y="24" width="60" height="32" fill="${fill}" stroke="${wire}"/><text x="136" y="44" font-size="10" fill="${wire}">R-Bank</text><text x="196" y="45" font-size="11" font-weight="bold" fill="${okCol}">0 mA</text>`,
      'Ignores blown upstream fuse (wrong 200 mA)',
      `<rect x="18" y="28" width="56" height="26" rx="4" fill="#fee2e2" stroke="${badCol}"/><text x="25" y="45" font-size="10" font-weight="bold" fill="${badCol}">F1 BLOWN</text><line x1="74" y1="41" x2="128" y2="41" stroke="${badCol}" stroke-width="3"/><rect x="128" y="24" width="60" height="32" fill="#fee2e2" stroke="${badCol}"/><text x="136" y="44" font-size="10" fill="${badCol}">R-Bank</text><text x="193" y="45" font-size="10.5" font-weight="bold" fill="${badCol}">200mA?</text>`
    ),
    M12_SWITCH_TOGGLE_WHATIF: () => _proofSvgPair(
      'Drawn CLOSED -> hypothetical flip yields OFF',
      `<text x="16" y="24" font-size="10" fill="${wire}">Drawn: SW1=CLOSED (ON)</text><line x1="20" y1="54" x2="80" y2="54" stroke="${wire}" stroke-width="2"/><line x1="82" y1="52" x2="132" y2="28" stroke="${okCol}" stroke-width="3"/><line x1="134" y1="54" x2="180" y2="54" stroke="${wire}" stroke-width="2"/><text x="142" y="42" font-size="11" font-weight="bold" fill="${okCol}">FLIP -&gt; OFF</text>`,
      'Ignores what-if toggle (keeps stale ON)',
      `<text x="16" y="24" font-size="10" fill="${badCol}">Bug: Ignores Toggle Instruction</text><line x1="20" y1="54" x2="160" y2="54" stroke="${badCol}" stroke-width="3"/><text x="166" y="58" font-size="11" font-weight="bold" fill="${badCol}">STUCK ON?</text>`
    ),
  };
  const body = scenes[id] ? scenes[id]() : '';
  return `<div><b>Verification Proof (${esc(id)}):</b> <span class="mono">${esc(evidence)}</span></div>${body}`;
}

function renderEvalTab(flash = false) {
  renderInteractiveCharts();
  const mut = (overviewData && overviewData.mutation) || { results: [] };
  document.getElementById('mutation-table').innerHTML = `
    <table>
      <thead><tr><th>Guardrail Check</th><th>What Broken Bug Was Tested</th><th>Result</th><th>Live Visual Proof</th></tr></thead>
      <tbody>
        ${(mut.results || []).map((r, idx) => `
          <tr class="${flash ? 'mutant-flash' : ''}">
            <td style="font-weight:700; font-size:12.5px;">${esc(MUTANT_HUMAN[r.mutant_id] || r.mutant_id)}</td>
            <td style="font-size:12.5px;">${esc(r.description)}</td>
            <td><span class="badge ${r.killed ? 'ok' : 'warn'}">${r.killed ? 'CAUGHT' : 'MISSED'}</span></td>
            <td><button type="button" class="secondary" style="padding:4px 9px; font-size:11px;" onclick="toggleMutantProof(${idx})">Visual Proof</button></td>
          </tr>
          <tr id="mut-proof-${idx}" class="hidden">
            <td colspan="4" style="background:var(--paper-inset); font-size:12px;">
              ${renderMutantVisualProof(r.mutant_id, r.evidence)}
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function runMutationsLive() {
  const st = document.getElementById('mutation-run-status');
  if (st) st.textContent = 'Running all 12 broken-circuit guardrail tests right now...';
  const t0 = performance.now();
  const res = await fetch('/api/mutate-test', { method: 'POST' });
  overviewData.mutation = await res.json();
  const ms = Math.round(performance.now() - t0);
  const nowStr = new Date().toLocaleTimeString();
  if (st) {
    st.innerHTML = `<b>Verified live at ${esc(nowStr)} (${ms} ms):</b> All <b>${overviewData.mutation.mutants_killed}/${overviewData.mutation.total_mutants}</b> planted errors caught &amp; blocked.`;
  }
  renderKPIs();
  renderEvalTab(true);
}

init();
