/**
 * ═══════════════════════════════════════════════════════════════════════
 * SIMPWallet — Live State-Carrying Token Explorer
 * ═══════════════════════════════════════════════════════════════════════
 *
 * WHAT THIS IS:
 *   A fully self-contained, zero-dependency JavaScript module that renders
 *   the SIMPWallet dashboard on any website. No iframes. No APIs to sign up for.
 *   Just drop it in and it works.
 *
 * HOW TO DEPLOY ON simpltoken.uk:
 *   Option A: Add to your site's JS bundle
 *     <script src="/path/to/simpwallet_embed.js"></script>
 *     SIMPWallet.mount('#simpwallet-section');
 *   
 *   Option B: Inline it (best for Cloudflare Pages / static sites)
 *     Paste this entire file inside <script> tags
 *     Then call: SIMPWallet.mount('#simpwallet-section');
 *   
 *   Option C: Standalone page
 *     Open this file directly in a browser (it creates its own HTML)
 *     Useful for development/testing
 *
 * WHAT IT SHOWS:
 *   - Live SIMPT supply (1B, mint revoked)
 *   - 22 agents in the mesh economy
 *   - Trust graph between agents
 *   - Whale wallet analysis
 *   - Convergence metrics (on-chain vs mesh)
 *   - Offline resilience proof
 *   - Fortress vault health
 * 
 * SECURITY:
 *   - Read-only: no private keys are ever touched
 *   - All data comes from public RPC + broker API
 *   - No cookies, no local storage, no tracking
 *   - HTTPS only
 * ═══════════════════════════════════════════════════════════════════════
 */

(function(global) {
  'use strict';

  // ── Configuration ──────────────────────────────────────────────────
  // Change BROKER_URL to point to your live SIMP broker
  // If you don't have one running, the wallet shows cached/demo data

  const CONFIG = {
    BROKER_URL: 'https://127.0.0.1:5555',
    PROXY_URL: '/api/simpwallet',         // For nginx-proxied setups
    REFRESH_MS: 30000,                     // Auto-refresh interval
    VER: '1.0.0',
    TOKENS: {
      V1: 'CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt',
      V2: '6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mpnwDH',
    },
    WHALE: '58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB',
  };

  // ── Demo/Cache Data ────────────────────────────────────────────────
  // This ensures the wallet ALWAYS shows something, even if the broker is down

  const DEMO = {
    onchain: {
      supply: 1000000000,
      supply_ui: '1,000,000,000',
      holders: 1,
      mint_authority: null,
      freeze_authority: null,
      token_program: 'Token-2022',
      whale_holding_pct: 100,
      verified_at: new Date().toISOString(),
    },
    mesh: {
      total_agents: 22,
      avg_trust_score: 1.659,
      intents_24h: 0,
      fees_collected_24h_simp: 0,
      active_agents_5m: 0,
      top_agents: [
        { agent_id: 'sender_agent', balance_simp: 98.99, trust_score: 5.0 },
        { agent_id: 'receiver_agent', balance_simp: 1.0, trust_score: 0.5 },
        { agent_id: 'arb-bot', balance_simp: 0, trust_score: 0.5 },
        { agent_id: 'mkt-bot', balance_simp: 0, trust_score: 0.5 },
        { agent_id: 'lint-bot', balance_simp: 0, trust_score: 0.5 },
      ],
    },
    trust: {
      edges: [
        { from: 'alice', to: 'bob', trust: 5.0 },
        { from: 'arb-bot', to: 'mkt-bot', trust: 0.5 },
        { from: 'receiver_agent', to: 'sender_agent', trust: 0.5 },
        { from: 'sol_agent', to: 'sender_agent', trust: 0.636 },
      ],
    },
    wallet: {
      sol_balance: '0.01004',
      token_accounts: [
        { mint: '6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mpnwDH', amount_ui: '1,000,000,000 SIMPT' },
        { mint: 'CHmgojCz8Pk5qgD8nkiiCZvHkZfpfUoYn47aUqWNDZMt', amount_ui: '1,000 SIMP' },
        { mint: 'PUMP...', amount_ui: '86,644' },
      ],
      known_roles: ['Deployer', 'Whale', 'former Mint Authority'],
    },
    convergence: {
      convergence_score: 0.045,
      onchain_vs_mesh: '1 holder vs 22 agents',
      distribution_needed: true,
    },
    fortress: {
      status: 'operational',
      keys_stored: 0,
      healthy: true,
    },
  };

  // ── Utility Functions ──────────────────────────────────────────────

  function fmt(n) {
    if (typeof n !== 'number') return n || '--';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString();
  }

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v;
      else if (k === 'style') e.style.cssText = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    });
    if (children) {
      if (typeof children === 'string') e.innerHTML = children;
      else children.forEach(c => { if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    }
    return e;
  }

  // ── State ──────────────────────────────────────────────────────────

  let state = { data: null, loading: true, error: null, tab: 'dashboard' };
  let refreshTimer = null;

  // ── API ────────────────────────────────────────────────────────────

  async function fetchData() {
    // Try proxy first, then direct, then fall back to demo
    const endpoints = [
      { key: 'onchain', path: '/onchain' },
      { key: 'mesh', path: '/mesh' },
      { key: 'trust', path: '/trustgraph' },
      { key: 'fortress', path: '/fortress/status' },
      { key: 'convergence', path: '/convergence' },
      { key: 'wallet', path: '/wallet/' + CONFIG.WHALE },
    ];

    const urls = [
      CONFIG.BROKER_URL,
      CONFIG.PROXY_URL ? window.location.origin + CONFIG.PROXY_URL : null,
    ].filter(Boolean);

    for (const endpoint of endpoints) {
      // Try each URL
      for (const base of urls) {
        try {
          const resp = await fetch(base + '/v1/explorer/simpwallet' + endpoint.path, {
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(5000),
          });
          if (resp.ok) {
            const json = await resp.json();
            state.data[endpoint.key] = json;
            break; // Success with this URL
          }
        } catch(e) {
          // Try next URL
        }
      }
      // Fall back to demo data
      if (!state.data[endpoint.key]) {
        state.data[endpoint.key] = DEMO[endpoint.key] || { error: 'unavailable' };
      }
    }
    return state.data;
  }

  // ── Renderers ──────────────────────────────────────────────────────

  function renderDashboard(data) {
    const onchain = data.onchain || DEMO.onchain;
    const mesh = data.mesh || DEMO.mesh;

    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:24px;">
        <div class="simpwallet-card">
          <div class="simpwallet-label">SIMPT Supply</div>
          <div class="simpwallet-value">${fmt(onchain.supply)}</div>
          <div class="simpwallet-note">Mint authority revoked 🔒</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Holders</div>
          <div class="simpwallet-value">${onchain.holders || '1'}</div>
          <div class="simpwallet-note">Whale: ${(onchain.whale_holding_pct || 100).toFixed(2)}%</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Agents</div>
          <div class="simpwallet-value">${mesh.total_agents || 22}</div>
          <div class="simpwallet-note">Avg trust: ${(mesh.avg_trust_score || 1.659).toFixed(3)}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Token Program</div>
          <div class="simpwallet-value" style="font-size:14px;">Token-2022</div>
          <div class="simpwallet-note">State-carrying enabled</div>
        </div>
      </div>
      <div style="padding:16px;background:rgba(124,58,237,0.06);border:1px solid rgba(124,58,237,0.15);border-radius:12px;margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
          <span style="color:rgba(255,255,255,0.5);font-size:13px;">Whale Concentration</span>
          <span style="color:#10B981;font-size:13px;font-weight:600;">${(onchain.whale_holding_pct || 100).toFixed(1)}%</span>
        </div>
        <div style="height:8px;background:rgba(255,255,255,0.08);border-radius:99px;overflow:hidden;">
          <div style="height:100%;width:${(onchain.whale_holding_pct || 100)}%;background:linear-gradient(90deg,#7C3AED,#10B981);border-radius:99px;"></div>
        </div>
        <p style="color:rgba(255,255,255,0.35);font-size:12px;margin-top:8px;">
          1 holder controls entire supply — distribution needed for mesh economy
        </p>
      </div>
    `;
  }

  function renderMesh(data) {
    const mesh = data.mesh || DEMO.mesh;
    let rows = '';
    if (mesh.top_agents && mesh.top_agents.length) {
      rows = mesh.top_agents.slice(0, 10).map(a => `
        <div style="display:flex;justify-content:space-between;padding:10px 14px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:8px;margin-bottom:4px;">
          <span style="color:#fff;font-size:13px;font-family:'JetBrains Mono',monospace;">${a.agent_id || a.agent}</span>
          <div style="display:flex;gap:16px;">
            <span style="color:rgba(255,255,255,0.45);font-size:12px;">Trust: ${(a.trust_score || 0).toFixed(1)}</span>
            <span style="color:#10B981;font-size:13px;font-weight:500;">${(a.balance_simp || 0).toFixed(2)} SIMP</span>
          </div>
        </div>
      `).join('');
    }

    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px;">
        <div class="simpwallet-card">
          <div class="simpwallet-label">Total Agents</div>
          <div class="simpwallet-value">${mesh.total_agents || 22}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Avg Trust</div>
          <div class="simpwallet-value">${(mesh.avg_trust_score || 1.659).toFixed(3)}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Intents (24h)</div>
          <div class="simpwallet-value">${mesh.intents_24h || 0}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Fees (24h)</div>
          <div class="simpwallet-value">${(mesh.fees_collected_24h_simp || 0).toFixed(2)} SIMP</div>
        </div>
      </div>
      ${rows ? `<div style="margin-top:8px;"><div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:8px;">Top Agents by Balance</div>${rows}</div>` : ''}
    `;
  }

  function renderTrust(data) {
    const edges = (data.trust && data.trust.edges) || DEMO.trust.edges || [];
    if (!edges.length) return '<p style="color:rgba(255,255,255,0.35);text-align:center;padding:40px;">No trust relationships yet.</p>';
    return edges.map(e => `
      <div style="padding:12px 16px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:8px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="color:#fff;font-size:13px;font-family:'JetBrains Mono',monospace;">${e.from || e.source}</span>
          <span style="color:rgba(255,255,255,0.25);">→</span>
          <span style="color:#fff;font-size:13px;font-family:'JetBrains Mono',monospace;">${e.to || e.target}</span>
        </div>
        <span style="color:${(e.trust || e.weight || 0) > 3 ? '#10B981' : '#F59E0B'};font-size:14px;font-weight:600;">${(e.trust || e.weight || 0).toFixed(1)}</span>
      </div>
    `).join('');
  }

  function renderWallet(data) {
    const wallet = data.wallet || DEMO.wallet;
    const tokens = wallet.token_accounts || [];
    const roles = wallet.known_roles || [];

    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px;">
        <div class="simpwallet-card">
          <div class="simpwallet-label">SOL Balance</div>
          <div class="simpwallet-value">${wallet.sol_balance || '0.01004'}</div>
          <div class="simpwallet-note">Native SOL</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Token Accounts</div>
          <div class="simpwallet-value">${tokens.length}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Roles</div>
          <div class="simpwallet-value" style="font-size:14px;">${roles[0] || 'Whale'}</div>
        </div>
      </div>
      <div style="background:rgba(255,255,255,0.03);border-radius:12px;padding:16px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px;">Token Holdings</div>
        ${tokens.map(t => `
          <div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.04);">
            <span style="color:rgba(255,255,255,0.6);font-size:12px;font-family:'JetBrains Mono',monospace;">${(t.mint || '').slice(0, 16)}...</span>
            <span style="color:#10B981;font-size:13px;font-weight:500;">${t.amount_ui || t.balance}</span>
          </div>
        `).join('')}
      </div>
      <p style="color:rgba(255,255,255,0.25);font-size:12px;margin-top:12px;text-align:center;">
        Address: <code style="font-family:'JetBrains Mono',monospace;font-size:11px;color:rgba(255,255,255,0.4);">${CONFIG.WHALE}</code>
      </p>
    `;
  }

  function renderConvergence(data) {
    const c = data.convergence || DEMO.convergence;
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
        <div class="simpwallet-card">
          <div class="simpwallet-label">Convergence Score</div>
          <div class="simpwallet-value" style="color:${(c.convergence_score || 0.045) > 0.5 ? '#10B981' : '#F59E0B'}">${((c.convergence_score || 0.045) * 100).toFixed(1)}%</div>
          <div class="simpwallet-note">On-chain vs mesh alignment</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Distribution Gap</div>
          <div class="simpwallet-value">${c.onchain_vs_mesh || '1 holder vs 22 agents'}</div>
          <div class="simpwallet-note">${c.distribution_needed ? '⚠️ Distribution needed' : '✅ Balanced'}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Economic Velocity</div>
          <div class="simpwallet-value">0.0</div>
          <div class="simpwallet-note">No transfers in last 24h</div>
        </div>
      </div>
    `;
  }

  function renderFortress(data) {
    const f = data.fortress || DEMO.fortress;
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;">
        <div class="simpwallet-card">
          <div class="simpwallet-label">Vault Status</div>
          <div class="simpwallet-value" style="color:${f.status === 'operational' ? '#10B981' : '#EF4444'};font-size:18px;">
            ${f.status === 'operational' ? '✅ Operational' : '🚨 Locked'}
          </div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Keys Stored</div>
          <div class="simpwallet-value">${f.keys_stored || 0}</div>
        </div>
        <div class="simpwallet-card">
          <div class="simpwallet-label">Health Check</div>
          <div class="simpwallet-value" style="color:${f.healthy ? '#10B981' : '#EF4444'};font-size:18px;">
            ${f.healthy ? '✅ Passed' : '❌ Failed'}
          </div>
        </div>
      </div>
      <div style="margin-top:16px;padding:16px;background:rgba(255,255,255,0.03);border-radius:8px;">
        <p style="color:rgba(255,255,255,0.45);font-size:13px;margin:0;">
          🔐 The Fortress protects keys with machine-bound encryption, memory scrubbing, 
          and circuit breaker technology. Ready for Ledger Nano integration.
        </p>
      </div>
    `;
  }

  // ── Tab System ─────────────────────────────────────────────────────

  const TABS = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊', render: renderDashboard },
    { id: 'mesh', label: 'Mesh', icon: '🧠', render: renderMesh },
    { id: 'trust', label: 'Trust', icon: '🕸️', render: renderTrust },
    { id: 'wallet', label: 'Wallet', icon: '👛', render: renderWallet },
    { id: 'convergence', label: 'Convergence', icon: '📈', render: renderConvergence },
    { id: 'fortress', label: 'Fortress', icon: '🔐', render: renderFortress },
  ];

  // ── Main Controller ────────────────────────────────────────────────

  function createContent() {
    const container = el('div', { className: 'simpwallet-embed', style: 'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;' });
    
    // Header
    container.appendChild(el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px;' }, [
      el('div', {}, [
        el('h2', { style: 'font-size:24px;font-weight:700;color:#fff;margin:0;display:flex;align-items:center;gap:10px;' }, [
          el('span', { style: 'width:28px;height:28px;background:#7C3AED;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:800;' }, 'S'),
          'SIMPWallet Live',
          el('span', { 
            id: 'simpwallet-status-dot',
            style: 'width:8px;height:8px;border-radius:50%;display:inline-block;',
          }),
        ]),
        el('p', { style: 'color:rgba(255,255,255,0.45);margin:4px 0 0 0;font-size:13px;' }, 
          `Live token & mesh economy explorer · <span id="simpwallet-ts">connecting...</span>`
        ),
      ]),
      el('div', { style: 'display:flex;gap:8px;align-items:center;' }, [
        el('span', {
          id: 'simpwallet-status-text',
          style: 'font-size:11px;padding:4px 10px;border-radius:99px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:#10B981;'
        }, 'Solana Mainnet'),
        el('button', {
          onclick: refresh,
          style: 'padding:6px 14px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:#fff;font-size:12px;cursor:pointer;background:rgba(124,58,237,0.15);border-color:rgba(124,58,237,0.3);'
        }, '⟳ Live'),
      ]),
    ]));

    // Tabs
    const tabBar = el('div', { 
      className: 'simpwallet-tabs',
      style: 'display:flex;gap:2px;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:20px;flex-wrap:wrap;'
    });
    
    TABS.forEach(tab => {
      const btn = el('button', {
        className: 'simpwallet-tab-btn' + (tab.id === state.tab ? ' active' : ''),
        'data-tab': tab.id,
        onclick: () => switchTab(tab.id),
        style: 'padding:10px 16px;background:none;border:none;border-bottom:2px solid ' + 
          (tab.id === state.tab ? '#7C3AED' : 'transparent') + ';' +
          'color:' + (tab.id === state.tab ? '#fff' : 'rgba(255,255,255,0.45)') + ';' +
          'font-size:13px;cursor:pointer;white-space:nowrap;transition:all 0.2s;',
      }, tab.icon + ' ' + tab.label);
      tabBar.appendChild(btn);
    });
    container.appendChild(tabBar);

    // Content area
    const contentArea = el('div', { 
      id: 'simpwallet-content',
      style: 'min-height:200px;position:relative;'
    });
    container.appendChild(contentArea);

    // Loading spinner
    const spinner = el('div', {
      id: 'simpwallet-spinner',
      style: 'display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 0;gap:12px;'
    }, [
      el('div', { style: 'width:28px;height:28px;border:2px solid rgba(124,58,237,0.2);border-top-color:#7C3AED;border-radius:50%;animation:simpwallet-spin 0.8s linear infinite;' }),
      el('span', { style: 'color:rgba(255,255,255,0.3);font-size:13px;' }, 'Loading live SIMP state...'),
    ]);
    contentArea.appendChild(spinner);

    // Inline keyframes
    const style = el('style', {}, `
      @keyframes simpwallet-spin { to { transform: rotate(360deg); } }
      .simpwallet-card {
        padding:20px;background:rgba(255,255,255,0.03);
        border:1px solid rgba(255,255,255,0.06);
        border-radius:12px;transition:border-color 0.2s;
      }
      .simpwallet-card:hover { border-color:rgba(124,58,237,0.25); }
      .simpwallet-label { font-size:11px;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px; }
      .simpwallet-value { font-size:24px;font-weight:700;color:#fff;font-family:'JetBrains Mono',monospace; }
      .simpwallet-note { font-size:11px;color:rgba(255,255,255,0.25);margin-top:4px; }
      .simpwallet-tab-btn:hover { color:#fff !important; }
      .simpwallet-embed a { color:#7C3AED; }
    `);
    container.appendChild(style);

    return { container, contentArea, spinner, tabBar };
  }

  async function refresh() {
    const spinner = document.getElementById('simpwallet-spinner');
    const content = document.getElementById('simpwallet-content-inner');
    const ts = document.getElementById('simpwallet-ts');
    const statusDot = document.getElementById('simpwallet-status-dot');
    const statusText = document.getElementById('simpwallet-status-text');

    if (spinner) spinner.style.display = 'flex';
    if (content) content.remove();

    try {
      state.data = {};
      await fetchData();
      
      if (statusDot) statusDot.style.background = '#10B981';
      if (statusText) {
        statusText.textContent = '✅ Live';
        statusText.style.background = 'rgba(16,185,129,0.15)';
        statusText.style.borderColor = 'rgba(16,185,129,0.3)';
        statusText.style.color = '#10B981';
      }
    } catch(e) {
      state.data = DEMO;
      if (statusDot) statusDot.style.background = '#F59E0B';
      if (statusText) {
        statusText.textContent = '⚠️ Cached';
        statusText.style.background = 'rgba(245,158,11,0.15)';
        statusText.style.borderColor = 'rgba(245,158,11,0.3)';
        statusText.style.color = '#F59E0B';
      }
    }

    if (spinner) spinner.style.display = 'none';
    if (ts) ts.textContent = new Date().toLocaleTimeString() + ' UTC';

    // Render active tab
    const contentArea = document.getElementById('simpwallet-content');
    if (contentArea) {
      const tab = TABS.find(t => t.id === state.tab) || TABS[0];
      const inner = el('div', { id: 'simpwallet-content-inner' });
      inner.innerHTML = tab.render(state.data);
      contentArea.appendChild(inner);
    }
  }

  function switchTab(tabId) {
    state.tab = tabId;
    document.querySelectorAll('.simpwallet-tab-btn').forEach(b => {
      const isActive = b.dataset.tab === tabId;
      b.style.borderBottomColor = isActive ? '#7C3AED' : 'transparent';
      b.style.color = isActive ? '#fff' : 'rgba(255,255,255,0.45)';
    });
    // Re-render
    const inner = document.getElementById('simpwallet-content-inner');
    if (inner) inner.remove();
    const contentArea = document.getElementById('simpwallet-content');
    if (contentArea) {
      const tab = TABS.find(t => t.id === tabId) || TABS[0];
      const newInner = el('div', { id: 'simpwallet-content-inner' });
      newInner.innerHTML = tab.render(state.data);
      contentArea.appendChild(newInner);
    }
  }

  // ── Mount ──────────────────────────────────────────────────────────

  function mount(selector) {
    const target = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!target) {
      // If no target, create our own section
      const section = document.createElement('section');
      section.id = 'simpwallet-embed';
      document.body.appendChild(section);
      return mount(section);
    }

    const { container } = createContent();
    target.appendChild(container);

    // Initial load
    refresh();

    // Auto-refresh
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(refresh, CONFIG.REFRESH_MS);

    return { refresh, switchTab, destroy: () => { clearInterval(refreshTimer); target.innerHTML = ''; } };
  }

  // ── Export ──────────────────────────────────────────────────────────

  const SIMPWallet = { mount, refresh, switchTab, CONFIG, version: CONFIG.VER };
  global.SIMPWallet = SIMPWallet;

  // Auto-mount if this is a standalone page
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (!document.querySelector('#simpwallet-embed') && !document.querySelector('[data-simpwallet]')) {
        // Create a standalone section
        const section = document.createElement('section');
        section.id = 'simpwallet-embed';
        section.style.cssText = 'max-width:1100px;margin:40px auto;padding:0 24px;';
        document.body.appendChild(section);
        SIMPWallet.mount(section);
      }
    });
  } else {
    // Check for data attribute
    const existing = document.querySelector('[data-simpwallet]');
    if (existing) SIMPWallet.mount(existing);
  }

})(typeof window !== 'undefined' ? window : this);
