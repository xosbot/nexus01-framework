const state = {
  sessionId: null,
  approvalId: null,
  ws: null,
  chart: null,
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Navigation
$$('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.nav-item').forEach((b) => b.classList.remove('active'));
    $$('.panel').forEach((p) => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = btn.dataset.panel;
    $(`#panel-${panel}`).classList.add('active');
    $('#panel-title').textContent = btn.textContent.replace(/^[^\s]+\s/, '').trim();
    if (panel === 'overview') loadOverview();
    if (panel === 'projects') loadProjects();
    if (panel === 'sessions') loadSessions();
    if (panel === 'memory') loadKnowledge();
    if (panel === 'rag') loadRag();
    if (panel === 'costs') loadCosts();
    if (panel === 'agents') loadAgents();
    if (panel === 'channels') loadChannels();
  });
});

// Status
async function refreshStatus() {
  try {
    const data = await api('/system/status');
    $('#status-text').textContent = `${data.agents.length} agents · ${data.channels.length} channels`;
    $('#status-dot').style.background = 'var(--green)';
    return data;
  } catch {
    $('#status-text').textContent = 'Offline';
    $('#status-dot').style.background = 'var(--red)';
    return null;
  }
}

async function loadOverview() {
  const data = await refreshStatus();
  if (!data) return;
  const m = data.memory;
  $('#stats-grid').innerHTML = `
    <div class="stat-card blue"><div class="label">Conversations</div><div class="value">${m.conversations}</div></div>
    <div class="stat-card purple"><div class="label">Sessions</div><div class="value">${m.sessions}</div></div>
    <div class="stat-card green"><div class="label">Projects</div><div class="value">${m.projects}</div></div>
    <div class="stat-card amber"><div class="label">Knowledge</div><div class="value">${m.knowledge}</div></div>`;

  const agents = Object.entries(m.by_agent || {});
  const ctx = $('#agent-chart').getContext('2d');
  if (state.chart) state.chart.destroy();
  state.chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: agents.map(([a]) => a),
      datasets: [{
        label: 'Messages',
        data: agents.map(([, c]) => c),
        backgroundColor: ['#00d4ff88', '#8b5cf688', '#ec489988', '#10b98188'],
        borderRadius: 6,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#64748b' }, grid: { color: '#ffffff08' } },
        y: { ticks: { color: '#64748b' }, grid: { color: '#ffffff08' } },
      },
    },
  });

  $('#provider-list').innerHTML = (data.llm_providers || []).map((p) => `
    <div class="provider-row">
      <span>${p.name} <span style="color:var(--text3)">(${p.model})</span></span>
      <span class="badge ${p.available ? 'ok' : 'off'}">${p.available ? 'online' : 'offline'}</span>
    </div>`).join('');
}

async function loadProjects() {
  const projects = await api('/projects');
  $('#projects-table').innerHTML = projects.length ? projects.map((p) => `
    <tr>
      <td><strong>${esc(p.name)}</strong><br><small style="color:var(--text3)">${esc(p.description)}</small></td>
      <td>${p.status}</td>
      <td class="mono" style="font-size:.75rem">${fmt(p.updated_at)}</td>
      <td><button class="btn btn-sm btn-danger" onclick="deleteProject('${p.id}')">Delete</button></td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">No projects yet</td></tr>';
}

async function loadSessions() {
  const sessions = await api('/sessions');
  $('#sessions-table').innerHTML = sessions.length ? sessions.map((s) => `
    <tr>
      <td>${esc(s.title)}</td>
      <td>${s.channel}</td>
      <td class="mono">${s.project_id || '—'}</td>
      <td class="mono" style="font-size:.75rem">${fmt(s.updated_at)}</td>
      <td>
        <button class="btn btn-sm" onclick="openSession('${s.id}')">Open</button>
        <button class="btn btn-sm btn-danger" onclick="deleteSession('${s.id}')">Delete</button>
      </td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty">No sessions</td></tr>';
  renderChatSessions(sessions);
}

async function loadKnowledge() {
  const items = await api('/memory/knowledge?limit=50');
  $('#knowledge-table').innerHTML = items.length ? items.map((k) => `
    <tr>
      <td class="mono" style="font-size:.75rem">${esc(k.key)}</td>
      <td>${esc(k.value.slice(0, 80))}...</td>
      <td><button class="btn btn-sm btn-danger" onclick="deleteKnowledge('${esc(k.key)}')">Del</button></td>
    </tr>`).join('') : '<tr><td colspan="3" class="empty">Empty knowledge store</td></tr>';
}

async function loadRag() {
  const stats = await api('/rag/stats');
  $('#rag-stats').innerHTML = `
    <div class="stat-card blue"><div class="label">Documents</div><div class="value">${stats.documents}</div></div>
    <div class="stat-card purple"><div class="label">Collection</div><div class="value" style="font-size:1rem">${stats.collection}</div></div>
    <div class="stat-card green"><div class="label">ChromaDB</div><div class="value" style="font-size:1rem">${stats.chroma_enabled ? 'ON' : 'OFF'}</div></div>
    <div class="stat-card amber"><div class="label">Supabase</div><div class="value" style="font-size:1rem">${stats.supabase_enabled ? 'ON' : 'OFF'}</div></div>`;
}

async function loadCosts() {
  const data = await api('/costs');
  $('#cost-stats').innerHTML = `
    <div class="stat-card blue"><div class="label">Requests</div><div class="value">${data.total_requests}</div></div>
    <div class="stat-card purple"><div class="label">Tokens</div><div class="value">${data.total_tokens}</div></div>
    <div class="stat-card green"><div class="label">Cost (USD)</div><div class="value">$${data.total_cost_usd}</div></div>
    <div class="stat-card amber"><div class="label">Period</div><div class="value" style="font-size:1rem">${data.period_days}d</div></div>`;
  $('#costs-table').innerHTML = (data.recent || []).map(r => `
    <tr>
      <td class="mono" style="font-size:.7rem">${fmt(r.timestamp)}</td>
      <td>${r.provider}</td>
      <td>${r.model}</td>
      <td>${r.tokens}</td>
      <td>$${r.cost_usd}</td>
      <td>${r.agent || '—'}</td>
    </tr>`).join('') || '<tr><td colspan="6" class="empty">No usage yet</td></tr>';
}

$('#btn-rag-search').addEventListener('click', async () => {
  const q = $('#rag-query').value.trim();
  if (!q) return;
  const results = await api(`/rag/search?q=${encodeURIComponent(q)}`);
  $('#rag-results').innerHTML = results.length
    ? results.map(r => `<div style="padding:12px 0;border-bottom:1px solid var(--border)"><small style="color:var(--text3)">${esc(r.metadata?.source || '')}</small><br>${esc(r.content)}</div>`).join('')
    : '<div class="empty">No matches</div>';
});

$('#btn-rag-ingest').addEventListener('click', async () => {
  const result = await api('/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '..' }) });
  alert(`Ingested ${result.chunks || result.files || 0} chunks`);
  loadRag();
});

async function loadAgents() {
  const data = await api('/system/status');
  const agents = [
    { name: 'Orchestrator', icon: '🎯', role: 'Routes intent to specialists' },
    { name: 'OSINT', icon: '🔍', role: 'Intelligence gathering' },
    { name: 'Analyst', icon: '📈', role: 'Pattern & anomaly detection' },
    { name: 'Executor', icon: '⚡', role: 'System actions (gated)' },
  ];
  $('#agent-grid').innerHTML = agents.map((a) => `
    <div class="agent-card">
      <div class="icon">${a.icon}</div>
      <div class="name">${a.name}</div>
      <div class="role">${a.role}</div>
    </div>`).join('');
}

async function loadChannels() {
  const data = await api('/system/status');
  const all = ['telegram', 'whatsapp', 'discord', 'slack', 'signal', 'teams', 'web', 'cli'];
  const active = new Set((data.channels || []).map((c) => c.name));
  $('#channel-list').innerHTML = all.map((ch) => `
    <div class="provider-row">
      <span>${ch}</span>
      <span class="badge ${active.has(ch) ? 'ok' : 'off'}">${active.has(ch) ? 'active' : 'inactive'}</span>
    </div>`).join('');
}

// Chat
function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  state.ws = new WebSocket(`${proto}://${location.host}/ws/chat`);
  state.ws.onopen = () => console.log('WS connected');
  state.ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === 'typing') return;
    if (data.type === 'response') {
      state.sessionId = data.session_id;
      appendMessage('assistant', data.text, data.route);
      if (data.requires_approval) {
        state.approvalId = data.approval_id;
        $('#approval-bar').classList.add('visible');
      } else {
        $('#approval-bar').classList.remove('visible');
      }
      loadSessions();
    }
  };
  state.ws.onclose = () => setTimeout(connectWs, 3000);
}

function appendMessage(role, text, route) {
  const el = $('#chat-messages');
  if (el.querySelector('.empty')) el.innerHTML = '';
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = `${route?.length ? `<div class="route">${route.join(' → ')}</div>` : ''}${esc(text)}`;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function sendChat() {
  const text = $('#chat-input').value.trim();
  if (!text) return;
  appendMessage('user', text);
  $('#chat-input').value = '';
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ text, session_id: state.sessionId }));
  } else {
    api('/chat', { method: 'POST', body: JSON.stringify({ text, session_id: state.sessionId }) })
      .then((r) => {
        state.sessionId = r.session_id;
        appendMessage('assistant', r.text, r.route);
        if (r.requires_approval) {
          state.approvalId = r.approval_id;
          $('#approval-bar').classList.add('visible');
        }
      });
  }
}

$('#btn-send').addEventListener('click', sendChat);
$('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

$('#btn-approve').addEventListener('click', () => {
  state.ws?.send(JSON.stringify({ type: 'approve', approved: true, approval_id: state.approvalId, session_id: state.sessionId }));
  $('#approval-bar').classList.remove('visible');
});
$('#btn-reject').addEventListener('click', () => {
  state.ws?.send(JSON.stringify({ type: 'approve', approved: false, approval_id: state.approvalId, session_id: state.sessionId }));
  $('#approval-bar').classList.remove('visible');
});

function renderChatSessions(sessions) {
  $('#chat-sessions').innerHTML = `
    <button class="session-item" onclick="newSession()">+ New Session</button>` +
    sessions.map((s) => `
      <div class="session-item ${s.id === state.sessionId ? 'active' : ''}" onclick="openSession('${s.id}')">
        ${esc(s.title)}<br><small style="color:var(--text3)">${s.channel}</small>
      </div>`).join('');
}

async function newSession() {
  const s = await api('/sessions', { method: 'POST', body: JSON.stringify({ title: 'New Session' }) });
  state.sessionId = s.id;
  $('#chat-messages').innerHTML = '<div class="empty">New session started</div>';
  loadSessions();
}

async function openSession(id) {
  state.sessionId = id;
  const s = await api(`/sessions/${id}`);
  $('#chat-messages').innerHTML = '';
  (s.messages || []).forEach((m) => appendMessage(m.role === 'user' ? 'user' : 'assistant', m.content));
  $$('.nav-item').forEach((b) => b.classList.remove('active'));
  $$('.panel').forEach((p) => p.classList.remove('active'));
  $('[data-panel="chat"]').classList.add('active');
  $('#panel-chat').classList.add('active');
  loadSessions();
}

$('#btn-new-project').addEventListener('click', async () => {
  const name = $('#project-name').value.trim();
  if (!name) return;
  await api('/projects', { method: 'POST', body: JSON.stringify({ name, description: $('#project-desc').value }) });
  $('#project-name').value = '';
  $('#project-desc').value = '';
  loadProjects();
});

$('#btn-memory-search').addEventListener('click', async () => {
  const q = $('#memory-search').value.trim();
  if (!q) return;
  const results = await api(`/memory/search?q=${encodeURIComponent(q)}`);
  $('#search-results').innerHTML = results.length
    ? results.map((r) => `<div style="padding:8px 0;border-bottom:1px solid var(--border)">${esc(r.content)}</div>`).join('')
    : '<div class="empty">No results</div>';
});

window.deleteProject = async (id) => { await api(`/projects/${id}`, { method: 'DELETE' }); loadProjects(); };
window.deleteSession = async (id) => { await api(`/sessions/${id}`, { method: 'DELETE' }); loadSessions(); };
window.deleteKnowledge = async (key) => { await api(`/memory/knowledge/${encodeURIComponent(key)}`, { method: 'DELETE' }); loadKnowledge(); };
window.openSession = openSession;
window.newSession = newSession;

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function fmt(iso) { return iso ? new Date(iso).toLocaleString() : '—'; }

$('#api-url').textContent = `${location.origin}/api`;
$('#ws-url').textContent = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/chat`;

connectWs();
loadOverview();
setInterval(refreshStatus, 30000);
