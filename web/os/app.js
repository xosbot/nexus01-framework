/* IVA OS — VS Code-style Frontend Controller */

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
  pendingApproval: null,
  termLog: [],
};

const MAX_TERM_LINES = 100;

/* ── Terminal Log ──────────────────────────── */

function logTerminal(message, level = 'info') {
  state.termLog.push({ message, level, ts: new Date() });
  const feed = $('#term-feed');
  if (feed) {
    const line = document.createElement('div');
    line.className = 'term-line';
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const icons = { ok: '●', warn: '◆', error: '▲', info: '■' };
    line.innerHTML = `<span class="term-ts" style="color:var(--fg-muted);margin-right:6px;">[${ts}]</span><span style="color:${level === 'ok' ? 'var(--green)' : level === 'warn' ? 'var(--amber)' : level === 'error' ? 'var(--red)' : 'var(--accent)'};margin-right:4px;">${icons[level] || icons.info}</span> ${escapeHtml(message)}`;
    feed.appendChild(line);
    feed.scrollTop = feed.scrollHeight;
    while (feed.children.length > MAX_TERM_LINES) feed.removeChild(feed.firstChild);
  }
  const body = $('#term-body');
  if (body && !feed) {
    const line = document.createElement('div');
    line.className = 'term-line';
    line.innerHTML = `<span class="term-prompt">nexus@os:~$</span> ${escapeHtml(message)}`;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
    while (body.children.length > MAX_TERM_LINES) body.removeChild(body.firstChild);
  }
  const cnt = $('#term-count');
  if (cnt) cnt.textContent = state.termLog.length;
}

/* ── Init ──────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initChat();
  initSettings();
  initRAG();
  initMemory();
  initProjects();
  initSessions();
  initTerminal();
  initApprovals();
  loadOverview();
  loadSessions();
  loadProjects();
  loadBrain();
  loadKnowledge();
  loadAgents();
  loadIntegrations();
  loadWebhooks();
  loadRAGStats();
  loadApprovals();
  connectWS();
});

/* ── Navigation (Activity Bar + Tabs + Sidebar) ── */

function initNav() {
  // Activity bar clicks
  $$('.activity-btn').forEach(btn => {
    btn.addEventListener('click', () => switchPanel(btn.dataset.panel));
  });

  // Sidebar close
  $('#side-close')?.addEventListener('click', () => {
    $('#side')?.classList.remove('open');
  });

  // Tab clicks
  $('#tabs')?.addEventListener('click', e => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    if (e.button === 1 || e.ctrlKey || e.metaKey) {
      // Middle-click or Ctrl+click to close
      const panel = tab.dataset.panel;
      if (panel && panel !== 'overview') closeTab(panel);
      return;
    }
    switchPanel(tab.dataset.panel);
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') $('#side')?.classList.remove('open');
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); focusChat(); }
    if ((e.ctrlKey || e.metaKey) && e.key === '`') { e.preventDefault(); toggleTerminal(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); toggleSidebar(); }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    const n = parseInt(e.key);
    if (n >= 1 && n <= 9) {
      const panels = ['overview','chat','memory','projects','sessions','rag','agents','integrations','approvals'];
      if (panels[n - 1]) {
        e.preventDefault();
        switchPanel(panels[n - 1]);
      }
    }
  });
}

function switchPanel(id) {
  if (!id) return;
  state.panel = id;

  // Update activity bar
  $$('.activity-btn').forEach(b => b.classList.toggle('active', b.dataset.panel === id));

  // Update panels
  $$('.panel').forEach(p => p.classList.toggle('active', p.id === `panel-${id}`));

  // Update tabs
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.panel === id));
  ensureTab(id);

  // Update sidebar title
  const titles = {
    overview: 'Overview', chat: 'Chat', memory: 'Memory',
    projects: 'Projects', sessions: 'Sessions', rag: 'RAG',
    agents: 'Agents', integrations: 'Integrations', approvals: 'Approvals', settings: 'Settings'
  };
  const titleEl = $('#side-title');
  if (titleEl) titleEl.textContent = titles[id] || id;

  // Update sidebar content per panel
  updateSidebar(id);

  // Reload data for the active panel
  if (id === 'overview') loadOverview();
  if (id === 'chat') { loadSessions(); renderChatSessions(); }
  if (id === 'memory') { loadBrain(); loadKnowledge(); }
  if (id === 'projects') loadProjects();
  if (id === 'sessions') loadSessions();
  if (id === 'rag') loadRAGStats();
  if (id === 'agents') loadAgents();
  if (id === 'integrations') { loadIntegrations(); loadWebhooks(); }
  if (id === 'approvals') loadApprovals();
}

function ensureTab(id) {
  const tabs = $('#tabs');
  if (!tabs) return;
  if ($(`.tab[data-panel="${id}"]`)) return;
  const titles = {
    overview: 'Overview', chat: 'Chat', memory: 'Memory',
    projects: 'Projects', sessions: 'Sessions', rag: 'RAG',
    agents: 'Agents', integrations: 'Integrations', approvals: 'Approvals', settings: 'Settings'
  };
  const icons = {
    overview: '⬡', chat: '💬', memory: '🧠', projects: '📁',
    sessions: '⌘', rag: '📚', agents: '🤖', integrations: '🔗', approvals: '✓', settings: '⚙'
  };
  const tab = document.createElement('div');
  tab.className = 'tab active';
  tab.dataset.panel = id;
  tab.innerHTML = `<span class="tab-icon">${icons[id] || '⬡'}</span><span class="tab-label">${titles[id] || id}</span>`;
  tabs.appendChild(tab);
}

function closeTab(id) {
  if (id === 'overview') return;
  const tab = $(`.tab[data-panel="${id}"]`);
  if (tab) tab.remove();
  if (state.panel === id) {
    // Switch to first available tab
    const firstTab = $('.tab');
    if (firstTab) switchPanel(firstTab.dataset.panel);
  }
}

function toggleSidebar() {
  $('#side')?.classList.toggle('open');
}

function updateSidebar(id) {
  const body = $('#side-body');
  if (!body) return;

  // Default sidebar: providers + stats for overview
  if (id === 'overview') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">LLM Providers</div>
        <div class="provider-list" id="provider-list"></div>
      </div>
      <div class="side-section">
        <div class="side-label">Quick Stats</div>
        <div class="side-stats" id="side-stats">
          <div class="side-stat"><span class="side-stat-label">Sessions</span><span class="side-stat-value" id="stat-sessions">—</span></div>
          <div class="side-stat"><span class="side-stat-label">Messages</span><span class="side-stat-value" id="stat-messages">—</span></div>
          <div class="side-stat"><span class="side-stat-label">Knowledge</span><span class="side-stat-value" id="stat-knowledge">—</span></div>
          <div class="side-stat"><span class="side-stat-label">Uptime</span><span class="side-stat-value" id="stat-uptime">—</span></div>
        </div>
      </div>
    `;
    loadOverview();
    return;
  }

  if (id === 'chat') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Current Session</div>
        <div id="chat-side-info">
          <div style="padding:8px;font-size:11px;color:var(--fg-dim);">
            ${state.currentSession ? `<div>Session: <span style="color:var(--accent);font-family:var(--mono);">${escapeHtml(state.currentSession.substring(0, 12))}</span></div>` : '<div>No active session</div>'}
            <div style="margin-top:6px;">Messages: <span style="color:var(--fg);">${state.sessions.filter(s => s.id === state.currentSession)[0]?.message_count || $$('#chat-msgs .msg').length || 0}</span></div>
          </div>
        </div>
      </div>
      <div class="side-section">
        <div class="side-label">Quick Actions</div>
        <div style="display:flex;flex-direction:column;gap:4px;">
          <button class="btn btn-sm" id="btn-new-session-side">New Session</button>
        </div>
      </div>
    `;
    $('#btn-new-session-side')?.addEventListener('click', createSession);
    return;
  }

  if (id === 'memory') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Knowledge Store</div>
        <div id="memory-side-list"></div>
      </div>
    `;
    // Show recent knowledge in sidebar
    const list = $('#memory-side-list');
    if (list) {
      apiFetch('/api/memory/knowledge?limit=10').then(data => {
        const items = Array.isArray(data) ? data : [];
        if (!items.length) { list.innerHTML = '<div style="padding:8px;color:var(--fg-dim);font-size:11px;">No knowledge stored</div>'; return; }
        list.innerHTML = items.map(k => `<div style="padding:6px 8px;font-size:11px;color:var(--fg-dim);border-bottom:1px solid var(--border);">${escapeHtml(k.key?.substring(0, 30) || '')}</div>`).join('');
      }).catch(() => {});
    }
    return;
  }

  if (id === 'projects') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Create Project</div>
        <div style="display:flex;flex-direction:column;gap:4px;">
          <input class="input" id="project-name" placeholder="Project name">
          <input class="input" id="project-desc" placeholder="Description">
          <button class="btn btn-primary btn-sm" id="btn-new-project">Create</button>
        </div>
      </div>
    `;
    $('#btn-new-project')?.addEventListener('click', async () => {
      const name = $('#project-name').value.trim();
      const desc = $('#project-desc').value.trim();
      if (!name) return;
      try {
        await apiFetch('/api/projects', { method: 'POST', body: JSON.stringify({ name, description: desc }) });
        $('#project-name').value = '';
        $('#project-desc').value = '';
        loadProjects();
        toast('Project created', 'success');
      } catch { toast('Failed to create project', 'error'); }
    });
    return;
  }

  if (id === 'sessions') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Filter</div>
        <input class="input" id="sessions-filter" placeholder="Filter sessions...">
      </div>
    `;
    $('#sessions-filter')?.addEventListener('input', e => {
      const q = e.target.value.toLowerCase();
      $$('#sessions-table tr').forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
      });
    });
    return;
  }

  if (id === 'rag') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">RAG Status</div>
        <div class="side-stats">
          <div class="side-stat"><span class="side-stat-label">Collection</span><span class="side-stat-value" style="font-size:11px;" id="rag-collection-side">—</span></div>
          <div class="side-stat"><span class="side-stat-label">Documents</span><span class="side-stat-value" id="rag-docs-side">0</span></div>
        </div>
      </div>
    `;
    loadRAGStats();
    return;
  }

  if (id === 'agents') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Agent Status</div>
        <div id="agent-side-list"></div>
      </div>
    `;
    apiFetch('/api/system/status').then(data => {
      const agents = data.agents || [];
      const list = $('#agent-side-list');
      if (!list) return;
      if (!agents.length) { list.innerHTML = '<div style="padding:8px;color:var(--fg-dim);font-size:11px;">No agents</div>'; return; }
      list.innerHTML = agents.map(a => `<div class="side-stat"><span class="side-stat-label">${escapeHtml(a)}</span><span class="side-stat-value badge ok">Online</span></div>`).join('');
    }).catch(() => {});
    return;
  }

  if (id === 'integrations') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Connected Apps</div>
        <div id="integration-side-list"></div>
      </div>
    `;
    apiFetch('/api/integrations').then(data => {
      const items = Array.isArray(data) ? data : [];
      const list = $('#integration-side-list');
      if (!list) return;
      if (!items.length) { list.innerHTML = '<div style="padding:8px;color:var(--fg-dim);font-size:11px;">None</div>'; return; }
      list.innerHTML = items.map(i => `<div class="side-stat"><span class="side-stat-label">${escapeHtml(i.name)}</span><span class="badge ${i.enabled ? 'ok' : 'off'}">${i.enabled ? 'On' : 'Off'}</span></div>`).join('');
    }).catch(() => {});
    return;
  }

  if (id === 'approvals') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Pending Approvals</div>
        <div id="approvals-side-count" style="padding:8px;font-size:11px;color:var(--fg-dim);">Loading...</div>
      </div>
      <div class="side-section">
        <div class="side-label">Quick Actions</div>
        <div style="display:flex;flex-direction:column;gap:4px;">
          <button class="btn btn-sm" id="btn-approvals-refresh">Refresh</button>
        </div>
      </div>
    `;
    loadApprovals();
    $('#btn-approvals-refresh')?.addEventListener('click', loadApprovals);
    return;
  }

  if (id === 'settings') {
    body.innerHTML = `
      <div class="side-section">
        <div class="side-label">Keyboard Shortcuts</div>
        <div style="padding:4px 0;">
          <div class="side-stat"><span class="side-stat-label">Ctrl+K</span><span class="side-stat-value" style="color:var(--fg-muted)">Chat</span></div>
          <div class="side-stat"><span class="side-stat-label">Ctrl+\`</span><span class="side-stat-value" style="color:var(--fg-muted)">Terminal</span></div>
          <div class="side-stat"><span class="side-stat-label">Ctrl+B</span><span class="side-stat-value" style="color:var(--fg-muted)">Sidebar</span></div>
          <div class="side-stat"><span class="side-stat-label">Alt+1-9</span><span class="side-stat-value" style="color:var(--fg-muted)">Panels</span></div>
        </div>
      </div>
    `;
    return;
  }
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

  try { state.ws = new WebSocket(url); }
  catch { updateWSStatus('disconnected'); return; }

  updateWSStatus('reconnecting');

  state.ws.onopen = () => {
    state.connected = true;
    state.wsRetries = 0;
    state.wsBackoff = 1000;
    updateWSStatus('connected');
    logTerminal('WebSocket connected', 'ok');
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
  if (key) state.ws.send(JSON.stringify({ type: 'auth', api_key: key }));
}

function handleWSMessage(msg) {
  if (msg.type === 'auth_ok') {
    state.authenticated = true;
    logTerminal('Authenticated', 'ok');
    return;
  }
  if (msg.type === 'auth_failed') {
    toast('Invalid API key', 'error');
    localStorage.removeItem('iva_api_key');
    state.authenticated = false;
    return;
  }
  if (msg.type === 'auth_required') { authWS(); return; }
  if (msg.type === 'typing') { showTyping(); return; }
  if (msg.type === 'chat_response') {
    hideTyping();
    appendMessage('assistant', msg.content, msg.route);
    if (msg.session_id) state.currentSession = msg.session_id;
    loadSessions();
    logTerminal(`IVA response via ${msg.route || 'direct'}`, 'info');
    return;
  }
  if (msg.type === 'approval_required') {
    showApproval(msg);
    logTerminal('Approval required for execution', 'warn');
    return;
  }
  if (msg.type === 'system_log') {
    logTerminal(msg.message, msg.level || 'info');
    return;
  }
}

function updateWSStatus(status) {
  const badge = $('#ws-badge');
  if (!badge) return;
  badge.className = 'ws-badge';
  if (status === 'disconnected') badge.classList.add('disconnected');
  if (status === 'reconnecting') badge.classList.add('reconnecting');
  const dot = badge.querySelector('.ws-dot');
  if (dot) {
    dot.style.background = status === 'connected' ? 'var(--green)' :
      status === 'reconnecting' ? 'var(--amber)' : 'var(--red)';
  }
  const label = $('#ws-label');
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
  $('#btn-approve')?.addEventListener('click', () => handleApproval(true));
  $('#btn-reject')?.addEventListener('click', () => handleApproval(false));
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
  const container = $('#chat-msgs');
  if (!container) return;
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
function focusChat() { switchPanel('chat'); setTimeout(() => $('#chat-input')?.focus(), 100); }

/* ── Sessions ──────────────────────────────── */

function initSessions() {
  // Session filter initialized in sidebar as needed
}

async function loadSessions() {
  try {
    const data = await apiFetch('/api/sessions');
    state.sessions = data.sessions || [];
    renderChatSessions();
    renderSessionsTable();
  } catch { logTerminal('Failed to load sessions', 'error'); }
}

function renderChatSessions() {
  const container = $('#chat-sessions');
  if (!container) return;
  container.innerHTML = state.sessions.map(s => `
    <div class="session-item ${s.id === state.currentSession ? 'active' : ''}" data-id="${escapeHtml(s.id)}">
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
    el.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--fg-muted);padding:24px;">No sessions yet</td></tr>';
    return;
  }
  el.innerHTML = state.sessions.map(s => `
    <tr>
      <td><strong>${escapeHtml(s.title || 'Untitled')}</strong></td>
      <td><span class="badge info">${s.channel || 'web'}</span></td>
      <td style="color:var(--fg-dim)">${s.project_id || '—'}</td>
      <td style="color:var(--fg-dim)">${formatTime(s.updated_at)}</td>
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
    const container = $('#chat-msgs');
    if (!container) return;
    container.innerHTML = '';
    const messages = data.messages || [];
    if (messages.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-title">No messages yet</div><div class="empty-desc">Start a conversation with IVA</div></div>';
      return;
    }
    messages.forEach(m => appendMessage(m.role, m.content));
  } catch {}
}

/* ── Overview ──────────────────────────────── */

async function loadOverview() {
  try {
    const data = await apiFetch('/api/overview');
    renderStats(data);
    renderProviders(data.providers || []);
    renderChart(data.agent_activity || {});
    logTerminal('Overview data loaded', 'ok');
  } catch {
    renderStats({});
    renderProviders([]);
    renderChart({});
    logTerminal('Failed to load overview', 'error');
  }
}

function renderStats(data) {
  const update = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val; };
  update('stat-sessions-ov', data.total_sessions ?? '—');
  update('stat-messages-ov', data.total_messages ?? '—');
  update('stat-knowledge-ov', data.knowledge_count ?? '—');
  update('stat-uptime-ov', data.uptime ?? '—');
  update('stat-sessions', data.total_sessions ?? '—');
  update('stat-messages', data.total_messages ?? '—');
  update('stat-knowledge', data.knowledge_count ?? '—');
  update('stat-uptime', data.uptime ?? '—');
}

function renderProviders(providers) {
  const el = $('#provider-list');
  if (!el) return;
  if (!providers?.length) { el.innerHTML = '<div class="empty-desc">No providers configured</div>'; return; }
  el.innerHTML = providers.map(p => {
    const providerData = p.model ? { name: p.name, model: p.model } : { name: p.name, model: '' };
    return `
      <div class="provider-row">
        <div>
          <div class="provider-name">${escapeHtml(providerData.name)}</div>
          ${providerData.model ? `<div class="provider-model">${escapeHtml(providerData.model)}</div>` : ''}
        </div>
        <span class="badge ${p.available ? 'ok' : 'off'}">${p.available ? 'Active' : 'Off'}</span>
      </div>
    `;
  }).join('');
}

function renderChart(activity) {
  const ctx = $('#agent-chart');
  if (!ctx) return;
  if (state.chart) { state.chart.destroy(); state.chart = null; }

  // Clear previous empty state
  const parent = ctx.parentElement;
  const existingEmpty = parent.querySelector('.empty-desc');
  if (existingEmpty && !Object.keys(activity).length) return;

  const labels = Object.keys(activity);
  const values = Object.values(activity);

  if (!labels.length) {
    parent.innerHTML += '<div class="empty-desc" style="margin-top:12px;">No activity yet</div>';
    return;
  }

  state.chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: 'rgba(118, 185, 0, 0.3)',
        borderColor: 'rgba(118, 185, 0, 0.8)',
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
  // Project creation handled in sidebar
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
    el.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--fg-muted);padding:24px;">No projects yet</td></tr>';
    return;
  }
  el.innerHTML = projects.map(p => {
    const progress = p.progress || { total: 0, done: 0, percent: 0 };
    const progressClass = progress.percent >= 100 ? 'ok' : progress.percent >= 50 ? 'info' : 'warn';
    return `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td><span class="badge ${p.status === 'active' ? 'ok' : p.status === 'completed' ? 'info' : 'warn'}">${p.status || 'active'}</span></td>
        <td>
          <div class="progress-bar">
            <div class="progress-fill ${progressClass}" style="width:${progress.percent}%"></div>
            <span class="progress-text">${progress.done}/${progress.total} (${progress.percent}%)</span>
          </div>
        </td>
        <td style="color:var(--fg-dim)">${formatTime(p.updated_at)}</td>
      </tr>
    `;
  }).join('');
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
        <div style="padding:10px;background:var(--bg);border:1px solid var(--border);margin-bottom:6px;">
          <div style="color:var(--fg-dim);margin-bottom:4px;">${escapeHtml(r.content?.substring(0, 200) || '')}</div>
          <div style="color:var(--fg-muted);font-size:11px;">Score: ${(r.score || 0).toFixed(2)}</div>
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
  const update = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val ?? 0; };
  update('brain-episodic', data.episodic_count);
  update('brain-semantic', data.semantic_count);
  update('brain-procedural', data.procedural_count);
  update('brain-working', data.working_count);
}

async function loadKnowledge() {
  try {
    const data = await apiFetch('/api/memory/knowledge?limit=50');
    const el = $('#knowledge-table');
    if (!el) return;
    const items = Array.isArray(data) ? data : [];
    if (!items.length) {
      el.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--fg-muted);padding:24px;">No knowledge stored</td></tr>';
      return;
    }
    el.innerHTML = items.map(k => `
      <tr>
        <td style="font-family:var(--mono);font-size:12px;color:var(--accent);">${escapeHtml(k.key?.substring(0, 40) || '')}</td>
        <td style="color:var(--fg-dim);font-size:12px;">${escapeHtml(k.value?.substring(0, 80) || '')}</td>
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
        const meta = r.metadata || {};
        const source = meta.source || meta.url || '';
        const score = r.score != null ? `<span style="color:var(--accent);font-size:11px;">score:${r.score.toFixed(3)}</span> ` : '';
        const sourceEl = source ? `<span style="color:var(--fg-muted);font-size:11px;"> ${escapeHtml(source)}</span>` : '';
        return `<div style="padding:10px;background:var(--bg);border:1px solid var(--border);margin-bottom:6px;"><div>${score}${sourceEl}</div><div style="color:var(--fg-dim);margin-top:4px;">${escapeHtml(content?.substring(0, 300) || '')}</div></div>`;
      }).join('');
    } catch { toast('RAG search failed', 'error'); }
  });

  $('#btn-rag-ingest')?.addEventListener('click', async () => {
    try {
      toast('Re-ingesting documents...', 'info');
      await apiFetch('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '../docs' }) });
      toast('RAG re-ingested', 'success');
      logTerminal('RAG documents re-ingested', 'ok');
      loadRAGStats();
    } catch { toast('Re-ingest failed', 'error'); logTerminal('RAG re-ingest failed', 'error'); }
  });

  $('#btn-rag-ingest-url')?.addEventListener('click', async () => {
    const url = $('#rag-ingest-url')?.value.trim();
    if (!url) { toast('Enter a URL', 'error'); return; }
    try {
      toast('Fetching URL...', 'info');
      await apiFetch('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ url }) });
      toast('URL ingested', 'success');
      logTerminal(`Ingested: ${url}`, 'ok');
      $('#rag-ingest-url').value = '';
      loadRAGStats();
    } catch { toast('URL ingest failed', 'error'); }
  });

  $('#btn-rag-ingest-text')?.addEventListener('click', async () => {
    const text = $('#rag-ingest-text')?.value.trim();
    if (!text) { toast('Enter text to ingest', 'error'); return; }
    try {
      toast('Ingesting text...', 'info');
      await apiFetch('/api/rag/ingest', { method: 'POST', body: JSON.stringify({ text, source: 'dashboard' }) });
      toast('Text ingested', 'success');
      logTerminal(`Ingested ${text.length} chars`, 'ok');
      $('#rag-ingest-text').value = '';
      loadRAGStats();
    } catch { toast('Text ingest failed', 'error'); }
  });
}

async function loadRAGStats() {
  try {
    const data = await apiFetch('/api/rag/stats');
    const update = (id, val) => { const e = $(`#${id}`); if (e) e.textContent = val; };
    update('rag-collection', data.collection || '—');
    update('rag-documents', data.documents ?? 0);
    update('rag-chroma', data.chroma_enabled ? 'Active' : 'Off');
    update('rag-embedder', data.embedder ? 'Active' : 'Off');
    update('rag-collection-side', data.collection || '—');
    update('rag-docs-side', data.documents ?? 0);
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
    orchestrator: {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="22" height="22"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="M12 8v3M7 17l2-3M17 17l-2-3"/></svg>',
      role: 'Routes tasks to specialized agents'
    },
    osint: {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="22" height="22"><circle cx="12" cy="12" r="3"/><path d="M12 1v4m0 14v4M1 12h4m14 0h4"/><circle cx="12" cy="12" r="10" stroke-dasharray="4 4"/></svg>',
      role: 'Open-source intelligence gathering'
    },
    analyst: {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="22" height="22"><path d="M3 3v18h18"/><path d="M7 16l4-8 4 4 4-6"/></svg>',
      role: 'Data analysis and reporting'
    },
    executor: {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="22" height="22"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
      role: 'Command execution in sandbox'
    },
  };

  if (!agents.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-title">No agents loaded</div></div>';
    return;
  }

  el.innerHTML = agents.map(name => {
    const info = agentInfo[name] || {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="22" height="22"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="8" cy="12" r="1.5"/><circle cx="16" cy="12" r="1.5"/><path d="M10 12h4"/></svg>',
      role: 'Agent'
    };
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

let _modalProvider = null;

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
    navigator.clipboard.writeText(apiUrl).then(() => toast('Copied', 'success'));
  });

  $('#btn-copy-ws')?.addEventListener('click', () => {
    navigator.clipboard.writeText(wsUrl).then(() => toast('Copied', 'success'));
  });

  $('#btn-restart')?.addEventListener('click', () => {
    if (confirm('Restart IVA? This will interrupt all active sessions.')) {
      toast('Restart requested — SSH to restart manually', 'warning');
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

  // Reload providers button
  $('#btn-reload-providers')?.addEventListener('click', loadProviders);

  // Modal handlers
  $('#modal-close')?.addEventListener('click', closeKeyModal);
  $('#modal-cancel')?.addEventListener('click', closeKeyModal);
  $('#modal-save')?.addEventListener('click', saveModalKey);
  $('#modal-toggle-visibility')?.addEventListener('click', () => {
    const input = $('#modal-key-input');
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
  });
  $('#modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeKeyModal();
  });

  // System setting toggles
  $('#toggle-cold-mode')?.addEventListener('change', (e) => saveSetting('cold_mode', e.target.checked));
  $('#toggle-react-loop')?.addEventListener('change', (e) => saveSetting('use_react_loop', e.target.checked));
  $('#toggle-rag')?.addEventListener('change', (e) => saveSetting('rag_enabled', e.target.checked));
  $('#toggle-sandbox')?.addEventListener('change', (e) => saveSetting('executor_sandbox_enabled', e.target.checked));
  $('#select-tier')?.addEventListener('change', (e) => saveSetting('default_tier', e.target.value));

  // Reload config button
  $('#btn-reload-config')?.addEventListener('click', async () => {
    try {
      await apiFetch('/api/config/reload', { method: 'POST' });
      toast('Config reloaded', 'success');
      loadProviders();
    } catch { toast('Reload failed', 'error'); }
  });
}

async function loadProviders() {
  try {
    const data = await apiFetch('/api/config');
    renderProviders(data.providers || {});
    applySystemSettings(data.settings || {});
  } catch {
    const el = $('#settings-providers');
    if (el) el.innerHTML = '<div class="provider-empty">Could not load providers</div>';
  }
}

function renderProviders(providers) {
  const el = $('#settings-providers');
  if (!el) return;

  const names = Object.keys(providers);
  if (!names.length) {
    el.innerHTML = '<div class="provider-empty">No providers configured</div>';
    return;
  }

  const providerIcons = {
    ollama: '🦙', groq: '⚡', gemini: '🔷', openai: '🟢', anthropic: '🟠',
  };

  el.innerHTML = `<div class="provider-cards">${names.map(name => {
    const p = providers[name];
    const hasKey = p.has_key;
    const enabled = p.enabled;
    const statusClass = !enabled ? 'unconfigured' : (p.has_key || name === 'ollama') ? 'online' : 'offline';
    const model = p.model || '—';
    const keyDisplay = p.key_masked || 'Not set';
    const icon = providerIcons[name] || '●';

    return `
      <div class="provider-card ${enabled ? '' : 'disabled'}" data-provider="${escapeHtml(name)}">
        <div class="provider-status ${statusClass}"></div>
        <div class="provider-info">
          <div class="provider-name">${icon} ${escapeHtml(name)}</div>
          <div class="provider-meta">
            <span>Model: ${escapeHtml(model)}</span>
            ${p.tier ? `<span>Tier: ${escapeHtml(p.tier)}</span>` : ''}
          </div>
        </div>
        <div class="provider-key">${escapeHtml(keyDisplay)}</div>
        <div class="provider-actions">
          <label class="toggle" title="${enabled ? 'Disable' : 'Enable'}">
            <input type="checkbox" ${enabled ? 'checked' : ''} onchange="toggleProvider('${escapeHtml(name)}', this.checked)">
            <span class="toggle-slider"></span>
          </label>
          ${name !== 'ollama' ? `
            <button class="btn btn-sm btn-ghost" onclick="openKeyModal('${escapeHtml(name)}')" title="Set API Key">🔑</button>
            <button class="btn btn-sm btn-ghost" onclick="testProvider('${escapeHtml(name)}')" title="Test connection">▶</button>
          ` : ''}
        </div>
      </div>
    `;
  }).join('')}</div>`;
}

function openKeyModal(provider) {
  _modalProvider = provider;
  const modal = $('#modal-overlay');
  const title = $('#modal-title');
  const desc = $('#modal-desc');
  const input = $('#modal-key-input');
  if (title) title.textContent = `Set API Key — ${provider}`;
  if (desc) desc.textContent = `Enter the API key for ${provider}. The key will be stored securely.`;
  if (input) { input.value = ''; input.type = 'password'; }
  if (modal) modal.style.display = 'flex';
  setTimeout(() => input?.focus(), 100);
}

function closeKeyModal() {
  _modalProvider = null;
  const modal = $('#modal-overlay');
  if (modal) modal.style.display = 'none';
}

async function saveModalKey() {
  if (!_modalProvider) return;
  const input = $('#modal-key-input');
  const key = input?.value?.trim();
  if (!key) { toast('Enter an API key', 'warning'); return; }

  try {
    await apiFetch(`/api/config/providers/${_modalProvider}/key`, {
      method: 'PUT',
      body: JSON.stringify({ api_key: key }),
    });
    toast(`${_modalProvider} API key saved`, 'success');
    closeKeyModal();
    loadProviders();
  } catch { toast('Failed to save key', 'error'); }
}

async function testProvider(name) {
  toast(`Testing ${name}...`, 'info');
  try {
    const result = await apiFetch(`/api/config/providers/${name}/test`, { method: 'POST' });
    if (result.ok) {
      toast(`${name}: Connected!`, 'success');
    } else {
      toast(`${name}: ${result.error || 'Connection failed'}`, 'error');
    }
  } catch { toast(`${name}: Test failed`, 'error'); }
}

async function toggleProvider(name, enabled) {
  try {
    await apiFetch(`/api/config/providers/${name}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
    toast(`${name} ${enabled ? 'enabled' : 'disabled'}`, 'success');
    loadProviders();
  } catch { toast('Toggle failed', 'error'); }
}

function applySystemSettings(settings) {
  const coldMode = settings.cold_mode;
  const reactLoop = settings.use_react_loop;
  const ragEnabled = settings.rag_enabled;
  const sandbox = settings.executor_sandbox_enabled;
  const tier = settings.default_tier;

  if (coldMode !== undefined) {
    const el = $('#toggle-cold-mode');
    if (el) el.checked = coldMode === 'true' || coldMode === true;
  }
  if (reactLoop !== undefined) {
    const el = $('#toggle-react-loop');
    if (el) el.checked = reactLoop === 'true' || reactLoop === true;
  }
  if (ragEnabled !== undefined) {
    const el = $('#toggle-rag');
    if (el) el.checked = ragEnabled === 'true' || ragEnabled === true;
  }
  if (sandbox !== undefined) {
    const el = $('#toggle-sandbox');
    if (el) el.checked = sandbox === 'true' || sandbox === true;
  }
  if (tier) {
    const el = $('#select-tier');
    if (el) el.value = tier;
  }
}

async function saveSetting(key, value) {
  try {
    await apiFetch('/api/config/settings', {
      method: 'PUT',
      body: JSON.stringify({ key, value: String(value) }),
    });
    toast(`${key} updated`, 'success');
  } catch { toast('Failed to update setting', 'error'); }
}

/* ── Terminal Panel ────────────────────────── */

function initTerminal() {
  const input = $('#term-input');
  const clearBtn = $('#btn-term-clear');
  const toggleBtn = $('#btn-term-toggle');

  input?.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleTermCommand(input.value.trim());
      input.value = '';
    }
  });

  clearBtn?.addEventListener('click', () => {
    const body = $('#term-body');
    if (body) body.innerHTML = '';
    const feed = $('#term-feed');
    if (feed) feed.innerHTML = '';
  });

  toggleBtn?.addEventListener('click', toggleTerminal);
}

function toggleTerminal() {
  const term = $('#term');
  if (!term) return;
  term.classList.toggle('collapsed');
}

function handleTermCommand(cmd) {
  const body = $('#term-body');
  if (!body) return;

  // Echo the command
  const echoLine = document.createElement('div');
  echoLine.className = 'term-line';
  echoLine.innerHTML = `<span class="term-prompt">nexus@os:~$</span> ${escapeHtml(cmd)}`;
  body.appendChild(echoLine);

  if (!cmd) { body.scrollTop = body.scrollHeight; return; }

  const parts = cmd.split(/\s+/);
  const command = parts[0].toLowerCase();
  const args = parts.slice(1);

  let response = '';

  switch (command) {
    case 'help':
      response = `Available commands:
  help       — Show this help
  clear      — Clear terminal
  status     — Show system status
  sessions   — List active sessions
  agents     — List running agents
  rag        — Show RAG stats
  echo       — Echo text
  uptime     — Show system uptime`;
      break;

    case 'clear':
      body.innerHTML = '';
      body.scrollTop = body.scrollHeight;
      return;

    case 'status':
      apiFetch('/api/system/status').then(data => {
        const lines = [
          `System Status: OK`,
          `Bus: ${data.bus_backend || 'memory'}`,
          `Cold Mode: ${data.cold_mode ? 'Enabled' : 'Disabled'}`,
          `React Loop: ${data.react_loop ? 'Enabled' : 'Disabled'}`,
          `Agents: ${(data.agents || []).join(', ')}`,
          `Channels: ${(data.channels || []).map(c => c.name).join(', ') || 'none'}`,
          `LLM Providers: ${(data.llm_providers || []).map(p => p.name || p).join(', ') || 'none'}`,
        ];
        lines.forEach(l => {
          const line = document.createElement('div');
          line.className = 'term-line';
          line.style.color = 'var(--green)';
          line.textContent = l;
          body.appendChild(line);
        });
        body.scrollTop = body.scrollHeight;
      }).catch(() => {
        const line = document.createElement('div');
        line.className = 'term-line';
        line.style.color = 'var(--red)';
        line.textContent = 'Error: Could not fetch status';
        body.appendChild(line);
        body.scrollTop = body.scrollHeight;
      });
      return;

    case 'sessions':
      apiFetch('/api/sessions').then(data => {
        const sessions = data.sessions || [];
        if (!sessions.length) {
          const line = document.createElement('div');
          line.className = 'term-line';
          line.style.color = 'var(--fg-dim)';
          line.textContent = 'No active sessions.';
          body.appendChild(line);
        } else {
          sessions.slice(-10).forEach(s => {
            const line = document.createElement('div');
            line.className = 'term-line';
            line.textContent = `${s.id?.substring(0, 8) || '—'}  ${s.title || 'Untitled'}  [${s.channel || 'web'}]  ${formatTime(s.updated_at)}`;
            body.appendChild(line);
          });
        }
        body.scrollTop = body.scrollHeight;
      }).catch(() => {});
      return;

    case 'agents':
      apiFetch('/api/system/status').then(data => {
        const agents = data.agents || [];
        if (!agents.length) {
          const line = document.createElement('div');
          line.className = 'term-line';
          line.style.color = 'var(--fg-dim)';
          line.textContent = 'No agents running.';
          body.appendChild(line);
        } else {
          agents.forEach(a => {
            const line = document.createElement('div');
            line.className = 'term-line';
            line.style.color = 'var(--green)';
            line.textContent = `● ${a} — Online`;
            body.appendChild(line);
          });
        }
        body.scrollTop = body.scrollHeight;
      }).catch(() => {});
      return;

    case 'rag':
      apiFetch('/api/rag/stats').then(data => {
        const lines = [
          `Collection: ${data.collection || '—'}`,
          `Documents: ${data.documents || 0}`,
          `Chunks: ${data.chunks || 0}`,
          `ChromaDB: ${data.chroma_enabled ? 'Active' : 'Off'}`,
          `Embedder: ${data.embedder || '—'}`,
        ];
        lines.forEach(l => {
          const line = document.createElement('div');
          line.className = 'term-line';
          line.textContent = l;
          body.appendChild(line);
        });
        body.scrollTop = body.scrollHeight;
      }).catch(() => {});
      return;

    case 'echo':
      response = args.join(' ') || '';
      break;

    case 'uptime':
      apiFetch('/api/overview').then(data => {
        const line = document.createElement('div');
        line.className = 'term-line';
        line.style.color = 'var(--accent)';
        line.textContent = `Uptime: ${data.uptime || '—'}`;
        body.appendChild(line);
        body.scrollTop = body.scrollHeight;
      }).catch(() => {});
      return;

    default:
      response = `Unknown command: ${command}. Type 'help' for available commands.`;
  }

  if (response) {
    response.split('\n').forEach(l => {
      const line = document.createElement('div');
      line.className = 'term-line';
      line.textContent = l;
      body.appendChild(line);
    });
  }
  body.scrollTop = body.scrollHeight;
}

/* ── Approval ──────────────────────────────── */

function showApproval(msg) {
  state.pendingApproval = msg;
  $('#approval-bar')?.classList.add('visible');
}

function handleApproval(approved) {
  if (!state.pendingApproval) return;
  state.ws?.send(JSON.stringify({
    type: 'approval_response',
    approved,
    approval_id: state.pendingApproval.approval_id,
    session_id: state.currentSession,
  }));
  $('#approval-bar')?.classList.remove('visible');
  if (approved) showTyping();
  state.pendingApproval = null;
}

/* ── Approvals Panel ─────────────────────── */

function initApprovals() {
  $('#btn-approvals-refresh')?.addEventListener('click', loadApprovals);
}

async function loadApprovals() {
  try {
    const data = await apiFetch('/api/approvals?include_expired=true');
    renderApprovals(data.approvals || []);
  } catch { renderApprovals([]); }
}

function renderApprovals(approvals) {
  const el = $('#approvals-list');
  if (!el) return;
  if (!approvals.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-title">No pending approvals</div><div class="empty-desc">Customer reply drafts will appear here for review</div></div>';
    return;
  }
  el.innerHTML = approvals.map(a => `
    <div class="approval-card ${a.expired ? 'expired' : ''}" data-id="${escapeHtml(a.id)}">
      <div class="approval-header">
        <span class="badge info">${escapeHtml(a.channel)}</span>
        <span class="approval-time">${formatTime(a.created_at)}</span>
        ${a.expired ? '<span class="badge warn">Expired</span>' : ''}
      </div>
      <div class="approval-session">Session: ${escapeHtml(a.session_id?.substring(0, 12) || '')}</div>
      <div class="approval-text">${escapeHtml(a.text?.substring(0, 200) || '')}</div>
      ${!a.expired ? `
        <div class="approval-actions">
          <button class="btn btn-sm btn-primary" onclick="respondApproval('${a.id}', true)">Approve</button>
          <button class="btn btn-sm" onclick="respondApproval('${a.id}', false)">Reject</button>
        </div>
      ` : ''}
    </div>
  `).join('');
}

async function respondApproval(approvalId, approved) {
  try {
    await apiFetch(`/api/approvals/${approvalId}/respond`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    });
    toast(approved ? 'Approved' : 'Rejected', approved ? 'success' : 'info');
    loadApprovals();
  } catch { toast('Failed to respond', 'error'); }
}

/* ── Toast ─────────────────────────────────── */

function toast(msg, type = 'info') {
  const container = $('#toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 200);
  }, 3000);
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

/* ── Periodic Refresh ──────────────────────── */

setInterval(() => {
  if (state.panel === 'overview') loadOverview();
  loadBrain();
  loadKnowledge();
  loadRAGStats();
}, 30000);
