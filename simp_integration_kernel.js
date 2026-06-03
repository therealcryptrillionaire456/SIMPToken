/**
 * ═══════════════════════════════════════════════════════════════════════════
 * SIMPWallet Integration Kernel — v1.0
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Embed this into simptoken.uk to add a live SIMPWallet dashboard.
 *
 * HOW TO DEPLOY:
 *   Option A — If you control the server:
 *     1. Copy the `dashboard/static/simpwallet.css` file to your webroot
 *     2. Copy the `dashboard/static/simpwallet.js` file to your webroot
 *     3. Copy this file (simp_integration_kernel.js) to your webroot
 *     4. Add to the site's <head>:
 *        <link rel="stylesheet" href="/simpwallet.css">
 *     5. Add before </body>:
 *        <script src="/simpwallet.js"></script>
 *        <script src="/simp_integration_kernel.js"></script>
 *
 *   Option B — Pure HTML embed (no file server needed):
 *     Copy the entire CSS inline into a <style> block
 *     Copy the entire JS inline into a <script> block
 *     Use the HTML snippet below
 *
 *   Option C — Proxy the broker (recommended for production):
 *     Set up nginx/caddy to proxy /api/simpwallet/* → https://127.0.0.1:5555/v1/explorer/simpwallet/*
 *     Then change BROKER_URL below to your domain
 * ═══════════════════════════════════════════════════════════════════════════
 */

(function() {
  'use strict';

  // ── CONFIG ──────────────────────────────────────────────────────────────
  // Change this to your broker URL. If proxied via nginx, use relative path.
  const CONFIG = {
    // Option A: Direct to live broker (localhost only — dev/test)
    // BROKER_URL: 'https://127.0.0.1:5555',

    // Option B: Proxied via your domain (production)
    BROKER_URL: 'https://simptoken.uk/api/simpwallet',

    // Option C: Fallback if the proxy is down
    FALLBACK_URL: 'https://api.simptoken.uk/simpwallet',

    // How often to refresh (ms)
    REFRESH_INTERVAL: 30000,

    // Token addresses for display
    V1_MINT: 'CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt',
    V2_MINT: '6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mpnwDH',
    WHALE_WALLET: '58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB',
  };

  // ── DOM TEMPLATES ───────────────────────────────────────────────────────

  const TEMPLATES = {
    container: function() {
      return `
        <section id="simpwallet" style="padding: 80px 24px; background: #0A0A0A;">
          <div style="max-width: 1200px; margin: 0 auto;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; flex-wrap: wrap; gap: 16px;">
              <div>
                <h2 style="font-size: 28px; font-weight: 700; color: #fff; margin: 0; font-family: 'JetBrains Mono', monospace; display: flex; align-items: center; gap: 12px;">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#7C3AED" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
                  SIMPWallet
                </h2>
                <p style="color: rgba(255,255,255,0.55); margin: 4px 0 0 0; font-size: 14px;">
                  Live token &amp; mesh economy explorer.
                  <span id="simpwallet-last-refresh" style="color:#5a6477;font-size:12px;"></span>
                </p>
              </div>
              <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <span style="display:inline-flex;align-items:center;gap:4px;padding:4px 10px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:999px;font-size:11px;color:#10B981;">
                  <span style="width:6px;height:6px;border-radius:50%;background:#10B981;display:inline-block;"></span>
                  Solana Mainnet
                </span>
                <span id="simpwallet-mesh-tag" style="display:inline-flex;align-items:center;gap:4px;padding:4px 10px;background:rgba(124,58,237,0.15);border:1px solid rgba(124,58,237,0.3);border-radius:999px;font-size:11px;color:#7C3AED;">
                  <span style="width:6px;height:6px;border-radius:50%;background:#7C3AED;display:inline-block;"></span>
                  Mesh Loading...
                </span>
                <button onclick="window.SIMP_WALLET_REFRESH()" style="padding:6px 14px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#fff;font-size:12px;cursor:pointer;">⟳ Refresh</button>
              </div>
            </div>

            <!-- Loading -->
            <div id="simpwallet-loading" style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 0;gap:16px;">
              <div style="width:32px;height:32px;border:2px solid rgba(124,58,237,0.2);border-top-color:#7C3AED;border-radius:50%;animation:spin 0.8s linear infinite;"></div>
              <span style="color:rgba(255,255,255,0.35);font-size:14px;">Loading token state...</span>
            </div>

            <!-- Error -->
            <div id="simpwallet-error" style="display:none;padding:24px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);border-radius:12px;color:#EF4444;font-size:14px;text-align:center;margin-bottom:24px;"></div>

            <!-- Dashboard Content -->
            <div id="simpwallet-content" style="display:none;">
              <!-- Tabs -->
              <div style="display:flex;gap:4px;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:24px;flex-wrap:wrap;">
                <button class="simpwallet-tab-btn active" data-tab="onchain" onclick="switchSimpWalletTab('onchain')" style="padding:10px 18px;background:none;border:none;border-bottom:2px solid #7C3AED;color:#fff;font-size:13px;font-weight:500;cursor:pointer;">On-Chain</button>
                <button class="simpwallet-tab-btn" data-tab="mesh" onclick="switchSimpWalletTab('mesh')" style="padding:10px 18px;background:none;border:none;border-bottom:2px solid transparent;color:rgba(255,255,255,0.5);font-size:13px;cursor:pointer;">Mesh</button>
                <button class="simpwallet-tab-btn" data-tab="trust" onclick="switchSimpWalletTab('trust')" style="padding:10px 18px;background:none;border:none;border-bottom:2px solid transparent;color:rgba(255,255,255,0.5);font-size:13px;cursor:pointer;">Trust</button>
                <button class="simpwallet-tab-btn" data-tab="wallet" onclick="switchSimpWalletTab('wallet')" style="padding:10px 18px;background:none;border:none;border-bottom:2px solid transparent;color:rgba(255,255,255,0.5);font-size:13px;cursor:pointer;">Whale</button>
              </div>

              <!-- On-Chain Tab -->
              <div class="simpwallet-panel" id="panel-onchain">
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;" id="simpwallet-onchain-grid"></div>
                <div style="margin-top:16px;padding:16px;background:rgba(255,255,255,0.03);border-radius:8px;">
                  <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                    <span style="color:rgba(255,255,255,0.5);font-size:13px;">Whale Concentration</span>
                    <span style="color:#10B981;font-size:13px;font-weight:600;">100%</span>
                  </div>
                  <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:99px;overflow:hidden;">
                    <div style="height:100%;width:100%;background:linear-gradient(90deg,#7C3AED,#10B981);border-radius:99px;"></div>
                  </div>
                  <p style="color:rgba(255,255,255,0.35);font-size:11px;margin-top:8px;">1 holder controls entire supply — distribution needed for mesh economy</p>
                </div>
              </div>

              <!-- Mesh Tab -->
              <div class="simpwallet-panel" id="panel-mesh" style="display:none;">
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;" id="simpwallet-mesh-grid"></div>
                <div style="margin-top:16px;" id="simpwallet-top-agents"></div>
              </div>

              <!-- Trust Tab -->
              <div class="simpwallet-panel" id="panel-trust" style="display:none;">
                <div id="simpwallet-trust-content"></div>
              </div>

              <!-- Wallet Tab -->
              <div class="simpwallet-panel" id="panel-wallet" style="display:none;">
                <div id="simpwallet-wallet-content"></div>
              </div>
            </div>
          </div>
        </section>

        <style>
          @keyframes spin { to { transform: rotate(360deg); } }
          .simpwallet-tab-btn:hover { color: #fff !important; }
          .simpwallet-stat-card {
            padding: 20px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px; transition: border-color 0.2s;
          }
          .simpwallet-stat-card:hover { border-color: rgba(124,58,237,0.3); }
          .simpwallet-stat-label { font-size: 11px; color: rgba(255,255,255,0.35); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
          .simpwallet-stat-value { font-size: 22px; font-weight: 700; color: #fff; font-family: 'JetBrains Mono', monospace; }
          .simpwallet-stat-note { font-size: 11px; color: rgba(255,255,255,0.25); margin-top: 4px; }
          .simpwallet-agent-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 12px 16px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04);
            border-radius: 8px; margin-bottom: 6px;
          }
          .simpwallet-agent-row:hover { background: rgba(124,58,237,0.05); border-color: rgba(124,58,237,0.15); }
        </style>
      `;
    },

    statCard: function(label, value, note) {
      return `
        <div class="simpwallet-stat-card">
          <div class="simpwallet-stat-label">${label}</div>
          <div class="simpwallet-stat-value">${value}</div>
          <div class="simpwallet-stat-note">${note || ''}</div>
        </div>
      `;
    }
  };

  // ── STATE ───────────────────────────────────────────────────────────────
  let state = {
    dashboard: null,
    onchain: null,
    mesh: null,
    trustGraph: null,
    wallet: null,
    lastRefresh: null,
  };

  // ── API ─────────────────────────────────────────────────────────────────

  function apiUrl(endpoint) {
    return CONFIG.BROKER_URL + endpoint;
  }

  async function apiGet(endpoint) {
    const url = apiUrl(endpoint);
    try {
      const resp = await fetch(url, {
        headers: { 'Accept': 'application/json' }
      });
      if (!resp.ok) {
        // Try fallback
        const fallback = CONFIG.FALLBACK_URL + endpoint;
        const resp2 = await fetch(fallback, {
          headers: { 'Accept': 'application/json' }
        });
        if (!resp2.ok) throw new Error(`HTTP ${resp2.status}`);
        return await resp2.json();
      }
      return await resp.json();
    } catch (e) {
      throw e;
    }
  }

  // ── RENDERERS ───────────────────────────────────────────────────────────

  function renderOnchain(data) {
    const grid = document.getElementById('simpwallet-onchain-grid');
    if (!grid) return;

    const supply = data.supply_ui || data.supply || 'N/A';
    const supplyFormatted = typeof supply === 'number'
      ? supply.toLocaleString()
      : supply;

    grid.innerHTML = [
      TEMPLATES.statCard('Total Supply', `${supplyFormatted} SIMPT`, 'Fixed, mint authority revoked'),
      TEMPLATES.statCard('Holders', data.holders || 'N/A', 'Whale has 100%'),
      TEMPLATES.statCard('Mint Authority', data.mint_authority === null ? '🔥 Revoked' : 'Active', 'Permanently disabled'),
      TEMPLATES.statCard('Token Program', 'Token-2022', 'State-carrying enabled'),
      TEMPLATES.statCard('Recent TX', data.recent_tx_count || 'N/A', 'Last 24h'),
      TEMPLATES.statCard('Verified At', new Date(data.verified_at || Date.now()).toLocaleTimeString(), 'Solana mainnet'),
    ].join('');
  }

  function renderMesh(data) {
    const grid = document.getElementById('simpwallet-mesh-grid');
    const agentsEl = document.getElementById('simpwallet-top-agents');
    if (!grid) return;

    grid.innerHTML = [
      TEMPLATES.statCard('Total Agents', data.total_agents || 0, 'Registered in mesh'),
      TEMPLATES.statCard('Avg Trust', data.avg_trust_score ? data.avg_trust_score.toFixed(3) : '0', 'Trust-weighted'),
      TEMPLATES.statCard('Intents (24h)', data.intents_24h || 0, 'Agent message volume'),
      TEMPLATES.statCard('Fees (24h)', `${(data.fees_collected_24h_simp || 0).toFixed(2)} SIMP`, 'Economic activity'),
    ].join('');

    if (agentsEl && data.top_agents && data.top_agents.length) {
      agentsEl.innerHTML = `
        <div style="margin-top:8px;">
          <div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px;">Top Agents by Balance</div>
          ${data.top_agents.slice(0, 8).map(a => `
            <div class="simpwallet-agent-row">
              <span style="color:#fff;font-size:13px;font-family:'JetBrains Mono',monospace;">${a.agent_id || a.agent}</span>
              <div style="display:flex;gap:16px;align-items:center;">
                <span style="color:rgba(255,255,255,0.45);font-size:12px;">Trust: ${(a.trust_score || 0).toFixed(1)}</span>
                <span style="color:#10B981;font-size:13px;font-weight:500;">${(a.balance_simp || 0).toFixed(2)} SIMP</span>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    // Update mesh tag
    const tag = document.getElementById('simpwallet-mesh-tag');
    if (tag) {
      tag.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:#10B981;display:inline-block;"></span> ${data.total_agents || 0} Agents`;
    }
  }

  function renderTrust(data) {
    const el = document.getElementById('simpwallet-trust-content');
    if (!el) return;

    const edges = data.edges || data.trust_edges || [];
    if (!edges.length) {
      el.innerHTML = `<p style="color:rgba(255,255,255,0.35);text-align:center;padding:40px;">No trust relationships yet — agents need to transact.</p>`;
      return;
    }

    el.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;">
        ${edges.slice(0, 12).map(e => `
          <div style="padding:14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="color:#fff;font-size:12px;font-family:'JetBrains Mono',monospace;">${e.from || e.source}</span>
              <span style="color:rgba(255,255,255,0.25);font-size:11px;">→</span>
              <span style="color:#fff;font-size:12px;font-family:'JetBrains Mono',monospace;">${e.to || e.target}</span>
            </div>
            <div style="margin-top:8px;display:flex;justify-content:space-between;">
              <span style="color:rgba(255,255,255,0.35);font-size:11px;">Trust</span>
              <span style="color:${(e.trust || e.weight || 0) > 3 ? '#10B981' : '#F59E0B'};font-size:14px;font-weight:600;">${(e.trust || e.weight || 0).toFixed(1)}</span>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderWallet(data) {
    const el = document.getElementById('simpwallet-wallet-content');
    if (!el) return;

    if (!data || data.error) {
      el.innerHTML = `<p style="color:rgba(255,255,255,0.35);text-align:center;padding:40px;">Could not fetch wallet data.</p>`;
      return;
    }

    const tokens = data.token_accounts || [];
    const roles = data.known_roles || [];

    el.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px;">
        ${TEMPLATES.statCard('SOL Balance', `${data.sol_balance || '0'} SOL`, 'Native')}
        ${TEMPLATES.statCard('Token Accounts', tokens.length, 'SPL tokens held')}
        ${TEMPLATES.statCard('Roles', roles.slice(0,3).join(', '), roles.length > 3 ? `+${roles.length-3} more` : '')}
      </div>
      ${tokens.length ? `
        <div style="padding:16px;background:rgba(255,255,255,0.03);border-radius:8px;">
          <div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px;">Token Holdings</div>
          ${tokens.slice(0, 5).map(t => `
            <div class="simpwallet-agent-row">
              <span style="color:#fff;font-size:12px;font-family:'JetBrains Mono',monospace;">${(t.mint || t.address || '').slice(0, 12)}...</span>
              <span style="color:#10B981;font-size:13px;font-weight:500;">${t.amount_ui || t.balance || 'N/A'}</span>
            </div>
          `).join('')}
        </div>
      ` : ''}
    `;
  }

  // ── MAIN REFRESH ───────────────────────────────────────────────────────

  async function refreshAll() {
    try {
      document.getElementById('simpwallet-loading').style.display = 'flex';
      document.getElementById('simpwallet-content').style.display = 'none';
      document.getElementById('simpwallet-error').style.display = 'none';

      // Fetch all data in parallel
      const [dashboard, onchain, mesh, trustGraph, wallet] = await Promise.all([
        apiGet('/dashboard').catch(() => ({})),
        apiGet('/onchain').catch(() => ({})),
        apiGet('/mesh').catch(() => ({})),
        apiGet('/trustgraph').catch(() => ({})),
        apiGet('/wallet/' + CONFIG.WHALE_WALLET).catch(() => ({})),
      ]);

      state.dashboard = dashboard;
      state.onchain = onchain;
      state.mesh = mesh;
      state.trustGraph = trustGraph;
      state.wallet = wallet;
      state.lastRefresh = new Date();

      // Render
      renderOnchain(onchain);
      renderMesh(mesh);
      renderTrust(trustGraph);
      renderWallet(wallet);

      // Update last refresh
      const refreshEl = document.getElementById('simpwallet-last-refresh');
      if (refreshEl) {
        refreshEl.textContent = `Last updated: ${state.lastRefresh.toLocaleTimeString()}`;
      }

      // Show content
      document.getElementById('simpwallet-loading').style.display = 'none';
      document.getElementById('simpwallet-content').style.display = 'block';
    } catch (e) {
      document.getElementById('simpwallet-loading').style.display = 'none';
      const errorEl = document.getElementById('simpwallet-error');
      if (errorEl) {
        errorEl.style.display = 'block';
        errorEl.innerHTML = `⚠️ Could not connect to SIMP broker. The data will appear when the broker is online. <span style="color:rgba(255,255,255,0.25);font-size:12px;">(${e.message || e})</span>`;
      }
      // Show cached content if available
      document.getElementById('simpwallet-content').style.display = 'block';
    }
  }

  // ── TAB SWITCHING ───────────────────────────────────────────────────────

  window.switchSimpWalletTab = function(tabId) {
    document.querySelectorAll('.simpwallet-panel').forEach(p => p.style.display = 'none');
    document.querySelectorAll('.simpwallet-tab-btn').forEach(b => {
      b.style.borderBottomColor = 'transparent';
      b.style.color = 'rgba(255,255,255,0.5)';
    });

    const panel = document.getElementById('panel-' + tabId);
    if (panel) panel.style.display = 'block';

    const btn = document.querySelector(`.simpwallet-tab-btn[data-tab="${tabId}"]`);
    if (btn) {
      btn.style.borderBottomColor = '#7C3AED';
      btn.style.color = '#fff';
    }
  };

  window.SIMP_WALLET_REFRESH = refreshAll;

  // ── INIT ────────────────────────────────────────────────────────────────

  function inject() {
    // Check if already injected
    if (document.getElementById('simpwallet')) return;

    // Find a good insertion point — after tokenomics section, before footer
    const tokenomics = document.getElementById('tokenomics');
    const footer = document.querySelector('footer');
    const howtobuy = document.getElementById('howtobuy');

    let insertBefore = footer || howtobuy?.nextElementSibling || document.body.lastElementChild;

    const temp = document.createElement('div');
    temp.innerHTML = TEMPLATES.container();
    const section = temp.firstElementChild;

    if (insertBefore && insertBefore.parentNode) {
      insertBefore.parentNode.insertBefore(section, insertBefore);
    } else {
      document.body.appendChild(section);
    }

    // Start refresh cycle
    refreshAll();
    setInterval(refreshAll, CONFIG.REFRESH_INTERVAL);
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
