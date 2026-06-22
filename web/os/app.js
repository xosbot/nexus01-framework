/* IVA OS — Complete Frontend Controller */

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => [...p.querySelectorAll(s)];

const state = {
  ws: null,
  sessions: [],
  currentSession: null,
  panel: 'overview',
  connected: false,
  authenticated: false,
  chart: null,
  wsRetries: 0,
  wsMaxRetries: 5,
  wsBackoff: 1000,
};

/* ── Init ──────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initChat();
  initSettings();
  initRAG();
  initMemory();
  initProjects();
  initSessions();
  loadOverview();
  loadSessions();
  loadProjects();
  loadBrain();
  loadKnowledge();
  loadAgents();
  loadIntegrations();
  loadWebhooks();
  loadRAGStats();
  connectWS();
});

/* ── Navigation ────────────────────────────── */

function initNav() {
  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => switchPanel(btn.dataset.panel));
  });

  $('#hamburger')?.addEventListener('click', toggleSidebar);
  $('#sidebar-close')?.addEventListener('click', closeSidebar);
  $('#sidebar-overlay')?.addEventListener('click', closeSidebar);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSidebar();
    if ((e.ctrlKey || e.metaKey) && e.key === '/') { e.preventDefault(); toggleSidebar(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); focusChat(); }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    const n = parseInt(e.key);
    if (n >= 1 && n <= 9) {
      const panels = ['overview','chat','brain','projects','sessions','rag','agents','integrations','settings'];
      if (panels[n - 1]) switchPanel(panels[n - 1]);
    }
  });
}

function switchPanel(id) {
  state.panel = id;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.panel === id));
  $$('.panel').forEach(p => p.classList.toggle('active', p.id === `panel-${id}`));
  const titles = {
    overview: 'Overview', chat: 'Chat', brain: 'Memory',
    projects: 'Projects', sessions: 'Sessions', rag: 'RAG',
    agents: 'Agents', integrations: 'Integrations', settings: 'Settings'
  };
  $('#panel-title').textContent = titles[id] || id;
  closeSidebar();
}

function toggleSidebar() {
  $('#sidebar').classList.toggle('open');
  $('#sidebar-overlay').classList.toggle('visible');
}

function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#sidebar-overlay').classList.remove('visible');
}

/* ── API Helper ────────────────────────────── */

function apiHeaders() {
  return {
    'X-API-Key': localStorage.getItem('iva_api_key') || '',
    'Content-Type': 'application/json',
  };
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

/* ── WebSocket ─────────────────────────────── */

function connectWS() {
  if (state.wsRetries >= state.wsMaxRetries) {
    updateWSStatus('disconnected');
    toast('WebSocket connection failed. Refresh to retry.', 'error');
    return;
  }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws`;

  try {
    state.ws = new WebSocket(url);
  } catch {
    updateWSStatus('disconnected');
    return;
  }

  updateWSStatus('reconnecting');

  state.ws.onopen = () => {
    state.connected = true;
    state.wsRetries = 0;
    state.wsBackoff = 1000;
    updateWSStatus('connected');
    authWS();
  };

  state.ws.onclose = () => {
    state.connected = false;
    state.authenticated = false;
    state.wsRetries++;
    updateWSStatus('disconnected');
    if (state.wsRetries < state.wsMaxRetries) {
      setTimeout(connectWS, state.wsBackoff);
      state.wsBackoff = Math.min(state.wsBackoff * 1.5, 10000);
    }
  };

  state.ws.onerror = () => updateWSStatus('disconnected');

  state.ws.onmessage = e => {
    try { handleWSMessage(JSON.parse(e.data)); } catch {}
  };
}

function authWS() {
  let key = localStorage.getItem('iva_api_key');
  if (!key) {
    key = prompt('Enter IVA API key:');
    if (key) localStorage.setItem('iva_api_key', key);
  }
  if (key) {
    state.ws.send(JSON.stringify({ type: 'auth', api_key: key }));
  }
}

function handleWSMessage(msg) {
  if (msg.type === 'auth_ok') {
    state.authenticated = true;
    return;
  }
  if (msg.type === 'auth_failed') {
    toast('Invalid API key', 'error');
    localStorage.removeItem('iva_api_key');
    state.authenticated = false;
    return;
  }
  if (msg.type === 'auth_required') {
    authWS();
    return;
  }
  if (msg.type === 'typing') {
    showTyping();
    return;
  }
  if (msg.type === 'chat_response') {
    hideTyping();
    appendMessage('assistant', msg.content, msg.route);
    if (msg.session_id) state.currentSession = msg.session_id;
    loadSessions();
    return;
  }
  if (msg.type === 'approval_required') {
    showApproval(msg);
    return;
  }
}

function updateWSStatus(status) {
  const el = $('#ws-indicator');
  if (!el) return;
  el.className = `ws-badge ${status === 'connected' ? '' : status}`;
  const label = el.querySelector('.label');
  if (label) {
    label.textContent = status === 'connected' ? 'Connected' :
                         status === 'reconnecting' ? 'Reconnecting...' : 'Disconnected';
  }
}

/* ── Chat ──────────────────────────────────── */

function initChat() {
  const input = $('#chat-input');
  const send = $('#btn-send');

  input?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  input?.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  send?.addEventListener('click', sendMessage);
  $('#btn-new-session')?.addEventListener('click', createSession);
  $('#btn-approve')?.addEventListener('click', () => handleApproval(true));
  $('#btn-reject')?.addEventListener('click', () => handleApproval(false));
  $('#btn-toggle-sessions')?.addEventListener('click', () => {
    $('#chat-sidebar-panel')?.classList.toggle('mobile-visible');
  });
  $('#session-search')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    $$('.session-item').forEach(el => {
      const title = el.querySelector('.session-title')?.textContent?.toLowerCase() || '';
      el.style.display = title.includes(q) ? '' : 'none';
    });
  });
}

function sendMessage() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;

  appendMessage('user', text);
  input.value = '';
  input.style.height = 'auto';
  showTyping();

  if (state.ws?.readyState === WebSocket.OPEN && state.authenticated) {
    state.ws.send(JSON.stringify({
      type: 'chat',
      content: text,
      session_id: state.currentSession,
    }));
  } else {
    apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, session_id: state.currentSession }),
    })
    .then(data => {
      hideTyping();
      appendMessage('assistant', data.response, data.route);
      if (data.session_id) state.currentSession = data.session_id;
      loadSessions();
    })
    .catch(() => {
      hideTyping();
      appendMessage('assistant', 'Connection lost. Please try again.');
    });
  }
}

function appendMessage(role, content, route) {
  const container = $('#chat-messages');
  const empty = container.querySelector('.empty-state');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = `msg ${role}`;

  let html = '';
  if (route) {
    const routeStr = Array.isArray(route) ? route.join(' → ') : route;
    html += `<div class="msg-route">${escapeHtml(routeStr)}</div>`;
  }
  html += renderMarkdown(content);
  html += `<div class="msg-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>`;

  div.innerHTML = html;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function showTyping() { $('#typing-indicator')?.classList.add('visible'); }
function hideTyping() { $('#typing-indicator')?.classList.remove('visible'); }
function focusChat() { switchPanel('chat'); $('#chat-input')?.focus(); }

/* ── Sessions ──────────────────────────────── */

function initSessions() {
  $('#sessions-filter')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    $$('#sessions-table tr').forEach(row => {
      const text = row.textContent.toLowerCase();
      row.style.display = text.includes(q) ? '' : 'none';
    });
  });
}

async function loadSessions() {
  try {
    const data = await apiFetch('/api/sessions');
    state.sessions = data.sessions || [];
    renderChatSessions();
    renderSessionsTable();
  } catch {}
}

function renderChatSessions() {
  const container = $('#chat-sessions');
  if (!container) return;
  container.innerHTML = state.sessions.map(s => `
    <div class="session-item ${s.id === state.currentSession ? 'active' : ''}" data-id="${s.id}">
      <div class="session-title">${escapeHtml(s.title || 'Untitled')}</div>
      <div class="session-meta">${s.channel || 'web'} · ${formatTime(s.updated_at)}</div>
    </div>
  `).join('');

  $$('.session-item', container).forEach(el => {
    el.addEventListener('click', () => selectSession(el.dataset.id));
  });
}

function renderSessionsTable() {
  const el = $('#sessions-table');
  if (!el) return;
  if (!state.sessions.length) {
    el.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-3);padding:24px;">No sessions yet</td></tr>';
    return;
  }
  el.innerHTML = state.sessions.map(s => `
    <tr>
      <td><strong>${escapeHtml(s.title || 'Untitled')}</strong></td>
      <td><span class="badge info">${s.channel || 'web'}</span></td>
      <td style="color:var(--text-3)">${s.project_id || '—'}</td>
      <td style="color:var(--text-3)">${formatTime(s.updated_at)}</td>
    </tr>
  `).join('');
}

function selectSession(id) {
  state.currentSession = id;
  renderChatSessions();
  loadChatHistory(id);
}

async function createSession() {
  try {
    const data = await apiFetch('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: 'New Session' }),
    });
    state.currentSession = data.id;
    await loadSessions();
    toast('Session created', 'success');
  } catch { toast('Failed to create session', 'error'); }
}

async function loadChatHistory(sessionId) {
  try {
    const data = await apiFetch(`/api/sessions/${sessionId}/messages`);
    const container = $('#chat-messages');
    container.innerHTML = '';
    const messages = data.messages || [];
    if (messages.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-title">No messages yet</div><div class="empty-desc">Start a conversation with IVA</div></div>';
      return;
    }
    messages.forEach(m => appendMessage(m.role, m.content, null));
  } catch {}
}

/* ── Overview ──────────────────────────────── */

async function loadOverview() {
  try {
    const data = await apiFetch('/api/overview');
    renderStats(data);
    renderProviders(data.providers || []);
    renderChart(data.agent_activity || {});
  } catch {
    renderStats({});
    renderProviders([]);
    renderChart({});
  }
}

function renderStats(data) {
  const el = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val; };
  el('stat-sessions', data.total_sessions || 0);
  el('stat-messages', data.total_messages || 0);
  el('stat-knowledge', data.knowledge_count || 0);
  el('stat-uptime', data.uptime || '—');
}

function renderProviders(providers) {
  const el = $('#provider-list');
  if (!el) return;
  if (!providers.length) { el.innerHTML = '<div class="empty-desc">No providers configured</div>'; return; }
  el.innerHTML = providers.map(p => `
    <div class="provider-row">
      <div>
        <div class="provider-name">${escapeHtml(p.name)}</div>
        ${p.model ? `<div class="provider-model">${escapeHtml(p.model)}</div>` : ''}
      </div>
      <span class="badge ${p.available ? 'ok' : 'off'}">${p.available ? 'Active' : 'Off'}</span>
    </div>
  `).join('');
}

function renderChart(activity) {
  const ctx = $('#agent-chart');
  if (!ctx) return;
  if (state.chart) state.chart.destroy();

  const labels = Object.keys(activity);
  const values = Object.values(activity);

  if (!labels.length) {
    ctx.parentElement.innerHTML += '<div class="empty-desc" style="margin-top:12px;">No activity yet</div>';
    return;
  }

  state.chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: 'rgba(99, 102, 241, 0.3)',
        borderColor: 'rgba(99, 102, 241, 0.8)',
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', font: { size: 11 } } },
        y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', font: { size: 11 } } },
      },
    },
  });
}

/* ── Projects ──────────────────────────────── */

function initProjects() {
  $('#btn-new-project')?.addEventListener('click', async () => {
    const name = $('#project-name').value.trim();
    const desc = $('#project-desc').value.trim();
    if (!name) return;
    try {
      await apiFetch('/api/projects', {
        method: 'POST',
        body: JSON.stringify({ name, description: desc }),
      });
      $('#project-name').value = '';
      $('#project-desc').value = '';
      loadProjects();
      toast('Project created', 'success');
    } catch { toast('Failed to create project', 'error'); }
  });
}

async function loadProjects() {
  try {
    const data = await apiFetch('/api/projects');
    renderProjects(data.projects || []);
  } catch { renderProjects([]); }
}

function renderProjects(projects) {
  const el = $('#projects-table');
  if (!el) return;
  if (!projects.length) {
    el.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-3);padding:24px;">No projects yet</td></tr>';
    return;
  }
  el.innerHTML = projects.map(p => `
    <tr>
      <td><strong>${escapeHtml(p.name)}</strong></td>
      <td><span class="badge ${p.status === 'active' ? 'ok' : p.status === 'completed' ? 'info' : 'warn'}">${p.status || 'active'}</span></td>
      <td style="color:var(--text-3)">${formatTime(p.updated_at)}</td>
    </tr>
  `).join('');
}

/* ── Brain / Memory ────────────────────────── */

function initMemory() {
  $('#btn-memory-search')?.addEventListener('click', async () => {
    const query = $('#memory-search').value.trim();
    if (!query) return;
    try {
      const data = await apiFetch(`/api/memory/search?q=${encodeURIComponent(query)}`);
      const el = $('#search-results');
      const results = data.results || [];
      if (!results.length) { el.innerHTML = '<div class="empty-state"><div class="empty-title">No results</div></div>'; return; }
      el.innerHTML = results.map(r => `
        <div style="padding:10px;background:var(--bg-2);border-radius:var(--radius-sm);margin-bottom:6px;font-size:13px;">
          <div style="color:var(--text-2);margin-bottom:4px;">${escapeHtml(r.content?.substring(0, 200) || '')}</div>
          <div style="color:var(--text-4);font-size:11px;">Score: ${(r.score || 0).toFixed(2)}</div>
        </div>
      `).join('');
    } catch { toast('Search failed', 'error'); }
  });
}

async function loadBrain() {
  try {
    const data = await apiFetch('/api/brain/stats');
    renderBrainStats(data);
  } catch { renderBrainStats({}); }
}

function renderBrainStats(data) {
  const el = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val || 0; };
  el('brain-episodic', data.episodic_count);
  el('brain-semantic', data.semantic_count);
  el('brain-procedural', data.procedural_count);
  el('brain-working', data.working_count);
}

async function loadKnowledge() {
  try {
    const data = await apiFetch('/api/memory/knowledge?limit=50');
    const el = $('#knowledge-table');
    if (!el) return;
    const items = Array.isArray(data) ? data : [];
    if (!items.length) {
      el.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--text-3);padding:24px;">No knowledge stored</td></tr>';
      return;
    }
    el.innerHTML = items.map(k => `
      <tr>
        <td style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--accent-light);">${escapeHtml(k.key?.substring(0, 40) || '')}</td>
        <td style="color:var(--text-2);font-size:12px;">${escapeHtml(k.value?.substring(0, 80) || '')}</td>
      </tr>
    `).join('');
  } catch {}
}

/* ── RAG ───────────────────────────────────── */

function initRAG() {
  $('#btn-rag-search')?.addEventListener('click', async () => {
    const query = $('#rag-query').value.trim();
    if (!query) return;
    try {
      const data = await apiFetch(`/api/rag/search?q=${encodeURIComponent(query)}`);
      const el = $('#rag-results');
      const results = Array.isArray(data) ? data : [];
      if (!results.length) { el.innerHTML = '<div class="empty-state"><div class="empty-title">No results</div></div>'; return; }
      el.innerHTML = results.map(r => {
        const content = typeof r === 'string' ? r : (r.content || r.document || JSON.stringify(r));
        return `
          <div style="padding:10px;background:var(--bg-2);border-radius:var(--radius-sm);margin-bottom:6px;font-size:13px;">
            <div style="color:var(--text-2);">${escapeHtml(content?.substring(0, 300) || '')}</div>
          </div>
        `;
      }).join('');
    } catch { toast('RAG search failed', 'error'); }
  });

  $('#btn-rag-ingest')?.addEventListener('click', async () => {
    try {
      toast('Re-ingesting documents...', 'info');
      await apiFetch('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '../docs' }) });
      toast('RAG re-ingested', 'success');
      loadRAGStats();
    } catch { toast('Re-ingest failed', 'error'); }
  });
}

async function loadRAGStats() {
  try {
    const data = await apiFetch('/api/rag/stats');
    const el = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val; };
    el('rag-collection', data.collection || '—');
    el('rag-documents', data.documents || 0);
    el('rag-chroma', data.chroma_enabled ? 'Active' : 'Off');
    el('rag-embedder', data.embedder ? 'Active' : 'Off');
  } catch {}
}

/* ── Agents ────────────────────────────────── */

async function loadAgents() {
  try {
    const data = await apiFetch('/api/system/status');
    renderAgents(data.agents || []);
  } catch { renderAgents([]); }
}

function renderAgents(agents) {
  const el = $('#agent-grid');
  if (!el) return;

  const agentInfo = {
    orchestrator: { icon: '🧠', role: 'Routes tasks to specialized agents' },
    osint: { icon: '🔍', role: 'Open-source intelligence gathering' },
    analyst: { icon: '📊', role: 'Data analysis and reporting' },
    executor: { icon: '⚡', role: 'Command execution in sandbox' },
  };

  if (!agents.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-title">No agents loaded</div></div>';
    return;
  }

  el.innerHTML = agents.map(name => {
    const info = agentInfo[name] || { icon: '🤖', role: 'Agent' };
    return `
      <div class="agent-card">
        <div class="agent-icon">${info.icon}</div>
        <div class="agent-name">${escapeHtml(name)}</div>
        <div class="agent-role">${info.role}</div>
        <div class="agent-status"><span class="badge ok">Online</span></div>
      </div>
    `;
  }).join('');
}

/* ── Integrations ──────────────────────────── */

async function loadIntegrations() {
  try {
    const data = await apiFetch('/api/integrations');
    const el = $('#integrations-list');
    if (!el) return;
    const items = Array.isArray(data) ? data : [];
    if (!items.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-title">No integrations yet</div><div class="empty-desc">Connect your apps to IVA via API</div></div>';
      return;
    }
    el.innerHTML = items.map(i => `
      <div class="provider-row">
        <div>
          <div class="provider-name">${escapeHtml(i.name)}</div>
          <div class="provider-model">${i.type} · ${i.event_count || 0} events</div>
        </div>
        <span class="badge ${i.enabled ? 'ok' : 'off'}">${i.enabled ? 'Active' : 'Off'}</span>
      </div>
    `).join('');
  } catch {}
}

async function loadWebhooks() {
  try {
    const data = await apiFetch('/api/webhooks/events');
    const el = $('#webhooks-list');
    if (!el) return;
    const events = Array.isArray(data) ? data : [];
    if (!events.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-title">No events yet</div><div class="empty-desc">Webhook events will appear here</div></div>';
      return;
    }
    el.innerHTML = events.slice(-10).reverse().map(e => `
      <div class="provider-row">
        <div>
          <div class="provider-name">${escapeHtml(e.source || 'unknown')}:${escapeHtml(e.event_type || 'event')}</div>
          <div class="provider-model">${formatTime(e.timestamp)}</div>
        </div>
        <span class="badge ${e.processed ? 'ok' : 'warn'}">${e.processed ? 'Processed' : 'Pending'}</span>
      </div>
    `).join('');
  } catch {}
}

/* ── Settings ──────────────────────────────── */

function initSettings() {
  const proto = location.protocol;
  const host = location.host;
  const apiUrl = `${proto}//${host}/api`;
  const wsUrl = `${proto === 'https:' ? 'wss' : 'ws'}://${host}/ws`;

  const apiUrlEl = $('#api-url');
  const wsUrlEl = $('#ws-url');
  if (apiUrlEl) apiUrlEl.textContent = apiUrl;
  if (wsUrlEl) wsUrlEl.textContent = wsUrl;

  $('#btn-copy-api')?.addEventListener('click', () => {
    navigator.clipboard.writeText(apiUrl);
    toast('Copied', 'success');
  });

  $('#btn-copy-ws')?.addEventListener('click', () => {
    navigator.clipboard.writeText(wsUrl);
    toast('Copied', 'success');
  });

  $('#btn-restart')?.addEventListener('click', () => {
    if (confirm('Restart IVA? This will interrupt all active sessions.')) {
      toast('Restart requested — contact admin or SSH to restart', 'warning');
    }
  });

  $('#btn-reload-rag')?.addEventListener('click', async () => {
    try {
      toast('Reloading RAG...', 'info');
      await apiFetch('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '../docs' }) });
      toast('RAG reloaded', 'success');
      loadRAGStats();
    } catch { toast('Reload failed', 'error'); }
  });

  $('#btn-clear-key')?.addEventListener('click', () => {
    localStorage.removeItem('iva_api_key');
    toast('API key cleared. Refresh to re-enter.', 'info');
  });
}

/* ── Approval ──────────────────────────────── */

let pendingApproval = null;

function showApproval(msg) {
  pendingApproval = msg;
  $('#approval-bar')?.classList.add('visible');
}

function handleApproval(approved) {
  if (!pendingApproval) return;
  state.ws?.send(JSON.stringify({
    type: 'approval_response',
    approved,
    approval_id: pendingApproval.approval_id,
    session_id: state.currentSession,
  }));
  $('#approval-bar')?.classList.remove('visible');
  if (approved) showTyping();
  pendingApproval = null;
}

/* ── Toast ─────────────────────────────────── */

function toast(msg, type = 'info') {
  const container = $('#toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 200); }, 3000);
}

/* ── Utilities ─────────────────────────────── */

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function formatTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString();
}

function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/<\/ul>\s*<ul>/g, '')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>');
  return html;
}
