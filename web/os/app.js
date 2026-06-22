/* IVA OS — Modern Lightweight UI Controller */

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => [...p.querySelectorAll(s)];

const state = {
  ws: null,
  sessions: [],
  currentSession: null,
  panel: 'overview',
  connected: false,
  chart: null,
};

/* ── Init ──────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initChat();
  initSettings();
  loadOverview();
  connectWS();
  loadSessions();
  loadProjects();
  loadBrain();
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

/* ── WebSocket ─────────────────────────────── */

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws`;
  const indicator = $('#ws-indicator');

  try {
    state.ws = new WebSocket(url);
  } catch { updateWSStatus('disconnected'); return; }

  state.ws.onopen = () => {
    state.connected = true;
    updateWSStatus('connected');
    authWS();
  };

  state.ws.onclose = () => {
    state.connected = false;
    updateWSStatus('disconnected');
    setTimeout(connectWS, 3000);
  };

  state.ws.onerror = () => updateWSStatus('disconnected');

  state.ws.onmessage = e => {
    try { handleWSMessage(JSON.parse(e.data)); } catch {}
  };
}

function authWS() {
  const key = localStorage.getItem('iva_api_key') || prompt('Enter IVA API key:');
  if (key) {
    localStorage.setItem('iva_api_key', key);
    state.ws.send(JSON.stringify({ type: 'auth', api_key: key }));
  }
}

function handleWSMessage(msg) {
  if (msg.type === 'chat_response') {
    hideTyping();
    appendMessage('assistant', msg.content, msg.route);
  } else if (msg.type === 'approval_required') {
    showApproval(msg);
  } else if (msg.type === 'session_update') {
    loadSessions();
  }
}

function updateWSStatus(status) {
  const el = $('#ws-indicator');
  el.className = `ws-badge ${status === 'connected' ? '' : status}`;
  el.querySelector('.label').textContent = status === 'connected' ? 'Connected' : 'Disconnected';
}

/* ── Chat ──────────────────────────────────── */

function initChat() {
  const input = $('#chat-input');
  const send = $('#btn-send');
  const newSession = $('#btn-new-session');

  input?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  input?.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  send?.addEventListener('click', sendMessage);
  newSession?.addEventListener('click', createSession);
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

  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'chat',
      content: text,
      session_id: state.currentSession,
    }));
  } else {
    fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': localStorage.getItem('iva_api_key') || '',
      },
      body: JSON.stringify({ message: text, session_id: state.currentSession }),
    })
    .then(r => r.json())
    .then(data => {
      hideTyping();
      appendMessage('assistant', data.response || data.content, data.route);
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
  if (route) html += `<div class="msg-route">${escapeHtml(route)}</div>`;
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

async function loadSessions() {
  try {
    const res = await fetch('/api/sessions', {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
    state.sessions = data.sessions || [];
    renderSessions();
  } catch {}
}

function renderSessions() {
  const container = $('#chat-sessions');
  if (!container) return;
  container.innerHTML = state.sessions.map(s => `
    <div class="session-item ${s.id === state.currentSession ? 'active' : ''}"
         data-id="${s.id}">
      <div class="session-title">${escapeHtml(s.title || 'Untitled')}</div>
      <div class="session-meta">${s.channel || 'web'} · ${formatTime(s.updated_at)}</div>
    </div>
  `).join('');

  $$('.session-item', container).forEach(el => {
    el.addEventListener('click', () => selectSession(el.dataset.id));
  });
}

function selectSession(id) {
  state.currentSession = id;
  renderSessions();
  loadChatHistory(id);
}

async function createSession() {
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': localStorage.getItem('iva_api_key') || '',
      },
      body: JSON.stringify({ title: 'New Session' }),
    });
    const data = await res.json();
    state.currentSession = data.id;
    await loadSessions();
    toast('Session created', 'success');
  } catch { toast('Failed to create session', 'error'); }
}

async function loadChatHistory(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/messages`, {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
    const container = $('#chat-messages');
    container.innerHTML = '';
    (data.messages || []).forEach(m => appendMessage(m.role, m.content, m.route));
  } catch {}
}

/* ── Overview ──────────────────────────────── */

async function loadOverview() {
  try {
    const res = await fetch('/api/overview', {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
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
  const grid = $('#stats-grid');
  grid.innerHTML = `
    <div class="stat-card"><div class="stat-label">Sessions</div><div class="stat-value accent">${data.total_sessions || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Messages</div><div class="stat-value green">${data.total_messages || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Knowledge</div><div class="stat-value purple">${data.knowledge_count || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Uptime</div><div class="stat-value amber">${data.uptime || '—'}</div></div>
  `;
}

function renderProviders(providers) {
  const el = $('#provider-list');
  if (!providers.length) { el.innerHTML = '<div class="empty-desc">No providers configured</div>'; return; }
  el.innerHTML = providers.map(p => `
    <div class="provider-row">
      <span>${escapeHtml(p.name)}</span>
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

async function loadProjects() {
  try {
    const res = await fetch('/api/projects', {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
    renderProjects(data.projects || []);
  } catch { renderProjects([]); }
}

function renderProjects(projects) {
  const el = $('#projects-table');
  if (!projects.length) { el.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-3);padding:24px;">No projects yet</td></tr>'; return; }
  el.innerHTML = projects.map(p => `
    <tr>
      <td><strong>${escapeHtml(p.name)}</strong></td>
      <td><span class="badge ok">Active</span></td>
      <td style="color:var(--text-3)">${formatTime(p.updated_at)}</td>
    </tr>
  `).join('');
}

$('#btn-new-project')?.addEventListener('click', async () => {
  const name = $('#project-name').value.trim();
  const desc = $('#project-desc').value.trim();
  if (!name) return;
  try {
    await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': localStorage.getItem('iva_api_key') || '' },
      body: JSON.stringify({ name, description: desc }),
    });
    $('#project-name').value = '';
    $('#project-desc').value = '';
    loadProjects();
    toast('Project created', 'success');
  } catch { toast('Failed to create project', 'error'); }
});

/* ── Brain / Memory ────────────────────────── */

async function loadBrain() {
  try {
    const res = await fetch('/api/memory/stats', {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
    renderBrainStats(data);
  } catch { renderBrainStats({}); }
}

function renderBrainStats(data) {
  const grid = $('#brain-stats');
  grid.innerHTML = `
    <div class="stat-card"><div class="stat-label">Episodic</div><div class="stat-value accent">${data.episodic_count || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Semantic</div><div class="stat-value green">${data.semantic_count || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Procedural</div><div class="stat-value purple">${data.procedural_count || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Working</div><div class="stat-value amber">${data.working_count || 0}</div></div>
  `;
}

$('#btn-memory-search')?.addEventListener('click', async () => {
  const query = $('#memory-search').value.trim();
  if (!query) return;
  try {
    const res = await fetch(`/api/memory/search?q=${encodeURIComponent(query)}`, {
      headers: { 'X-API-Key': localStorage.getItem('iva_api_key') || '' }
    });
    const data = await res.json();
    const el = $('#search-results');
    if (!data.results?.length) { el.innerHTML = '<div class="empty-title">No results</div>'; return; }
    el.innerHTML = data.results.map(r => `
      <div style="padding:10px;background:var(--bg-2);border-radius:var(--radius-sm);margin-bottom:6px;font-size:13px;">
        <div style="color:var(--text-2);margin-bottom:4px;">${escapeHtml(r.content?.substring(0, 200) || '')}</div>
        <div style="color:var(--text-4);font-size:11px;">Score: ${(r.score || 0).toFixed(2)}</div>
      </div>
    `).join('');
  } catch { toast('Search failed', 'error'); }
});

/* ── Settings ──────────────────────────────── */

function initSettings() {
  const proto = location.protocol;
  const host = location.host;
  $('#api-url').textContent = `${proto}//${host}/api`;
  $('#ws-url').textContent = `${proto === 'https:' ? 'wss' : 'ws'}://${host}/ws`;
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
    task_id: pendingApproval.task_id,
  }));
  $('#approval-bar')?.classList.remove('visible');
  pendingApproval = null;
}

/* ── Toast ─────────────────────────────────── */

function toast(msg, type = 'info') {
  const container = $('#toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 200); }, 3000);
}

/* ── Utilities ─────────────────────────────── */

function escapeHtml(s) {
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
  return text
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
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>');
}
