/**
 * SIMPWallet — AI-Native State-Carrying Token Explorer
 * ====================================================
 * 
 * A real-time dashboard that combines on-chain Solana data with
 * agent mesh intelligence. Solcan shows you transactions.
 * SIMPWallet shows you the entire SIMP economy.
 * 
 * Architecture:
 *   ├─ On-Chain Layer    → /v1/explorer/simpwallet/onchain
 *   ├─ Mesh Layer        → /v1/explorer/simpwallet/mesh
 *   ├─ Trust Graph       → /v1/explorer/simpwallet/trustgraph
 *   ├─ State Memos       → /v1/explorer/simpwallet/statememos
 *   ├─ Wallet Analysis   → /v1/explorer/simpwallet/wallet/<address>
 *   ├─ Convergence       → /v1/explorer/simpwallet/convergence
 *   └─ Offline Metrics   → /v1/explorer/simpwallet/offline
 */
(function () {
  'use strict';

  // ── Configuration ──────────────────────────────────────────────────────

  const BROKER_URL = window.SIMP_BROKER_URL || 'http://127.0.0.1:5555';
  const API_BASE = BROKER_URL + '/v1/explorer/simpwallet';
  const REFRESH_INTERVAL = 15000; // 15 seconds

  // ── State ───────────────────────────────────────────────────────────────

  const state = {
    onchain: null,
    mesh: null,
    trustgraph: null,
    memos: null,
    convergence: null,
    offline: null,
    threat: null,
    walletResult: null,
    activeTab: 'onchain',
    lastRefresh: null,
    refreshIntervalId: null,
  };

  // ── DOM Cache ───────────────────────────────────────────────────────────

  let DOM = {};

  function cacheDOM() {
    DOM.section = document.getElementById('simpwallet-section');
    DOM.tabs = DOM.section?.querySelectorAll('.simpwallet-tab');
    DOM.contents = DOM.section?.querySelectorAll('.simpwallet-tab-content');
    DOM.tokenHero = document.getElementById('token-hero');
    DOM.onchainGrid = document.getElementById('onchain-grid');
    DOM.meshGrid = document.getElementById('mesh-grid');
    DOM.meshTiers = document.getElementById('mesh-tiers');
    DOM.graphCanvas = document.getElementById('graph-canvas');
    DOM.graphLegend = document.getElementById('graph-legend');
    DOM.memoList = document.getElementById('memo-list');
    DOM.memoCount = document.getElementById('memo-count');
    DOM.walletInput = document.getElementById('wallet-input');
    DOM.walletBtn = document.getElementById('wallet-analyze-btn');
    DOM.walletResult = document.getElementById('wallet-result');
    DOM.convergenceBody = document.getElementById('convergence-body');
    DOM.offlineStatus = document.getElementById('offline-status');
    DOM.lastRefresh = document.getElementById('simpwallet-last-refresh');
    DOM.navLink = document.getElementById('nav-simpwallet');
  }

  // ── API Client ──────────────────────────────────────────────────────────

  async function apiGet(endpoint) {
    const url = API_BASE + endpoint;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    return resp.json();
  }

  // ── Data Fetching ───────────────────────────────────────────────────────

  async function fetchAll() {
    const fetches = [
      apiGet('/dashboard').then(d => {
        state.onchain = d.onchain;
        state.mesh = d.mesh;
        state.convergence = d.convergence;
        state.offline = d.offline_resilience;
        state.lastRefresh = d.generated_at;
      }).catch(e => console.warn('Dashboard fetch failed:', e)),

      apiGet('/trustgraph').then(d => {
        state.trustgraph = d.edges || [];
      }).catch(e => console.warn('Trust graph fetch failed:', e)),

      apiGet('/statememos?limit=50').then(d => {
        state.memos = d.transfers_with_state || [];
      }).catch(e => console.warn('Memos fetch failed:', e)),

      apiGet('/threat').then(d => {
        state.threat = d;
      }).catch(e => { state.threat = null; }),
    ];

    await Promise.allSettled(fetches);
    render();
  }

  async function refresh() {
    const start = performance.now();
    await fetchAll();
    const elapsed = Math.round(performance.now() - start);
    updateLastRefresh(elapsed);
  }

  // ── Render ──────────────────────────────────────────────────────────────

  function render() {
    renderTokenHero();
    renderOnchain();
    renderMesh();
    renderTrustGraph();
    renderMemos();
    renderConvergence();
    renderOffline();
    renderThreat();
  }

  function renderTokenHero() {
    if (!DOM.tokenHero || !state.onchain) return;

    const o = state.onchain;
    DOM.tokenHero.innerHTML = `
      <div class="token-hero-top">
        <div class="token-hero-title">
          <div class="token-hero-avatar">S</div>
          <div class="token-hero-name">
            <h3>SIMPT</h3>
            <span>${o.mint}</span>
          </div>
        </div>
        <div class="token-hero-badges">
          <span class="token-hero-badge mint-disabled">Mint Disabled</span>
          <span class="token-hero-badge freeze-disabled">Freeze Disabled</span>
          <span class="token-hero-badge token2022">Token-2022</span>
          <span class="token-hero-badge update-authority">Update Authority Active</span>
        </div>
      </div>
      <div class="token-hero-stats">
        <div class="token-hero-stat">
          <div class="token-hero-stat-label">Total Supply</div>
          <div class="token-hero-stat-value green">${o.supply_ui?.toLocaleString() || '—'}</div>
          <div class="token-hero-stat-sub">${o.decimals} decimals</div>
        </div>
        <div class="token-hero-stat">
          <div class="token-hero-stat-label">Holders</div>
          <div class="token-hero-stat-value gold">${o.holders_count || '—'}</div>
          <div class="token-hero-stat-sub">wallet addresses</div>
        </div>
        <div class="token-hero-stat">
          <div class="token-hero-stat-label">Whale Holding</div>
          <div class="token-hero-stat-value blue">${o.whale_pct || 0}%</div>
          <div class="token-hero-stat-sub">${o.whale_balance?.toLocaleString() || 0} SIMPT</div>
        </div>
        <div class="token-hero-stat">
          <div class="token-hero-stat-label">Program</div>
          <div class="token-hero-stat-value purple">${o.program?.split('_')[0] || 'Token-2022'}</div>
          <div class="token-hero-stat-sub">${o.recent_tx_count || 0} recent TXs</div>
        </div>
      </div>
    `;
  }

  function renderOnchain() {
    if (!DOM.onchainGrid || !state.onchain) return;

    const o = state.onchain;
    DOM.onchainGrid.innerHTML = `
      <div class="onchain-card">
        <h4>🔗 Token Details</h4>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Mint</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#c0c6d0;word-break:break-all;max-width:200px;text-align:right;">${o.mint}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Supply (raw)</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#e0e4ea;">${o.supply_raw?.toLocaleString() || '—'}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Supply (UI)</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#22c55e;font-weight:600;">${o.supply_ui?.toLocaleString() || '—'}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Decimals</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#e0e4ea;">${o.decimals || 6}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Mint Authority</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:${o.mint_authority === null ? '#22c55e' : '#ffb74d'};">${o.mint_authority === null ? '🔒 DISABLED' : o.mint_authority}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8b95a5;font-size:12px;">Freeze Authority</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:${o.freeze_authority === null ? '#22c55e' : '#ffb74d'};">${o.freeze_authority === null ? '🔒 DISABLED' : o.freeze_authority}</span>
          </div>
        </div>
      </div>
      <div class="onchain-card">
        <h4>🐋 Top Holders</h4>
        <div class="holder-list" id="holder-list">
          <div class="holder-row">
            <div class="holder-address">58Eohzq...PpB</div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="holder-balance">${o.whale_balance?.toLocaleString() || '—'}</span>
              <span class="holder-pct">${o.whale_pct || 0}%</span>
            </div>
          </div>
        </div>
      </div>
      <div class="onchain-card">
        <h4>🔎 Quick Links</h4>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <a href="https://solscan.io/token/${o.mint}" target="_blank" style="color:#4f98a3;font-size:13px;text-decoration:none;display:flex;align-items:center;gap:6px;">
            <span>→</span> Solscan: SIMPT Token
          </a>
          <a href="https://solscan.io/address/${o.mint}" target="_blank" style="color:#4f98a3;font-size:13px;text-decoration:none;display:flex;align-items:center;gap:6px;">
            <span>→</span> Solscan: Mint Account
          </a>
          <a href="https://solscan.io/address/58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB" target="_blank" style="color:#4f98a3;font-size:13px;text-decoration:none;display:flex;align-items:center;gap:6px;">
            <span>→</span> Solscan: Whale Wallet
          </a>
        </div>
      </div>
    `;
  }

  function renderMesh() {
    if (!DOM.meshGrid || !state.mesh) return;

    const m = state.mesh;
    
    // Metrics
    DOM.meshGrid.innerHTML = `
      <div class="mesh-metric">
        <div class="mesh-metric-value">${m.total_agents || 0}</div>
        <div class="mesh-metric-label">Total Agents</div>
      </div>
      <div class="mesh-metric">
        <div class="mesh-metric-value green">${m.active_agents_5m || 0}</div>
        <div class="mesh-metric-label">Active (5 min)</div>
      </div>
      <div class="mesh-metric">
        <div class="mesh-metric-value">${m.intents_24h || 0}</div>
        <div class="mesh-metric-label">Intents (24h)</div>
      </div>
      <div class="mesh-metric">
        <div class="mesh-metric-value gold">${m.fees_collected_24h_simp || 0}</div>
        <div class="mesh-metric-label">Fees (SIMPT)</div>
      </div>
      <div class="mesh-metric">
        <div class="mesh-metric-value blue">${m.avg_trust_score || 0}</div>
        <div class="mesh-metric-label">Avg Trust Score</div>
      </div>
      <div class="mesh-metric">
        <div class="mesh-metric-value purple">${m.revenue_pool_simp || 0}</div>
        <div class="mesh-metric-label">Revenue Pool</div>
      </div>
    `;

    // Trust tiers
    if (DOM.meshTiers && m.trust_distribution) {
      DOM.meshTiers.innerHTML = Object.entries(m.trust_distribution).map(([tier, count]) =>
        `<span class="trust-tier ${tier}">${tier}: ${count}</span>`
      ).join('');
    }
  }

  function renderTrustGraph() {
    if (!DOM.graphCanvas || !state.trustgraph) return;
    if (state.trustgraph.length === 0) {
      DOM.graphCanvas.innerHTML = '<div style="text-align:center;padding:80px 20px;color:#8b95a5;">No trust graph edges available yet.<br><span style="font-size:13px;">Trust relationships form as agents route intents to each other.</span></div>';
      DOM.graphLegend.innerHTML = '<div style="color:#8b95a5;font-size:12px;">Waiting for agent activity...</div>';
      return;
    }

    // Build a simple SVG force-directed graph
    const nodes = new Map();
    const edges = state.trustgraph.slice(0, 50);
    
    edges.forEach(e => {
      if (!nodes.has(e.from_agent)) nodes.set(e.from_agent, { id: e.from_agent, x: 0, y: 0, connections: 0 });
      if (!nodes.has(e.to_agent)) nodes.set(e.to_agent, { id: e.to_agent, x: 0, y: 0, connections: 0 });
      nodes.get(e.from_agent).connections++;
      nodes.get(e.to_agent).connections++;
    });

    const nodeArr = Array.from(nodes.values());
    const W = DOM.graphCanvas.clientWidth || 600;
    const H = 400;
    const cx = W / 2, cy = H / 2;
    const radius = Math.min(W, H) * 0.35;

    // Simple circular layout
    nodeArr.forEach((n, i) => {
      const angle = (i / nodeArr.length) * 2 * Math.PI - Math.PI / 2;
      n.x = cx + radius * Math.cos(angle);
      n.y = cy + radius * Math.sin(angle);
    });

    // SVG
    const maxConn = Math.max(...nodeArr.map(n => n.connections), 1);
    const nodeSize = (n) => Math.max(6, 10 + (n.connections / maxConn) * 20);

    const edgeLines = edges.map(e => {
      const from = nodeArr.find(n => n.id === e.from_agent);
      const to = nodeArr.find(n => n.id === e.to_agent);
      if (!from || !to) return '';
      const alpha = Math.min(0.6, Math.max(0.1, e.trust_score / 5));
      const dir = e.direction === 'mutual' ? '#8b5cf6' : e.direction === 'outgoing' ? '#4f98a3' : '#22c55e';
      return `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${dir}" stroke-width="${Math.max(0.5, e.intents_routed / 5)}" stroke-opacity="${alpha}"/>`;
    }).join('');

    const nodeCircles = nodeArr.map(n => {
      const size = nodeSize(n);
      const id = n.id.length > 14 ? n.id.slice(0, 6) + '...' + n.id.slice(-4) : n.id;
      return `<g><circle cx="${n.x}" cy="${n.y}" r="${size}" fill="${n.connections > maxConn * 0.5 ? '#4f98a3' : '#8b95a5'}" stroke="#1c2330" stroke-width="2"/><text x="${n.x}" y="${n.y + size + 12}" text-anchor="middle" fill="#8b95a5" font-size="10" font-family="JetBrains Mono, monospace">${id}</text></g>`;
    }).join('');

    DOM.graphCanvas.innerHTML = `<svg width="${W}" height="${H}" style="background:transparent;">${edgeLines}${nodeCircles}</svg>`;

    // Legend
    DOM.graphLegend.innerHTML = `
      <div class="graph-legend-item">
        <div class="graph-legend-dot" style="background:#4f98a3;"></div>
        Outgoing Trust
      </div>
      <div class="graph-legend-item">
        <div class="graph-legend-dot" style="background:#22c55e;"></div>
        Incoming Trust
      </div>
      <div class="graph-legend-item">
        <div class="graph-legend-dot" style="background:#8b5cf6;"></div>
        Mutual Trust
      </div>
      <div class="graph-legend-item" style="color:#8b95a5;">
        ${nodeArr.length} nodes · ${edges.length} edges
      </div>
    `;
  }

  function renderMemos() {
    if (!DOM.memoList) return;
    const memos = state.memos || [];
    
    if (DOM.memoCount) {
      DOM.memoCount.textContent = memos.length;
    }

    if (memos.length === 0) {
      DOM.memoList.innerHTML = `
        <div style="text-align:center;padding:40px;color:#8b95a5;">
          <div style="font-size:32px;margin-bottom:8px;">📝</div>
          <div style="font-weight:600;">No State-Carrying Transfers Yet</div>
          <div style="font-size:13px;margin-top:4px;">When agents start embedding mesh state in token memos, they'll appear here.</div>
        </div>
      `;
      return;
    }

    DOM.memoList.innerHTML = memos.slice(0, 20).map(m => {
      const memoType = m.memo_decoded?.type || 'unknown';
      const typeLabel = memoType.replace('_', ' ');
      return `
        <div class="memo-row">
          <div class="memo-info">
            <div class="memo-pair">${m.from_agent} → ${m.to_agent || 'system'}</div>
            <div class="memo-amount">${m.amount_simp} SIMPT</div>
            ${m.state_payload ? `<div class="memo-payload">${JSON.stringify(m.state_payload, null, 2).slice(0, 300)}</div>` : ''}
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
            <span class="memo-type ${memoType}">${typeLabel}</span>
            <span style="font-size:11px;color:#5a6477;">${new Date(m.timestamp).toLocaleString()}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  function renderConvergence() {
    if (!DOM.convergenceBody || !state.convergence) return;

    const c = state.convergence;
    const on = c.onchain || {};
    const mesh = c.mesh || {};
    const conv = c.convergence || {};

    DOM.convergenceBody.innerHTML = `
      <div class="convergence-row">
        <span class="convergence-label">Supply vs Agents</span>
        <span class="convergence-onchain">${on.supply?.toLocaleString() || '—'}</span>
        <span class="convergence-vs">vs</span>
        <span class="convergence-mesh">${mesh.total_agents || 0} agents</span>
      </div>
      <div class="convergence-row">
        <span class="convergence-label">Holders vs Active Agents</span>
        <span class="convergence-onchain">${on.holders || 0} holders</span>
        <span class="convergence-vs">vs</span>
        <span class="convergence-mesh">${mesh.active_agents_5m || 0} active</span>
      </div>
      <div class="convergence-row" style="flex-direction:column;align-items:stretch;">
        <div style="display:flex;justify-content:space-between;width:100%;">
          <span class="convergence-label">Economic Velocity</span>
          <span class="convergence-onchain">${conv.economic_velocity || 0}</span>
        </div>
        <div class="convergence-bar">
          <div class="convergence-bar-fill" style="width:${Math.min(100, (conv.economic_velocity || 0) * 10)}%"></div>
        </div>
      </div>
      <div class="convergence-row" style="flex-direction:column;align-items:stretch;">
        <div style="display:flex;justify-content:space-between;width:100%;">
          <span class="convergence-label">Trust Maturity</span>
          <span class="convergence-mesh">${conv.trust_maturity || 0}</span>
        </div>
        <div class="convergence-bar">
          <div class="convergence-bar-fill" style="width:${Math.min(100, ((conv.trust_maturity || 0) / 5) * 100)}%"></div>
        </div>
      </div>
      <div class="convergence-row">
        <span class="convergence-label">Whale Concentration</span>
        <span class="convergence-onchain">${on.whale_holding_pct || 0}%</span>
        <span class="convergence-vs"></span>
        <span class="convergence-mesh">${mesh.total_agents > 0 ? 'Needs distribution' : 'No agents to distribute to'}</span>
      </div>
    `;
  }

  function renderOffline() {
    if (!DOM.offlineStatus || !state.offline) return;

    const o = state.offline;
    const ready = o.offline_ready;

    DOM.offlineStatus.innerHTML = `
      <div class="offline-status-card">
        <div class="offline-status-icon">${ready ? '📡' : '🌐'}</div>
        <div class="offline-status-text" style="color:${ready ? '#22c55e' : '#ffb74d'}">
          ${ready ? 'Offline-Ready' : 'Internet-Dependent'}
        </div>
        <div class="offline-status-sub">
          Dependency: ${o.internet_dependency || 'unknown'}
        </div>
      </div>
      <div class="offline-check-grid">
        <div class="offline-check-item">
          <span class="offline-check-icon">${o.has_offline_queue ? '✅' : '❌'}</span>
          <span class="offline-check-label">Offline Queue</span>
        </div>
        <div class="offline-check-item">
          <span class="offline-check-icon">${o.has_state_snapshots ? '✅' : '❌'}</span>
          <span class="offline-check-label">State Snapshots</span>
        </div>
        <div class="offline-check-item">
          <span class="offline-check-icon">${o.crdt_objects > 0 ? '✅' : '❌'}</span>
          <span class="offline-check-label">CRDT Objects (${o.crdt_objects})</span>
        </div>
        <div class="offline-check-item">
          <span class="offline-check-icon">${o.mesh_edges > 0 ? '✅' : '❌'}</span>
          <span class="offline-check-label">Mesh Edges (${o.mesh_edges})</span>
        </div>
        <div class="offline-check-item">
          <span class="offline-check-icon">${o.internet_dependency === 'reconciliation_only' ? '✅' : '⚠️'}</span>
          <span class="offline-check-label">Reconciliation Available</span>
        </div>
      </div>
    `;
  }

  // ── BRP Threat Intelligence ────────────────────────────────────────────

  function renderThreat() {
    const tensionEl = document.getElementById('threat-tension');
    const screeningsEl = document.getElementById('threat-screenings');
    const deniedEl = document.getElementById('threat-denied');
    const blocklistEl = document.getElementById('threat-blocklist');
    const forecastEl = document.getElementById('threat-forecast');
    const alertsEl = document.getElementById('threat-alerts');

    if (!tensionEl) return;

    if (!state.threat || !state.threat.threat_summary) {
      tensionEl.textContent = 'Offline';
      tensionEl.style.color = 'rgba(255,255,255,0.3)';
      if (screeningsEl) screeningsEl.textContent = '--';
      if (deniedEl) deniedEl.textContent = '--';
      if (blocklistEl) blocklistEl.textContent = '0';
      if (forecastEl) forecastEl.textContent = '--';
      if (alertsEl) alertsEl.innerHTML = '<div style="color:rgba(255,255,255,0.3);font-size:13px;text-align:center;padding:24px;">BRP gateway offline. No threat data available.</div>';
      return;
    }

    const ts = state.threat.threat_summary || {};
    const fore = state.threat.forecast || {};
    const threats = state.threat.recent_threats || [];

    // Tension
    const tension = ts.current_tension || 'low';
    const tensionColors = {
      low: '#10B981', medium: '#FCD34D', high: '#FCA5A5', critical: '#EF4444'
    };
    tensionEl.textContent = tension.toUpperCase();
    tensionEl.style.color = tensionColors[tension] || '#10B981';

    if (screeningsEl) screeningsEl.textContent = ts.total_screenings || 0;
    if (deniedEl) deniedEl.textContent = ts.packets_denied || 0;
    if (blocklistEl) blocklistEl.textContent = ts.active_blocklist || 0;
    if (forecastEl) {
      const pct = Math.round((fore.next_hour_threat_probability || 0) * 100);
      forecastEl.textContent = `${fore.predicted_severity || 'unknown'} (${pct}%)`;
    }

    // Alerts list
    if (alertsEl) {
      if (threats.length === 0) {
        alertsEl.innerHTML = '<div style="color:rgba(255,255,255,0.3);font-size:13px;text-align:center;padding:24px;">✅ No recent threats. All clear.</div>';
      } else {
        alertsEl.innerHTML = threats.slice(0, 10).map(t => {
          const level = t.threat_level || 'unknown';
          const color = level === 'critical' ? '#EF4444' : level === 'high' ? '#F59E0B' : '#FCD34D';
          return `<div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:rgba(255,255,255,0.02);border-radius:8px;margin-bottom:6px;">
            <div>
              <span style="color:#fff;font-size:13px;">${t.agent_id || 'unknown'}</span>
              <span style="color:rgba(255,255,255,0.25);font-size:11px;margin-left:8px;">${new Date((t.timestamp || Date.now()) * 1000).toLocaleTimeString()}</span>
            </div>
            <span style="padding:2px 8px;background:${color}22;border:1px solid ${color}44;border-radius:4px;color:${color};font-size:11px;font-weight:600;">${level}</span>
          </div>`;
        }).join('');
      }
    }
  }

  // ── Wallet Analysis ─────────────────────────────────────────────────────

  async function analyzeWallet(address) {
    if (!address || address.length < 32) return;
    DOM.walletBtn.disabled = true;
    DOM.walletBtn.textContent = 'Analyzing...';
    DOM.walletResult.innerHTML = '<div class="simpwallet-loading"><div class="spinner"></div>Querying Solana mainnet...</div>';

    try {
      const data = await apiGet('/wallet/' + address);
      state.walletResult = data;
      renderWalletResult(data);
    } catch (e) {
      DOM.walletResult.innerHTML = `<div class="simpwallet-error">Failed to analyze wallet: ${e.message}</div>`;
    } finally {
      DOM.walletBtn.disabled = false;
      DOM.walletBtn.textContent = 'Analyze';
    }
  }

  function renderWalletResult(data) {
    if (!DOM.walletResult) return;

    const known = data.is_known_wallet;
    const roles = data.known_roles || [];

    DOM.walletResult.innerHTML = `
      <div style="margin-bottom:16px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#8b95a5;word-break:break-all;margin-bottom:8px;">${data.address}</div>
        ${known ? `<div class="wallet-roles">${roles.map(r => `<span class="wallet-role-tag">${r}</span>`).join('')}</div>` : ''}
      </div>
      <div class="wallet-balance-row">
        <span class="wallet-balance-label">SOL Balance</span>
        <span class="wallet-balance-value">${data.sol_balance} SOL</span>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:13px;color:#8b95a5;margin-bottom:8px;font-weight:600;">Token Accounts (${data.token_accounts.length})</div>
        ${data.token_accounts.length === 0 
          ? '<div style="color:#5a6477;font-size:12px;padding:8px 0;">No SPL token accounts found.</div>'
          : data.token_accounts.map(ta => `
            <div class="wallet-balance-row">
              <span class="wallet-balance-label" style="font-family:'JetBrains Mono',monospace;font-size:11px;">${ta.mint?.slice(0, 8) || 'Unknown'}... ${ta.decimals} decimals</span>
              <span class="wallet-balance-value" style="font-size:13px;">${ta.balance_ui?.toLocaleString() || 0}</span>
            </div>
          `).join('')
        }
      </div>
    `;
  }

  // ── Tab Switching ───────────────────────────────────────────────────────

  function switchTab(tabId) {
    state.activeTab = tabId;
    DOM.tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    DOM.contents.forEach(c => c.classList.toggle('active', c.id === 'simpwallet-content-' + tabId));
  }

  // ── Auto-Refresh ────────────────────────────────────────────────────────

  function updateLastRefresh(elapsed) {
    if (DOM.lastRefresh) {
      const label = state.lastRefresh 
        ? new Date(state.lastRefresh).toLocaleTimeString() 
        : 'just now';
      DOM.lastRefresh.textContent = `${label} (${elapsed}ms)`;
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    state.refreshIntervalId = setInterval(refresh, REFRESH_INTERVAL);
  }

  function stopAutoRefresh() {
    if (state.refreshIntervalId) {
      clearInterval(state.refreshIntervalId);
      state.refreshIntervalId = null;
    }
  }

  // ── Visibility ──────────────────────────────────────────────────────────

  function show() {
    DOM.section?.classList.add('active');
    startAutoRefresh();
    refresh();
  }

  function hide() {
    DOM.section?.classList.remove('active');
    stopAutoRefresh();
  }

  function isVisible() {
    return DOM.section?.classList.contains('active') || false;
  }

  // ── Init ────────────────────────────────────────────────────────────────

  function init() {
    cacheDOM();
    if (!DOM.section) {
      console.warn('SIMPWallet: section not found in DOM');
      return;
    }

    // Tab clicks
    DOM.tabs?.forEach(tab => {
      tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Wallet analysis
    DOM.walletBtn?.addEventListener('click', () => {
      analyzeWallet(DOM.walletInput?.value.trim());
    });
    DOM.walletInput?.addEventListener('keydown', e => {
      if (e.key === 'Enter') analyzeWallet(e.target.value.trim());
    });

    // Nav link
    if (DOM.navLink) {
      DOM.navLink.addEventListener('click', e => {
        e.preventDefault();
        show();
        // Also switch to SIMPWallet section from other dashboard tabs
        const allSections = document.querySelectorAll('.simpwallet-section');
        allSections.forEach(s => s.classList.remove('active'));
        show();
      });
    }

    // Auto-refresh based on visibility
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stopAutoRefresh();
      else if (isVisible()) startAutoRefresh();
    });

    console.log('🚀 SIMPWallet initialized');
    console.log(`   API Base: ${API_BASE}`);
    console.log(`   Auto-refresh: ${REFRESH_INTERVAL / 1000}s`);
  }

  // Kick off when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose public API
  window.SIMPWallet = {
    refresh,
    show,
    hide,
    isVisible,
    analyzeWallet,
    switchTab,
    getState: () => ({ ...state }),
  };

})();
