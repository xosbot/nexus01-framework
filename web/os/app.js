const state = {
  sessionId: null,
  approvalId: null,
  ws: null,
  wsReconnectTimer: null,
  chart: null,
  allSessions: [],
  panelNames: [],
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

/* ── Utilities ──────────────────────────────────────── */

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function fmt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Request failed');
    throw new Error(text);
  }
  return res.json();
}

/* ── Markdown renderer ─────────────────────────────── */

function renderMd(text) {
  if (!text) return '';
  let html = esc(text);

  // Code blocks (```...```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="lang-${lang}">${code}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold + italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Blockquote
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // Unordered lists
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);

  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr>');

  // Paragraphs (double newline)
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';

  // Single newlines to <br>
  html = html.replace(/\n/g, '<br>');

  // Clean empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>(<h[1-4]>)/g, '$1');
  html = html.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
  html = html.replace(/<p>(<pre>)/g, '$1');
  html = html.replace(/(<\/pre>)<\/p>/g, '$1');
  html = html.replace(/<p>(<ul>)/g, '$1');
  html = html.replace(/(<\/ul>)<\/p>/g, '$1');
  html = html.replace(/<p>(<blockquote>)/g, '$1');
  html = html.replace(/(<\/blockquote>)<\/p>/g, '$1');
  html = html.replace(/<p>(<hr>)/g, '$1');
  html = html.replace(/(<hr>)<\/p>/g, '$1');

  return html;
}

/* ── Toast notifications ──────────────────────────── */

function toast(message, type = 'info', duration = 3000) {
  const container = $('#toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    el.addEventListener('animationend', () => el.remove());
  }, duration);
}

/* ── Sidebar / Mobile ─────────────────────────────── */

function openSidebar() {
  $('#sidebar').classList.add('open');
  $('#sidebar-overlay').classList.add('visible');
}
function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#sidebar-overlay').classList.remove('visible');
}

$('#hamburger').addEventListener('click', openSidebar);
$('#sidebar-close').addEventListener('click', closeSidebar);
$('#sidebar-overlay').addEventListener('click', closeSidebar);

/* ── Navigation ──────────────────────────────────── */

const navButtons = $$('.nav-item');
state.panelNames = Array.from(navButtons).map((b) => b.dataset.panel);

navButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    navButtons.forEach((b) => { b.classList.remove('active'); b.removeAttribute('aria-current'); });
    $$('.panel').forEach((p) => p.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-current', 'page');
    const panel = btn.dataset.panel;
    $(`#panel-${panel}`).classList.add('active');
    $('#panel-title').textContent = btn.textContent.trim();
    closeSidebar();
    loadPanel(panel);
  });
});

function loadPanel(panel) {
  const loaders = {
    overview: loadOverview,
    projects: loadProjects,
    sessions: loadSessions,
    memory: loadKnowledge,
    rag: loadRag,
    costs: loadCosts,
    agents: loadAgents,
    channels: loadChannels,
  };
  if (loaders[panel]) loaders[panel]();
}

/* ── Keyboard shortcuts ──────────────────────────── */

document.addEventListener('keydown', (e) => {
  // Ctrl+K → focus chat
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const chatPanel = $('#panel-chat');
    if (!chatPanel.classList.contains('active')) {
      navButtons.forEach((b) => b.classList.remove('active'));
      $$('.panel').forEach((p) => p.classList.remove('active'));
      $('[data-panel="chat"]').classList.add('active');
      chatPanel.classList.add('active');
      $('#panel-title').textContent = 'Terminal / Chat';
    }
    $('#chat-input').focus();
  }

  // Ctrl+/ → toggle sidebar (mobile)
  if ((e.ctrlKey || e.metaKey) && e.key === '/') {
    e.preventDefault();
    if ($('#sidebar').classList.contains('open')) closeSidebar();
    else openSidebar();
  }

  // Escape → close sidebar
  if (e.key === 'Escape') {
    closeSidebar();
  }

  // Number keys 1-9 for panel navigation (when not in input)
  if (!e.ctrlKey && !e.metaKey && !e.altKey && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
    const num = parseInt(e.key);
    if (num >= 1 && num <= state.panelNames.length) {
      const btn = $(`[data-panel="${state.panelNames[num - 1]}"]`);
      if (btn) btn.click();
    }
  }
});

/* ── Status / Overview ──────────────────────────── */

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
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#ffffff08' } },
        y: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#ffffff08' }, beginAtZero: true },
      },
    },
  });

  $('#provider-list').innerHTML = (data.llm_providers || []).map((p) => `
    <div class="provider-row">
      <span>${esc(p.name)} <span style="color:var(--text3)">(${esc(p.model)})</span></span>
      <span class="badge ${p.available ? 'ok' : 'off'}">${p.available ? 'online' : 'offline'}</span>
    </div>`).join('');
}

/* ── Projects ──────────────────────────────────── */

async function loadProjects() {
  try {
    const projects = await api('/projects');
    $('#projects-table').innerHTML = projects.length ? projects.map((p) => `
      <tr>
        <td><strong>${esc(p.name)}</strong><br><small style="color:var(--text3)">${esc(p.description || '')}</small></td>
        <td><span class="badge ${p.status === 'active' ? 'ok' : 'off'}">${esc(p.status)}</span></td>
        <td class="mono" style="font-size:.75rem">${fmt(p.updated_at)}</td>
        <td><button class="btn btn-sm btn-danger" onclick="deleteProject('${p.id}')">Delete</button></td>
      </tr>`).join('') : '<tr><td colspan="4" class="empty-state">No projects yet</td></tr>';
  } catch (e) {
    toast('Failed to load projects', 'error');
  }
}

/* ── Sessions ──────────────────────────────────── */

async function loadSessions() {
  try {
    const sessions = await api('/sessions');
    state.allSessions = sessions;
    renderSessionsTable(sessions);
    renderChatSessions(sessions);
  } catch (e) {
    toast('Failed to load sessions', 'error');
  }
}

function renderSessionsTable(sessions) {
  const filter = ($('#sessions-filter')?.value || '').toLowerCase();
  const filtered = filter ? sessions.filter((s) => s.title.toLowerCase().includes(filter) || s.channel.toLowerCase().includes(filter)) : sessions;

  $('#sessions-table').innerHTML = filtered.length ? filtered.map((s) => `
    <tr>
      <td>${esc(s.title)}</td>
      <td><span class="badge ok">${esc(s.channel)}</span></td>
      <td class="mono" style="font-size:.75rem">${s.project_id ? esc(s.project_id.slice(0, 8)) : '—'}</td>
      <td class="mono" style="font-size:.75rem">${fmt(s.updated_at)}</td>
      <td>
        <button class="btn btn-sm" onclick="openSession('${s.id}')">Open</button>
        <button class="btn btn-sm btn-danger" onclick="deleteSession('${s.id}')">Delete</button>
      </td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty-state">No sessions found</td></tr>';
}

if ($('#sessions-filter')) {
  $('#sessions-filter').addEventListener('input', () => renderSessionsTable(state.allSessions));
}

/* ── Memory ──────────────────────────────────────── */

async function loadKnowledge() {
  try {
    const items = await api('/memory/knowledge?limit=50');
    $('#knowledge-table').innerHTML = items.length ? items.map((k) => `
      <tr>
        <td class="mono" style="font-size:.75rem">${esc(k.key)}</td>
        <td>${esc((k.value || '').slice(0, 80))}${(k.value || '').length > 80 ? '...' : ''}</td>
        <td><button class="btn btn-sm btn-danger" onclick="deleteKnowledge('${esc(k.key)}')">Del</button></td>
      </tr>`).join('') : '<tr><td colspan="3" class="empty-state">Empty knowledge store</td></tr>';
  } catch (e) {
    toast('Failed to load knowledge', 'error');
  }
}

/* ── RAG ──────────────────────────────────────── */

async function loadRag() {
  try {
    const stats = await api('/rag/stats');
    $('#rag-stats').innerHTML = `
      <div class="stat-card blue"><div class="label">Documents</div><div class="value">${stats.documents}</div></div>
      <div class="stat-card purple"><div class="label">Collection</div><div class="value" style="font-size:1rem">${esc(stats.collection)}</div></div>
      <div class="stat-card green"><div class="label">ChromaDB</div><div class="value" style="font-size:1rem">${stats.chroma_enabled ? 'ON' : 'OFF'}</div></div>
      <div class="stat-card amber"><div class="label">Supabase</div><div class="value" style="font-size:1rem">${stats.supabase_enabled ? 'ON' : 'OFF'}</div></div>`;
  } catch (e) {
    toast('Failed to load RAG stats', 'error');
  }
}

$('#btn-rag-search').addEventListener('click', async () => {
  const q = $('#rag-query').value.trim();
  if (!q) return;
  try {
    const results = await api(`/rag/search?q=${encodeURIComponent(q)}`);
    $('#rag-results').innerHTML = results.length
      ? results.map((r) => `
        <div style="padding:12px 0;border-bottom:1px solid var(--border)">
          <small style="color:var(--text3)">${esc(r.metadata?.source || '')}</small>
          <div style="margin-top:4px;line-height:1.5">${esc(r.content)}</div>
        </div>`).join('')
      : '<div class="empty-state"><div class="empty-title">No matches</div></div>';
  } catch (e) {
    toast('Search failed', 'error');
  }
});

$('#btn-rag-ingest').addEventListener('click', async () => {
  try {
    const result = await api('/rag/ingest', { method: 'POST', body: JSON.stringify({ path: '..' }) });
    toast(`Ingested ${result.chunks || result.files || 0} chunks`, 'success');
    loadRag();
  } catch (e) {
    toast('Ingest failed', 'error');
  }
});

/* ── Costs ──────────────────────────────────────── */

async function loadCosts() {
  try {
    const data = await api('/costs');
    $('#cost-stats').innerHTML = `
      <div class="stat-card blue"><div class="label">Requests</div><div class="value">${data.total_requests}</div></div>
      <div class="stat-card purple"><div class="label">Tokens</div><div class="value">${data.total_tokens.toLocaleString()}</div></div>
      <div class="stat-card green"><div class="label">Cost (USD)</div><div class="value">$${data.total_cost_usd}</div></div>
      <div class="stat-card amber"><div class="label">Period</div><div class="value" style="font-size:1rem">${data.period_days}d</div></div>`;
    $('#costs-table').innerHTML = (data.recent || []).map((r) => `
      <tr>
        <td class="mono" style="font-size:.7rem">${fmtTime(r.timestamp)}</td>
        <td>${esc(r.provider)}</td>
        <td>${esc(r.model)}</td>
        <td>${r.tokens.toLocaleString()}</td>
        <td>$${r.cost_usd}</td>
        <td>${esc(r.agent || '—')}</td>
      </tr>`).join('') || '<tr><td colspan="6" class="empty-state">No usage yet</td></tr>';
  } catch (e) {
    toast('Failed to load costs', 'error');
  }
}

/* ── Agents ──────────────────────────────────────── */

async function loadAgents() {
  try {
    const data = await api('/system/status');
    const agentMeta = {
      orchestrator: { icon: '🎯', name: 'Orchestrator', role: 'Routes intent to specialists via ReAct loop', color: 'var(--blue)' },
      osint: { icon: '🔍', name: 'OSINT', role: 'Intelligence gathering with Firecrawl + DuckDuckGo', color: 'var(--purple)' },
      analyst: { icon: '📈', name: 'Analyst', role: 'Pattern detection, anomaly analysis, RAG-grounded', color: 'var(--pink)' },
      executor: { icon: '⚡', name: 'Executor', role: 'Docker-sandboxed command execution, Cold Mode gated', color: 'var(--green)' },
    };
    const activeChannels = new Set((data.channels || []).map((c) => c.name));

    $('#agent-grid').innerHTML = (data.agents || []).map((a) => {
      const meta = agentMeta[a] || { icon: '🤖', name: a, role: 'Agent', color: 'var(--text3)' };
      return `
        <div class="agent-card">
          <div class="icon">${meta.icon}</div>
          <div class="name">${meta.name}</div>
          <div class="role">${meta.role}</div>
          <div class="agent-status"><span class="badge ok">active</span></div>
        </div>`;
    }).join('');
  } catch (e) {
    toast('Failed to load agents', 'error');
  }
}

/* ── Channels ──────────────────────────────────── */

async function loadChannels() {
  try {
    const data = await api('/system/status');
    const channelMeta = {
      telegram: { icon: '✈️', desc: 'Primary control channel with inline HITL' },
      whatsapp: { icon: '💬', desc: 'Meta Cloud API integration' },
      discord: { icon: '🎮', desc: 'Message Content Intent enabled' },
      slack: { icon: '💼', desc: 'Events API webhook' },
      signal: { icon: '🔒', desc: 'signal-cli HTTP daemon' },
      teams: { icon: '🏢', desc: 'Azure AD app registration' },
      web: { icon: '🌐', desc: 'FastAPI + WebSocket dashboard' },
      cli: { icon: '⌨️', desc: 'Rich terminal client' },
    };
    const active = new Set((data.channels || []).map((c) => c.name));

    const allChannels = ['telegram', 'whatsapp', 'discord', 'slack', 'signal', 'teams', 'web', 'cli'];
    $('#channel-list').innerHTML = allChannels.map((ch) => {
      const meta = channelMeta[ch] || { icon: '📡', desc: '' };
      const isActive = active.has(ch);
      return `
        <div class="provider-row">
          <span>${meta.icon} ${ch}</span>
          <span style="color:var(--text3);font-size:0.8rem;flex:1;margin:0 12px">${meta.desc}</span>
          <span class="badge ${isActive ? 'ok' : 'off'}">${isActive ? 'active' : 'inactive'}</span>
        </div>`;
    }).join('');
  } catch (e) {
    toast('Failed to load channels', 'error');
  }
}

/* ── WebSocket ──────────────────────────────────── */

function setWsStatus(status) {
  const el = $('#ws-indicator');
  el.className = 'ws-indicator ' + status;
  const label = el.querySelector('.ws-label');
  if (status === 'disconnected') label.textContent = 'Disconnected';
  else if (status === 'reconnecting') label.textContent = 'Reconnecting...';
  else label.textContent = 'Connected';
}

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  state.ws = new WebSocket(`${proto}://${location.host}/ws/chat`);

  state.ws.onopen = () => {
    console.log('WS connected');
    setWsStatus('connected');
    if (state.wsReconnectTimer) {
      clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = null;
    }
  };

  state.ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === 'typing') {
      $('#typing-indicator').classList.add('visible');
      return;
    }
    if (data.type === 'response') {
      $('#typing-indicator').classList.remove('visible');
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

  state.ws.onclose = () => {
    setWsStatus('reconnecting');
    state.wsReconnectTimer = setTimeout(connectWs, 3000);
  };

  state.ws.onerror = () => {
    setWsStatus('disconnected');
  };
}

/* ── Chat ──────────────────────────────────────── */

function appendMessage(role, text, route) {
  const el = $('#chat-messages');
  const empty = el.querySelector('.empty-state');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = `msg ${role}`;

  const now = new Date().toISOString();
  let content = '';
  if (route?.length) {
    content += `<div class="route">${route.map(esc).join(' → ')}</div>`;
  }
  content += role === 'assistant' ? renderMd(text) : esc(text);
  content += `<div class="msg-time">${fmtTime(now)}</div>`;

  div.innerHTML = content;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function sendChat() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  appendMessage('user', text);
  input.value = '';
  input.style.height = 'auto';

  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ text, session_id: state.sessionId }));
  } else {
    $('#typing-indicator').classList.add('visible');
    api('/chat', { method: 'POST', body: JSON.stringify({ text, session_id: state.sessionId }) })
      .then((r) => {
        $('#typing-indicator').classList.remove('visible');
        state.sessionId = r.session_id;
        appendMessage('assistant', r.text, r.route);
        if (r.requires_approval) {
          state.approvalId = r.approval_id;
          $('#approval-bar').classList.add('visible');
        }
      })
      .catch((e) => {
        $('#typing-indicator').classList.remove('visible');
        toast('Chat request failed', 'error');
      });
  }
}

$('#btn-send').addEventListener('click', sendChat);

$('#chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

// Auto-resize textarea
$('#chat-input').addEventListener('input', function () {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

$('#btn-approve').addEventListener('click', () => {
  state.ws?.send(JSON.stringify({ type: 'approve', approved: true, approval_id: state.approvalId, session_id: state.sessionId }));
  $('#approval-bar').classList.remove('visible');
  toast('Approved', 'success');
});

$('#btn-reject').addEventListener('click', () => {
  state.ws?.send(JSON.stringify({ type: 'approve', approved: false, approval_id: state.approvalId, session_id: state.sessionId }));
  $('#approval-bar').classList.remove('visible');
  toast('Cancelled', 'info');
});

function renderChatSessions(sessions) {
  const filter = ($('#session-search')?.value || '').toLowerCase();
  const filtered = filter ? sessions.filter((s) => s.title.toLowerCase().includes(filter)) : sessions;

  $('#chat-sessions').innerHTML =
    filtered.map((s) => `
      <div class="session-item ${s.id === state.sessionId ? 'active' : ''}" onclick="openSession('${s.id}')">
        <div class="session-title">${esc(s.title)}</div>
        <div class="session-meta">${esc(s.channel)} · ${fmt(s.updated_at)}</div>
      </div>`).join('') || '<div class="empty-state" style="padding:24px"><div class="empty-desc">No sessions</div></div>';
}

if ($('#session-search')) {
  $('#session-search').addEventListener('input', () => renderChatSessions(state.allSessions));
}

$('#btn-new-session').addEventListener('click', newSession);

async function newSession() {
  try {
    const s = await api('/sessions', { method: 'POST', body: JSON.stringify({ title: 'New Session' }) });
    state.sessionId = s.id;
    $('#chat-messages').innerHTML = '<div class="empty-state"><div class="empty-icon">💬</div><div class="empty-title">New session started</div></div>';
    loadSessions();
    toast('Session created', 'success');
  } catch (e) {
    toast('Failed to create session', 'error');
  }
}

async function openSession(id) {
  state.sessionId = id;
  try {
    const s = await api(`/sessions/${id}`);
    $('#chat-messages').innerHTML = '';
    (s.messages || []).forEach((m) => appendMessage(m.role === 'user' ? 'user' : 'assistant', m.content));
    navButtons.forEach((b) => { b.classList.remove('active'); b.removeAttribute('aria-current'); });
    $$('.panel').forEach((p) => p.classList.remove('active'));
    $('[data-panel="chat"]').classList.add('active');
    $('[data-panel="chat"]').setAttribute('aria-current', 'page');
    $('#panel-chat').classList.add('active');
    $('#panel-title').textContent = 'Terminal / Chat';
    loadSessions();
  } catch (e) {
    toast('Failed to open session', 'error');
  }
}

/* ── CRUD actions ──────────────────────────────── */

$('#btn-new-project').addEventListener('click', async () => {
  const name = $('#project-name').value.trim();
  if (!name) return;
  try {
    await api('/projects', { method: 'POST', body: JSON.stringify({ name, description: $('#project-desc').value }) });
    $('#project-name').value = '';
    $('#project-desc').value = '';
    loadProjects();
    toast('Project created', 'success');
  } catch (e) {
    toast('Failed to create project', 'error');
  }
});

$('#btn-memory-search').addEventListener('click', async () => {
  const q = $('#memory-search').value.trim();
  if (!q) return;
  try {
    const results = await api(`/memory/search?q=${encodeURIComponent(q)}`);
    $('#search-results').innerHTML = results.length
      ? results.map((r) => `
        <div style="padding:10px 0;border-bottom:1px solid var(--border)">
          <div style="line-height:1.5">${esc(r.content)}</div>
          ${r.score ? `<small style="color:var(--text4)">score: ${r.score.toFixed(3)}</small>` : ''}
        </div>`).join('')
      : '<div class="empty-state"><div class="empty-title">No results</div></div>';
  } catch (e) {
    toast('Search failed', 'error');
  }
});

window.deleteProject = async (id) => {
  if (!confirm('Delete this project?')) return;
  try { await api(`/projects/${id}`, { method: 'DELETE' }); loadProjects(); toast('Project deleted', 'success'); }
  catch (e) { toast('Delete failed', 'error'); }
};

window.deleteSession = async (id) => {
  if (!confirm('Delete this session?')) return;
  try { await api(`/sessions/${id}`, { method: 'DELETE' }); loadSessions(); toast('Session deleted', 'success'); }
  catch (e) { toast('Delete failed', 'error'); }
};

window.deleteKnowledge = async (key) => {
  if (!confirm('Delete this knowledge entry?')) return;
  try { await api(`/memory/knowledge/${encodeURIComponent(key)}`, { method: 'DELETE' }); loadKnowledge(); toast('Entry deleted', 'success'); }
  catch (e) { toast('Delete failed', 'error'); }
};

window.openSession = openSession;
window.newSession = newSession;
window.toast = toast;

/* ── Init ──────────────────────────────────────── */

$('#api-url').textContent = `${location.origin}/api`;
$('#ws-url').textContent = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/chat`;

connectWs();
loadOverview();
setInterval(refreshStatus, 30000);
