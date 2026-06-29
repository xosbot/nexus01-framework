/* IVA OS — admin drawer views (overview, memory, projects, rag, agents, approvals, events, soul, settings) */

(function () {
  const $  = (s, p = document) => p.querySelector(s);
  const $$ = (s, p = document) => [...p.querySelectorAll(s)];
  const esc = (s) => (s == null ? '' : String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;'));

  function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleString();
  }
  function fmtRel(ts) {
    if (!ts) return '—';
    const diff = (Date.now() - new Date(ts).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, {
      ...opts,
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '', 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    if (!res.ok) throw new Error('API ' + res.status);
    return res.json();
  }

  function setState(updates) {
    if (window.appState) Object.assign(window.appState, updates);
  }

  /* ── Overview ────────────────────────────────────────────── */

  async function overview() {
    const [ov, providers, events] = await Promise.all([
      api('/api/overview').catch(() => ({})),
      api('/api/config/providers').catch(() => ({ providers: {} })),
      api('/api/events/stats').catch(() => ({})),
    ]);
    const online = (ov.providers || []).filter(p => p.available).length;
    const total = (ov.providers || []).length;
    return `
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">Sessions</div><div class="stat-value accent">${esc(ov.total_sessions ?? '—')}</div></div>
        <div class="stat-card"><div class="stat-label">Messages</div><div class="stat-value">${esc(ov.total_messages ?? '—')}</div></div>
        <div class="stat-card"><div class="stat-label">Knowledge</div><div class="stat-value">${esc(ov.knowledge_count ?? '—')}</div></div>
        <div class="stat-card"><div class="stat-label">RAG docs</div><div class="stat-value">${esc(ov.rag_docs ?? '—')}</div></div>
        <div class="stat-card"><div class="stat-label">Providers</div><div class="stat-value green">${online} / ${total}</div></div>
        <div class="stat-card"><div class="stat-label">Uptime</div><div class="stat-value">${esc(ov.uptime ?? '—')}</div></div>
      </div>

      <div class="section-title">Providers</div>
      <div class="kv-list">
        ${(ov.providers || []).map(p => `
          <div class="kv-row">
            <span class="kv-key">${esc(p.name)}</span>
            <span class="kv-val ${p.available ? 'green' : 'red'}">${p.available ? 'online' : 'offline'}</span>
          </div>
        `).join('') || '<div class="empty-hint">No providers configured</div>'}
      </div>

      <div class="section-title">Event log</div>
      <div class="kv-list">
        <div class="kv-row"><span class="kv-key">Total</span><span class="kv-val">${esc(events.total ?? 0)}</span></div>
        <div class="kv-row"><span class="kv-key">Last hour</span><span class="kv-val">${esc(events.last_hour ?? 0)}</span></div>
        <div class="kv-row"><span class="kv-key">Last 24h</span><span class="kv-val">${esc(events.last_24h ?? 0)}</span></div>
      </div>
    `;
  }

  /* ── Memory ──────────────────────────────────────────────── */

  async function memory() {
    const [stats, knowledge] = await Promise.all([
      api('/api/brain/stats').catch(() => ({})),
      api('/api/memory/knowledge?limit=30').catch(() => []),
    ]);
    return `
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">Episodic</div><div class="stat-value accent">${esc(stats.episodic_count ?? 0)}</div></div>
        <div class="stat-card"><div class="stat-label">Semantic</div><div class="stat-value">${esc(stats.semantic_count ?? 0)}</div></div>
        <div class="stat-card"><div class="stat-label">Procedural</div><div class="stat-value accent">${esc(stats.procedural_count ?? 0)}</div></div>
        <div class="stat-card"><div class="stat-label">Working</div><div class="stat-value amber">${esc(stats.working_count ?? 0)}</div></div>
      </div>

      <div class="section-title">Knowledge store</div>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input class="input" id="mem-search" placeholder="Search memory...">
        <button class="btn btn-primary btn-sm" id="mem-search-btn">Search</button>
      </div>
      <div id="mem-results">
        ${(knowledge || []).slice(0, 30).map(k => `
          <div class="kv-row" style="display:block;">
            <div class="kv-key" style="color:var(--accent);">${esc((k.key || '').slice(0, 60))}</div>
            <div style="color:var(--fg-dim);font-size:12px;margin-top:2px;">${esc((k.value || '').slice(0, 120))}</div>
          </div>
        `).join('') || '<div class="empty-hint">No knowledge stored yet</div>'}
      </div>
    `;
  }

  /* ── Projects ────────────────────────────────────────────── */

  async function projects() {
    const data = await api('/api/projects').catch(() => ({ projects: [] }));
    const list = data.projects || [];
    return `
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input class="input" id="proj-name" placeholder="Project name" style="flex:1;">
        <input class="input" id="proj-desc" placeholder="Description" style="flex:1;">
        <button class="btn btn-primary btn-sm" id="proj-create">Create</button>
      </div>

      <div class="section-title">Projects</div>
      ${list.length ? list.map(p => {
        const progress = p.progress || { total: 0, done: 0, percent: 0 };
        return `
          <div class="kv-row" style="display:block;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong>${esc(p.name)}</strong>
              <span class="kv-val ${p.status === 'active' ? 'green' : ''}">${esc(p.status || '—')}</span>
            </div>
            <div style="color:var(--fg-dim);font-size:12px;margin-top:2px;">${esc(p.description || '')}</div>
            <div style="margin-top:6px;height:6px;background:var(--bg-3);border-radius:3px;overflow:hidden;">
              <div style="width:${progress.percent}%;height:100%;background:var(--accent);"></div>
            </div>
            <div style="color:var(--fg-muted);font-size:11px;margin-top:2px;font-family:var(--mono);">${progress.done} / ${progress.total} (${progress.percent}%)</div>
          </div>
        `;
      }).join('') : '<div class="empty-hint">No projects yet — create one above.</div>'}
    `;
  }

  /* ── RAG / Knowledge ─────────────────────────────────────── */

  async function rag() {
    const stats = await api('/api/rag/stats').catch(() => ({}));
    return `
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">Collection</div><div class="stat-value accent" style="font-size:14px;">${esc(stats.collection || '—')}</div></div>
        <div class="stat-card"><div class="stat-label">Documents</div><div class="stat-value green">${esc(stats.documents ?? 0)}</div></div>
        <div class="stat-card"><div class="stat-label">Chunks</div><div class="stat-value">${esc(stats.chunks ?? 0)}</div></div>
        <div class="stat-card"><div class="stat-label">ChromaDB</div><div class="stat-value ${stats.chroma_enabled ? 'green' : 'amber'}">${stats.chroma_enabled ? 'on' : 'off'}</div></div>
      </div>

      <div class="section-title">Search</div>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input class="input" id="rag-search-input" placeholder="Search documents...">
        <button class="btn btn-primary btn-sm" id="rag-search-btn">Search</button>
      </div>
      <div id="rag-results"></div>

      <div class="section-title">Ingest</div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <input class="input" id="rag-ingest-url" placeholder="URL to ingest">
        <button class="btn btn-sm" id="rag-ingest-url-btn">Ingest URL</button>
        <textarea class="input" id="rag-ingest-text" placeholder="Or paste text..." style="min-height:80px;"></textarea>
        <button class="btn btn-sm" id="rag-ingest-text-btn">Ingest Text</button>
      </div>
    `;
  }

  /* ── Agents ──────────────────────────────────────────────── */

  async function agents() {
    const status = await api('/api/system/status').catch(() => ({}));
    const agentInfo = {
      orchestrator: { icon: '🎯', role: 'Routes tasks to specialized agents' },
      osint:        { icon: '🔍', role: 'Open-source intelligence gathering' },
      analyst:      { icon: '📊', role: 'Data analysis and reporting' },
      executor:     { icon: '⚡', role: 'Command execution in sandbox' },
    };
    const list = status.agents || Object.keys(agentInfo);
    return `
      <div class="section-title">Agent status</div>
      <div class="kv-list">
        ${list.map(name => {
          const info = agentInfo[name] || { icon: '•', role: 'Agent' };
          return `
            <div class="kv-row">
              <span class="kv-key">${info.icon} ${esc(name)}</span>
              <span class="kv-val green">online</span>
            </div>
            <div class="kv-row" style="background:transparent;border:none;padding:4px 10px;">
              <span class="kv-key" style="font-size:11px;">${esc(info.role)}</span>
            </div>
          `;
        }).join('')}
      </div>

      <div class="section-title">System</div>
      <div class="kv-list">
        <div class="kv-row"><span class="kv-key">Bus</span><span class="kv-val">${esc(status.bus_backend || '—')}</span></div>
        <div class="kv-row"><span class="kv-key">Cold mode</span><span class="kv-val ${status.cold_mode ? 'green' : 'amber'}">${status.cold_mode ? 'on' : 'off'}</span></div>
        <div class="kv-row"><span class="kv-key">ReAct loop</span><span class="kv-val ${status.react_loop ? 'green' : 'amber'}">${status.react_loop ? 'on' : 'off'}</span></div>
      </div>

      <div class="section-title">Channels</div>
      <div class="kv-list">
        ${(status.channels || []).map(c => `
          <div class="kv-row"><span class="kv-key">${esc(c.name)}</span><span class="kv-val green">active</span></div>
        `).join('') || '<div class="empty-hint">No channels</div>'}
      </div>
    `;
  }

  /* ── Approvals ───────────────────────────────────────────── */

  async function approvals() {
    const data = await api('/api/approvals?include_expired=true').catch(() => ({ approvals: [] }));
    const list = data.approvals || [];
    return `
      <div class="section-title">Pending approvals</div>
      ${list.length ? list.map(a => `
        <div class="kv-row" style="display:block;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="kv-key">${esc(a.channel)}</span>
            <span style="color:var(--fg-muted);font-size:11px;font-family:var(--mono);">${fmtRel(a.created_at)}</span>
          </div>
          <div style="color:var(--fg-dim);font-size:12px;margin-top:4px;">${esc((a.text || '').slice(0, 160))}${(a.text || '').length > 160 ? '…' : ''}</div>
          ${a.expired ? '<div style="color:var(--amber);font-size:11px;margin-top:4px;">expired</div>' : `
            <div style="display:flex;gap:6px;margin-top:8px;">
              <button class="btn btn-sm btn-primary" onclick="AdminActions.respondApproval('${esc(a.id)}', true)">Approve</button>
              <button class="btn btn-sm" onclick="AdminActions.respondApproval('${esc(a.id)}', false)">Reject</button>
            </div>
          `}
        </div>
      `).join('') : '<div class="empty-hint">No pending approvals</div>'}
    `;
  }

  /* ── Events ──────────────────────────────────────────────── */

  async function events() {
    const data = await api('/api/events?limit=80').catch(() => ({ events: [] }));
    const rows = data.events || [];
    return `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div class="section-title" style="margin:0;border:none;padding:0;">Recent events</div>
        <button class="btn btn-sm" id="events-refresh">Refresh</button>
      </div>
      <div>
        ${rows.length ? rows.map(r => `
          <div class="event-row">
            <span class="event-time">${esc(new Date(r.ts * 1000).toLocaleTimeString())}</span>
            <span class="event-kind">${esc(r.kind)}</span>
            <span class="event-msg" title="${esc(r.message || '')}">${esc((r.message || '').slice(0, 60))}</span>
          </div>
        `).join('') : '<div class="empty-hint">No events yet</div>'}
      </div>
    `;
  }

  /* ── Soul ───────────────────────────────────────────────── */

  let _soulState = { section: 'soul', body: '', loading: false };

  async function soul() {
    if (!_soulState.body) {
      try {
        const data = await api('/api/soul');
        _soulState.body = data.sections?.soul || '';
      } catch { _soulState.body = ''; }
    }
    let stats = {};
    try { stats = (await api('/api/soul')).stats || {}; } catch {}
    return `
      <div style="color:var(--fg-dim);font-size:12px;margin-bottom:12px;">
        IVA's personality is defined by these markdown files. Edit and save — every new chat picks up changes immediately.
      </div>
      <div class="soul-editor">
        <div class="soul-section-tabs">
          ${['soul','personality','taste','heartbeat'].map(s => `
            <button class="${_soulState.section === s ? 'active' : ''}" data-soul-section="${s}">${s}</button>
          `).join('')}
        </div>
        <textarea class="soul-textarea" id="soul-body">${esc(_soulState.body)}</textarea>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div style="color:var(--fg-muted);font-size:11px;font-family:var(--mono);">
            ${(_soulState.section in stats) ? `${stats[_soulState.section].lines} lines · ${stats[_soulState.section].chars} chars` : ''}
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-sm" id="soul-reload">Reload</button>
            <button class="btn btn-sm btn-primary" id="soul-save">Save</button>
          </div>
        </div>
      </div>
    `;
  }

  async function loadSoulSection(name) {
    _soulState.section = name;
    try {
      const data = await api('/api/soul/' + name);
      _soulState.body = data.body || '';
    } catch { _soulState.body = ''; }
    if (window.AdminViews && window.AdminViews.activeTab === 'soul') {
      window.AdminViews.reload('soul');
    }
  }

  async function saveSoulSection() {
    const body = $('#soul-body')?.value || '';
    try {
      await api('/api/soul/' + _soulState.section, { method: 'PUT', body: JSON.stringify({ body }) });
      _soulState.body = body;
      toast(`Saved ${_soulState.section}.md`, 'success');
    } catch (err) {
      toast('Save failed: ' + err.message, 'error');
    }
  }

  /* ── Settings ────────────────────────────────────────────── */

  async function settings() {
    const [providers, sys, cfg] = await Promise.all([
      api('/api/config').catch(() => ({})),
      api('/api/system/status').catch(() => ({})),
      api('/api/config/settings').catch(() => ({ settings: {} })),
    ]);
    const provList = providers.providers || {};
    const settings = cfg.settings || {};
    return `
      <div class="section-title">LLM providers</div>
      <div class="kv-list">
        ${Object.entries(provList).map(([name, p]) => `
          <div class="provider-row">
            <div class="provider-status ${p.enabled ? (p.has_key || name === 'ollama' ? 'online' : 'offline') : 'offline'}"></div>
            <div style="flex:1;min-width:0;">
              <div class="provider-name">${esc(name)}</div>
              <div class="provider-model">${esc(p.model || '—')}${p.tier ? ' · ' + esc(p.tier) : ''}</div>
            </div>
            <label class="toggle" title="${p.enabled ? 'Disable' : 'Enable'}">
              <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="AdminActions.toggleProvider('${esc(name)}', this.checked)">
              <span class="toggle-slider"></span>
            </label>
            ${name !== 'ollama' ? `<button class="btn btn-sm" onclick="AdminActions.openKeyModal('${esc(name)}')" title="Set API key">🔑</button>` : ''}
          </div>
        `).join('') || '<div class="empty-hint">No providers configured</div>'}
      </div>

      <div class="section-title">System</div>
      <div class="toggle-row">
        <span class="toggle-label">Cold mode (approval for exec)</span>
        <label class="toggle"><input type="checkbox" ${settings.cold_mode === 'true' || settings.cold_mode === true ? 'checked' : ''} onchange="AdminActions.saveSetting('cold_mode', this.checked)"><span class="toggle-slider"></span></label>
      </div>
      <div class="toggle-row">
        <span class="toggle-label">ReAct loop</span>
        <label class="toggle"><input type="checkbox" ${settings.use_react_loop === 'true' || settings.use_react_loop === true ? 'checked' : ''} onchange="AdminActions.saveSetting('use_react_loop', this.checked)"><span class="toggle-slider"></span></label>
      </div>
      <div class="toggle-row">
        <span class="toggle-label">RAG enabled</span>
        <label class="toggle"><input type="checkbox" ${settings.rag_enabled === 'true' || settings.rag_enabled === true ? 'checked' : ''} onchange="AdminActions.saveSetting('rag_enabled', this.checked)"><span class="toggle-slider"></span></label>
      </div>
      <div class="toggle-row">
        <span class="toggle-label">Executor sandbox (Docker)</span>
        <label class="toggle"><input type="checkbox" ${settings.executor_sandbox_enabled === 'true' || settings.executor_sandbox_enabled === true ? 'checked' : ''} onchange="AdminActions.saveSetting('executor_sandbox_enabled', this.checked)"><span class="toggle-slider"></span></label>
      </div>

      <div class="section-title">Connection</div>
      <div class="kv-list">
        <div class="kv-row"><span class="kv-key">REST</span><span class="kv-val" style="font-size:11px;">${esc(location.origin + '/api')}</span></div>
        <div class="kv-row"><span class="kv-key">WebSocket</span><span class="kv-val" style="font-size:11px;">${esc((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws')}</span></div>
      </div>

      <div class="section-title">Danger zone</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        <button class="btn btn-sm btn-danger" onclick="AdminActions.reloadRag()">Reload RAG</button>
        <button class="btn btn-sm" onclick="AdminActions.reloadConfig()">Reload config</button>
        <button class="btn btn-sm btn-danger" onclick="AdminActions.clearKey()">Clear API key</button>
      </div>
    `;
  }

  /* ── Costs (Phase 2.6) ───────────────────────────────── */

  async function costs() {
    const days = parseInt($('#costs-days')?.value || '30', 10);
    const [data, budget] = await Promise.all([
      api(`/api/costs/dashboard?days=${days}`).catch(() => ({})),
      api('/api/costs/budget').catch(() => ({})),
    ]);
    const totals = data.totals || { requests: 0, tokens: 0, cost_usd: 0 };
    const series = data.daily_series || [];
    const byProv = data.by_provider || [];
    const byAgent = data.by_agent || [];
    const byUser = data.by_user || [];
    const recent = data.recent || [];
    const maxCost = series.reduce((m, d) => Math.max(m, d.cost_usd), 0.01);
    return `
      <div class="kv-row" style="margin-bottom:16px;">
        <div class="kv-label">Window</div>
        <div class="kv-value" style="display:flex;gap:8px;align-items:center;">
          <select id="costs-days" class="form-input" style="width:auto;">
            <option value="7"  ${days===7?'selected':''}>Last 7 days</option>
            <option value="30" ${days===30?'selected':''}>Last 30 days</option>
            <option value="90" ${days===90?'selected':''}>Last 90 days</option>
          </select>
          <button id="costs-refresh" class="btn btn-sm">Refresh</button>
        </div>
      </div>

      <div class="section-title">Cost overview <span style="color:var(--fg-muted);font-size:12px;">last ${days} days</span></div>
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label">Total spend</div><div class="stat-value accent">$${Number(totals.cost_usd).toFixed(4)}</div></div>
        <div class="stat-card"><div class="stat-label">Requests</div><div class="stat-value">${esc(totals.requests)}</div></div>
        <div class="stat-card"><div class="stat-label">Tokens</div><div class="stat-value">${esc(totals.tokens.toLocaleString())}</div></div>
        <div class="stat-card"><div class="stat-label">Avg $/req</div><div class="stat-value">$${totals.requests ? (totals.cost_usd / totals.requests).toFixed(5) : '0'}</div></div>
      </div>

      <div class="section-title">Daily spend</div>
      <div class="cost-chart" id="cost-chart">
        ${series.map(d => {
          const h = Math.max(2, Math.round((d.cost_usd / maxCost) * 60));
          return `<div class="cost-bar-wrap" title="${d.date}: $${d.cost_usd.toFixed(4)} (${d.requests} req)">
            <div class="cost-bar" style="height:${h}px"></div>
            <div class="cost-bar-label">${d.date.slice(5)}</div>
          </div>`;
        }).join('')}
      </div>

      <div class="section-title">By provider</div>
      <div class="kv-list">
        ${byProv.length ? byProv.map(p => `
          <div class="kv-row">
            <div class="kv-label">${esc(p.provider)}</div>
            <div class="kv-value">$${Number(p.cost_usd).toFixed(4)} <span style="color:var(--fg-muted);">(${p.requests} req · ${p.tokens.toLocaleString()} tok)</span></div>
          </div>
        `).join('') : '<div class="empty-hint">No usage yet</div>'}
      </div>

      <div class="section-title">By agent</div>
      <div class="kv-list">
        ${byAgent.length ? byAgent.map(a => `
          <div class="kv-row">
            <div class="kv-label">${esc(a.agent)}</div>
            <div class="kv-value">$${Number(a.cost_usd).toFixed(4)} <span style="color:var(--fg-muted);">(${a.requests} req)</span></div>
          </div>
        `).join('') : '<div class="empty-hint">No usage yet</div>'}
      </div>

      ${byUser.length ? `
        <div class="section-title">By user (admin view)</div>
        <div class="kv-list">
          ${byUser.map(u => `
            <div class="kv-row">
              <div class="kv-label" style="font-family:var(--mono);font-size:11px;">${esc(u.user_id)}</div>
              <div class="kv-value">$${Number(u.cost_usd).toFixed(4)} <span style="color:var(--fg-muted);">(${u.requests} req)</span></div>
            </div>
          `).join('')}
        </div>
      ` : ''}

      ${budget.budget_usd != null ? `
        <div class="section-title">Monthly budget</div>
        <div class="kv-row">
          <div class="kv-label">${esc(budget.month)}</div>
          <div class="kv-value">$${Number(budget.spend_usd).toFixed(4)} / $${Number(budget.budget_usd).toFixed(2)} ${budget.over_budget ? '<span style="color:var(--err);">over budget</span>' : ''}</div>
        </div>
      ` : ''}

      <div class="section-title">Recent requests</div>
      <div class="kv-list">
        ${recent.length ? recent.map(r => `
          <div class="kv-row" style="display:block;">
            <div style="font-size:12px;">
              <span class="badge">${esc(r.provider)}</span>
              <span style="color:var(--fg-muted);">${esc(r.model || '')}</span>
              <span style="color:var(--fg-muted);">${esc(r.agent || '')}</span>
              <span style="color:var(--fg-muted);">${esc(r.user_id || '')}</span>
            </div>
            <div style="color:var(--fg-dim);font-size:12px;margin-top:2px;">$${Number(r.cost_usd).toFixed(5)} · ${r.tokens} tok · ${fmtTime(r.timestamp)}</div>
          </div>
        `).join('') : '<div class="empty-hint">No recent requests</div>'}
      </div>
    `;
  }

  /* ── Wire up event listeners after render ──────────────── */

  function bind() {
    const tab = window.AdminViews?.activeTab;
    if (!tab) return;

    if (tab === 'memory') {
      $('#mem-search-btn')?.addEventListener('click', async () => {
        const q = $('#mem-search')?.value?.trim();
        if (!q) return;
        try {
          const data = await api('/api/memory/search?q=' + encodeURIComponent(q));
          const results = data.results || [];
          const target = $('#mem-results');
          if (target) {
            target.innerHTML = results.length ? results.map(r => `
              <div class="kv-row" style="display:block;">
                <div style="color:var(--fg-dim);font-size:12px;">${esc((r.content || '').slice(0, 200))}</div>
                <div style="color:var(--fg-muted);font-size:11px;font-family:var(--mono);margin-top:2px;">score: ${(r.score || 0).toFixed(2)}</div>
              </div>
            `).join('') : '<div class="empty-hint">No results</div>';
          }
        } catch (err) { toast('Search failed', 'error'); }
      });
    }

    if (tab === 'projects') {
      $('#proj-create')?.addEventListener('click', async () => {
        const name = $('#proj-name')?.value?.trim();
        const desc = $('#proj-desc')?.value?.trim();
        if (!name) return;
        try {
          await api('/api/projects', { method: 'POST', body: JSON.stringify({ name, description: desc }) });
          toast('Project created', 'success');
          if (window.AdminViews?.reload) window.AdminViews.reload('projects');
        } catch (err) { toast('Failed', 'error'); }
      });
    }

    if (tab === 'rag') {
      $('#rag-search-btn')?.addEventListener('click', async () => {
        const q = $('#rag-search-input')?.value?.trim();
        if (!q) return;
        try {
          const data = await api('/api/rag/search?q=' + encodeURIComponent(q));
          const results = Array.isArray(data) ? data : (data.results || []);
          const target = $('#rag-results');
          if (target) {
            target.innerHTML = results.length ? results.map(r => {
              const content = typeof r === 'string' ? r : (r.content || r.document || JSON.stringify(r));
              return `<div class="kv-row" style="display:block;">
                <div style="color:var(--fg-dim);font-size:12px;">${esc((content || '').slice(0, 300))}</div>
              </div>`;
            }).join('') : '<div class="empty-hint">No results</div>';
          }
        } catch (err) { toast('Search failed', 'error'); }
      });
      $('#rag-ingest-url-btn')?.addEventListener('click', async () => {
        const url = $('#rag-ingest-url')?.value?.trim();
        if (!url) return;
        try {
          await api('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ url }) });
          toast('URL ingested', 'success');
        } catch (err) { toast('Ingest failed', 'error'); }
      });
      $('#rag-ingest-text-btn')?.addEventListener('click', async () => {
        const text = $('#rag-ingest-text')?.value?.trim();
        if (!text) return;
        try {
          await api('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ text, source: 'dashboard' }) });
          toast('Text ingested', 'success');
        } catch (err) { toast('Ingest failed', 'error'); }
      });
    }

    if (tab === 'events') {
      $('#events-refresh')?.addEventListener('click', () => {
        if (window.AdminViews?.reload) window.AdminViews.reload('events');
      });
    }

    if (tab === 'soul') {
      $$('[data-soul-section]').forEach(b => {
        b.addEventListener('click', () => loadSoulSection(b.dataset.soulSection));
      });
      $('#soul-save')?.addEventListener('click', saveSoulSection);
      $('#soul-reload')?.addEventListener('click', async () => {
        try {
          await api('/api/soul/reload', { method: 'POST' });
          await loadSoulSection(_soulState.section);
          toast('Reloaded from disk', 'success');
        } catch (err) { toast('Reload failed', 'error'); }
      });
    }

    if (tab === 'costs') {
      const daysEl = $('#costs-days');
      if (daysEl) {
        daysEl.addEventListener('change', () => {
          if (window.AdminViews?.reload) window.AdminViews.reload('costs');
        });
      }
      $('#costs-refresh')?.addEventListener('click', () => {
        if (window.AdminViews?.reload) window.AdminViews.reload('costs');
      });
    }
  }

  /* ── Public action handlers (called from onclick) ────── */

  const AdminActions = {
    openKeyModal(provider) {
      if (window.appState) window.appState.openKeyModal?.(provider);
    },
    async respondApproval(id, approved) {
      try {
        await api('/api/approvals/' + id + '/respond', { method: 'POST', body: JSON.stringify({ approved }) });
        toast(approved ? 'Approved' : 'Rejected', 'success');
        if (window.AdminViews?.reload) window.AdminViews.reload('approvals');
      } catch (err) { toast('Failed', 'error'); }
    },
    async toggleProvider(name, enabled) {
      try {
        await api('/api/config/providers/' + name + '/toggle', { method: 'POST', body: JSON.stringify({ enabled }) });
        toast(`${name} ${enabled ? 'enabled' : 'disabled'}`, 'success');
      } catch (err) { toast('Toggle failed', 'error'); }
    },
    async saveSetting(key, value) {
      try {
        await api('/api/config/settings', { method: 'PUT', body: JSON.stringify({ key, value: String(value) }) });
        toast(`${key} updated`, 'success');
      } catch (err) { toast('Update failed', 'error'); }
    },
    async reloadRag() {
      try {
        await api('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '../docs' }) });
        toast('RAG reloaded', 'success');
      } catch (err) { toast('Reload failed', 'error'); }
    },
    async reloadConfig() {
      try {
        await api('/api/config/reload', { method: 'POST' });
        toast('Config reloaded', 'success');
        if (window.AdminViews?.reload) window.AdminViews.reload('settings');
      } catch (err) { toast('Reload failed', 'error'); }
    },
    clearKey() {
      if (confirm('Clear the API key stored in this browser?')) {
        localStorage.removeItem('iva_api_key');
        toast('API key cleared. Refresh to enter a new one.', 'info');
        setTimeout(() => location.reload(), 1500);
      }
    },
  };

  window.AdminActions = AdminActions;
  window.AdminViews = {
    activeTab: 'overview',
    overview, memory, projects, rag, agents, approvals, events, soul, costs, settings,
    bind,
    reload(tab) {
      if (window.AppSwitchTab) window.AppSwitchTab(tab);
    },
  };
})();
