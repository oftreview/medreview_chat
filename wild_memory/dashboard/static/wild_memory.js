/**
 * Wild Memory Dashboard — Shared JavaScript
 * Polling, chart rendering, API helpers, and UI utilities.
 * Zero dependencies (vanilla JS). Chart.js loaded via CDN in templates.
 */

const WM = {
  // ── Configuration ─────────────────────────────────────────
  BASE: '/wild-memory',
  POLL_INTERVAL: 10000,  // 10 seconds
  _timers: [],

  // ── API Helpers ───────────────────────────────────────────
  async api(endpoint, options = {}) {
    const url = `${this.BASE}/api/${endpoint}`;
    try {
      const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      console.warn(`[WM] API error (${endpoint}):`, err.message);
      return null;
    }
  },

  async get(endpoint) {
    return this.api(endpoint);
  },

  async post(endpoint, body = {}) {
    return this.api(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  async put(endpoint, body = {}) {
    return this.api(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },

  // ── Polling ───────────────────────────────────────────────
  poll(endpoint, callback, interval = null) {
    const ms = interval || this.POLL_INTERVAL;
    const run = async () => {
      const data = await this.get(endpoint);
      if (data) callback(data);
    };
    run(); // immediate first call
    const timer = setInterval(run, ms);
    this._timers.push(timer);
    return timer;
  },

  stopPolling() {
    this._timers.forEach(t => clearInterval(t));
    this._timers = [];
  },

  // ── Formatting ────────────────────────────────────────────
  formatNumber(n) {
    if (n === null || n === undefined) return '—';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
  },

  formatMs(ms) {
    if (ms === null || ms === undefined || ms === 0) return '—';
    if (ms < 1000) return ms.toFixed(0) + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  },

  formatTime(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      const now = new Date();
      const diffMs = now - d;
      const diffMin = Math.floor(diffMs / 60000);
      const diffHr = Math.floor(diffMs / 3600000);
      const diffDay = Math.floor(diffMs / 86400000);

      if (diffMin < 1) return 'agora';
      if (diffMin < 60) return `${diffMin}min atrás`;
      if (diffHr < 24) return `${diffHr}h atrás`;
      if (diffDay < 7) return `${diffDay}d atrás`;
      return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
    } catch {
      return isoStr;
    }
  },

  formatScore(score, decimals = 2) {
    if (score === null || score === undefined) return '—';
    return parseFloat(score).toFixed(decimals);
  },

  // ── DOM Helpers ───────────────────────────────────────────
  $(selector) {
    return document.querySelector(selector);
  },

  $$(selector) {
    return document.querySelectorAll(selector);
  },

  setText(selector, text) {
    const el = this.$(selector);
    if (el) el.textContent = text;
  },

  setHtml(selector, html) {
    const el = this.$(selector);
    if (el) el.innerHTML = html;
  },

  show(selector) {
    const el = this.$(selector);
    if (el) el.style.display = '';
  },

  hide(selector) {
    const el = this.$(selector);
    if (el) el.style.display = 'none';
  },

  // ── Tag Rendering ─────────────────────────────────────────
  renderTag(text, cls = '') {
    return `<span class="wm-tag ${cls}">${this.escapeHtml(text)}</span>`;
  },

  renderEntityTags(entities) {
    if (!entities || !entities.length) return '';
    return entities.map(e => this.renderTag(e, 'entity')).join('');
  },

  renderTypeTag(obsType) {
    return this.renderTag(obsType, obsType);
  },

  renderStatusTag(status) {
    return this.renderTag(status, status);
  },

  // ── Importance / Decay Bars ───────────────────────────────
  renderImportanceBar(importance, max = 10) {
    const pct = (importance / max) * 100;
    const cls = pct >= 70 ? 'green' : pct >= 40 ? 'yellow' : 'red';
    return `<div class="wm-bar-wrap" style="width:60px" title="Importance: ${importance}/${max}">
      <div class="wm-bar ${cls}" style="width:${pct}%"></div>
    </div>`;
  },

  renderDecayBar(score) {
    const pct = score * 100;
    const cls = pct >= 60 ? 'green' : pct >= 30 ? 'yellow' : 'red';
    return `<div class="wm-bar-wrap" style="width:60px" title="Decay: ${(score).toFixed(2)}">
      <div class="wm-bar ${cls}" style="width:${pct}%"></div>
    </div>`;
  },

  // ── Feed Icon Mapping ─────────────────────────────────────
  ICONS: {
    bee: '🐝',
    salmon: '🐟',
    elephant: '🐘',
    dolphin: '🐬',
    ant: '🐜',
    chameleon: '🦎',
    observation: '🐝',
    feedback: '🦎',
    reflection: '🐜',
    entity: '🐬',
    maintenance: '🐜',
    retrieval: '🐘',
  },

  getIcon(type) {
    return this.ICONS[type] || '📋';
  },

  // ── Health Dot ────────────────────────────────────────────
  renderPulseDot(isOn) {
    return `<span class="wm-pulse-dot ${isOn ? 'on' : 'off'}"></span>`;
  },

  // ── Security ──────────────────────────────────────────────
  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  // ── Chart Helpers (requires Chart.js) ─────────────────────
  charts: {},

  createChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Destroy existing chart
    if (this.charts[canvasId]) {
      this.charts[canvasId].destroy();
    }

    const ctx = canvas.getContext('2d');
    const chart = new Chart(ctx, {
      ...config,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#64748b', font: { size: 11 } },
          },
        },
        scales: config.options?.scales ? {
          ...config.options.scales,
          x: {
            ...config.options.scales?.x,
            ticks: { color: '#475569', font: { size: 10 } },
            grid: { color: 'rgba(100,116,139,0.08)' },
          },
          y: {
            ...config.options.scales?.y,
            ticks: { color: '#475569', font: { size: 10 } },
            grid: { color: 'rgba(100,116,139,0.08)' },
          },
        } : undefined,
        ...config.options,
      },
    });

    this.charts[canvasId] = chart;
    return chart;
  },

  // ── Loading State ─────────────────────────────────────────
  renderLoading() {
    return '<div class="wm-loading"><div class="wm-spinner"></div> Carregando...</div>';
  },

  renderEmpty(emoji, text) {
    return `<div class="wm-empty">
      <div class="wm-empty-emoji">${emoji}</div>
      <div class="wm-empty-text">${text}</div>
    </div>`;
  },

  // ── Initialization ────────────────────────────────────────
  init() {
    // Stop polling when leaving page
    window.addEventListener('beforeunload', () => this.stopPolling());
  },
};

// Auto-init
WM.init();
