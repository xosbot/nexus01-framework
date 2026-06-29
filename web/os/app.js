/* IVA OS — chat controller */

const $  = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => [...p.querySelectorAll(s)];

const state = {
  currentSession: null,
  streaming: false,
  theme: 'dark',
  pendingApproval: null,
  attachments: [],
  voice: null,
  voiceRecording: false,
  drawerOpen: null,   // 'sessions' | 'admin' | null
  activeAdminTab: 'overview',
  recognition: null,
  voiceBase: '',
  hljsThemeDark: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css',
  hljsThemeLight: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github.min.css',
  permissionMode: 'ask',
};

/* ── Theme ───────────────────────────────────────────────────────── */

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  const link = document.getElementById('hljs-theme');
  if (link) link.href = theme === 'light' ? state.hljsThemeLight : state.hljsThemeDark;
  try { localStorage.setItem('iva_theme', theme); } catch {}
}

function getTheme() {
  try { return localStorage.getItem('iva_theme') || 'dark'; } catch { return 'dark'; }
}

/* ── API helper ──────────────────────────────────────────────────── */

function apiHeaders() {
  return {
    'X-API-Key': localStorage.getItem('iva_api_key') || '',
    'Content-Type': 'application/json',
  };
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
  if (res.status === 401) {
    showKeyModal();
    throw new Error('Unauthorized');
  }
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

/* ── Marked.js / syntax highlight ────────────────────────────────── */

function initMarked() {
  if (typeof marked === 'undefined') return;
  marked.setOptions({ breaks: true, gfm: true });
  const renderer = new marked.Renderer();
  renderer.code = function(code, lang) {
    const label = lang || 'text';
    let highlighted = escapeHtml(code);
    if (typeof hljs !== 'undefined') {
      try {
        highlighted = lang && hljs.getLanguage(lang)
          ? hljs.highlight(code, { language: lang }).value
          : hljs.highlightAuto(code).value;
      } catch { /* keep escaped */ }
    }
    return `<div class="code-head"><span>${escapeHtml(label)}</span><button onclick="copyCode(this)">copy</button></div><pre><code class="hljs language-${escapeHtml(label)}">${highlighted}</code></pre>`;
  };
  marked.setOptions({ renderer });
}

function copyCode(btn) {
  const pre = btn.closest('.code-head')?.nextElementSibling;
  const code = pre?.querySelector('code')?.textContent || '';
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = 'copied!';
    setTimeout(() => { btn.textContent = 'copy'; }, 1500);
  }).catch(() => toast('Copy failed', 'error'));
}

function renderMarkdown(text) {
  if (!text) return '';
  if (typeof marked === 'undefined') return escapeHtml(text);
  try { return marked.parse(text); } catch { return escapeHtml(text); }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ── Init ────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  applyTheme(getTheme());
  initMarked();
  bindGlobalEvents();
  initChat();
  initComposer();
  initVoice();
  initAdmin();
  initKeyModal();
  loadOverview();
  loadSessions();
  loadPermissionMode();
});

function bindGlobalEvents() {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (state.drawerOpen) closeDrawer();
      else if ($('#modal-key') && !$('#modal-key').hidden) hideKeyModal();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      const i = $('#chat-input');
      if (i) { i.focus(); i.select(); }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      openDrawer('sessions');
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
      e.preventDefault();
      toggleDrawer();
    }
  });

  $('#drawer-backdrop')?.addEventListener('click', closeDrawer);
  $$('[data-close-drawer]').forEach(el => el.addEventListener('click', closeDrawer));
  $$('[data-close-modal]').forEach(el => el.addEventListener('click', hideKeyModal));
}

/* ── Drawers ─────────────────────────────────────────────────────── */

function openDrawer(name, tab) {
  state.drawerOpen = name;
  if (name === 'sessions') {
    $('#drawer-sessions').hidden = false;
    $('#drawer-admin').hidden = true;
    loadSessions();
  } else if (name === 'admin') {
    $('#drawer-sessions').hidden = true;
    $('#drawer-admin').hidden = false;
    if (tab) switchAdminTab(tab);
    else renderActiveAdmin();
  }
  $('#drawer-backdrop').hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeDrawer() {
  state.drawerOpen = null;
  $('#drawer-sessions').hidden = true;
  $('#drawer-admin').hidden = true;
  $('#drawer-backdrop').hidden = true;
  document.body.style.overflow = '';
}

function toggleDrawer() {
  if (state.drawerOpen === 'admin') openDrawer('sessions');
  else openDrawer('admin', state.activeAdminTab);
}

/* ── Admin tabs ──────────────────────────────────────────────────── */

function switchAdminTab(tab) {
  state.activeAdminTab = tab;
  $$('.admin-tab').forEach(t => t.classList.toggle('active', t.dataset.admin === tab));
  const titles = {
    overview: 'Overview', memory: 'Memory', projects: 'Projects', rag: 'Knowledge',
    agents: 'Agents', approvals: 'Approvals', events: 'Event log',
    soul: 'Soul', costs: 'Costs', settings: 'Settings',
  };
  const t = $('#admin-title');
  if (t) t.textContent = titles[tab] || tab;
  renderActiveAdmin();
}

function renderActiveAdmin() {
  const fn = window.AdminViews && window.AdminViews[state.activeAdminTab];
  const body = $('#admin-body');
  if (!body) return;
  if (typeof fn === 'function') {
    body.innerHTML = '<div class="empty-hint">Loading…</div>';
    Promise.resolve(fn()).then(html => { body.innerHTML = html; bindAdminActions(); }).catch(err => {
      body.innerHTML = `<div class="empty-hint">Error: ${escapeHtml(err.message)}</div>`;
    });
  } else {
    body.innerHTML = '<div class="empty-hint">View not found</div>';
  }
}

function bindAdminActions() {
  if (window.AdminViews) {
    window.AdminViews.activeTab = state.activeAdminTab;
    if (typeof window.AdminViews.bind === 'function') window.AdminViews.bind();
  }
}

function initAdmin() {
  $$('.admin-tab').forEach(t => t.addEventListener('click', () => switchAdminTab(t.dataset.admin)));

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action="open-admin"]');
    if (btn) {
      e.preventDefault();
      openDrawer('admin', btn.dataset.adminTab || 'overview');
    }
    const drawerBtn = e.target.closest('[data-action="open-sessions"]');
    if (drawerBtn) {
      e.preventDefault();
      openDrawer('sessions');
    }
  });
}

/* ── Composer ────────────────────────────────────────────────────── */

function initComposer() {
  const input = $('#chat-input');
  const form  = $('#composer-form');
  const send  = $('#btn-send');

  input?.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
    send.disabled = !input.value.trim() && state.attachments.length === 0;
  });

  input?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  form?.addEventListener('submit', e => {
    e.preventDefault();
    sendMessage();
  });

  $('#btn-attach')?.addEventListener('click', () => $('#file-input')?.click());
  $('#file-input')?.addEventListener('change', e => {
    [...(e.target.files || [])].forEach(addAttachment);
    e.target.value = '';
  });

  $$('.welcome-card').forEach(b => b.addEventListener('click', () => {
    const prompt = b.dataset.prompt;
    if (input) { input.value = prompt; input.focus(); input.dispatchEvent(new Event('input')); sendMessage(); }
  }));
}

function addAttachment(file) {
  if (file.size > 1024 * 1024) { toast(`${file.name} is too large (max 1MB)`, 'warn'); return; }
  const reader = new FileReader();
  reader.onload = () => {
    state.attachments.push({ name: file.name, size: file.size, content: reader.result, type: file.type });
    renderAttachments();
    const send = $('#btn-send');
    if (send) send.disabled = false;
  };
  if (file.type.startsWith('text/') || /\.(txt|md|json|ya?ml|toml|csv|log|py|js|ts|sh|css|html|xml)$/i.test(file.name)) {
    reader.readAsText(file);
  } else {
    reader.readAsDataURL(file);
  }
}

function renderAttachments() {
  const el = $('#chat-attachments');
  if (!el) return;
  if (!state.attachments.length) { el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = state.attachments.map((a, i) => `
    <span class="attachment-chip">
      <span>${escapeHtml(a.name)}</span>
      <span style="color:var(--fg-muted)">${(a.size/1024).toFixed(1)}KB</span>
      <button onclick="removeAttachment(${i})" aria-label="Remove">×</button>
    </span>
  `).join('');
}

function removeAttachment(i) {
  state.attachments.splice(i, 1);
  renderAttachments();
  const send = $('#btn-send');
  if (send) send.disabled = !($('#chat-input')?.value.trim()) && state.attachments.length === 0;
}

/* ── Chat send / stream ─────────────────────────────────────────── */

function initChat() {
  $('#btn-approve')?.addEventListener('click', () => respondApproval(true));
  $('#btn-reject')?.addEventListener('click', () => respondApproval(false));
  $('#topbar-mode')?.addEventListener('click', () => {
    const next = state.permissionMode === 'ask' ? 'allow' : 'ask';
    setPermissionMode(next);
  });
}

async function sendMessage() {
  const input = $('#chat-input');
  const raw = input.value.trim();
  if (!raw && !state.attachments.length) return;

  let messageText = raw;
  if (state.attachments.length) {
    const att = state.attachments.map(a =>
      `\n\n[Attached: ${a.name} (${(a.size/1024).toFixed(1)} KB)]\n\`\`\`\n${a.content.substring(0, 8000)}\n\`\`\``
    ).join('');
    messageText = raw ? raw + att : att.replace(/^\n+/, '');
  }
  state.attachments = [];
  renderAttachments();
  input.value = '';
  input.style.height = 'auto';
  const send = $('#btn-send');
  if (send) send.disabled = true;

  const welcome = $('#chat-welcome');
  if (welcome) welcome.remove();
  const typing = ensureTypingIndicator();
  appendUserMessage(messageText);

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ message: messageText, session_id: state.currentSession }),
    });
    if (!res.ok || !res.body) {
      removeTyping(typing);
      appendAssistantMessage('**Error.** Connection failed.', 'error');
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentBubble = null;
    let full = '';
    let sources = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (!payload) continue;
        let evt;
        try { evt = JSON.parse(payload); } catch { continue; }

        if (evt.type === 'sources') {
          sources = evt.sources || [];
        } else if (evt.type === 'memory_recall') {
          if (!currentBubble) {
            removeTyping(typing);
            currentBubble = createAssistantBubble();
          }
          appendMemoryRecall(currentBubble, evt.memories || []);
        } else if (evt.type === 'agent_iteration') {
          if (!currentBubble) {
            removeTyping(typing);
            currentBubble = createAssistantBubble();
          }
          appendAgentStep(currentBubble, evt);
        } else if (evt.type === 'tool_started') {
          if (!currentBubble) {
            removeTyping(typing);
            currentBubble = createAssistantBubble();
          }
          appendToolCall(currentBubble, evt);
        } else if (evt.type === 'tool_finished') {
          updateToolCall(currentBubble, evt);
        } else if (evt.type === 'approval_requested') {
          appendApprovalRequest(currentBubble, evt);
        } else if (evt.type === 'memory_proposed') {
          appendMemoryProposed(currentBubble, evt);
        } else if (evt.type === 'chunk') {
          if (!currentBubble) {
            removeTyping(typing);
            currentBubble = createAssistantBubble();
          }
          full += evt.content;
          updateAssistantBubble(currentBubble, full, sources);
        } else if (evt.type === 'command') {
          removeTyping(typing);
          currentBubble = null;
          appendCommandResult(evt);
          if (evt.session_id) state.currentSession = evt.session_id;
          if (evt.side_effect === 'theme_changed') {
            applyTheme(evt.data?.mode || 'dark');
          } else if (evt.side_effect === 'mode_changed') {
            state.permissionMode = evt.data?.mode || 'ask';
            updateModeBadge();
          } else if (evt.side_effect === 'new_session') {
            state.currentSession = null;
            updateTopbarTitle('New chat');
          }
        } else if (evt.type === 'done') {
          if (evt.session_id) state.currentSession = evt.session_id;
          if (currentBubble) finalizeAssistantBubble(currentBubble, full, sources);
          loadSessions();
        } else if (evt.type === 'error') {
          removeTyping(typing);
          if (!currentBubble) appendAssistantMessage(`**Error.** ${escapeHtml(evt.error || 'unknown')}`, 'error');
          else finalizeAssistantBubble(currentBubble, full, sources);
        }
      }
    }
  } catch (err) {
    removeTyping(typing);
    appendAssistantMessage('**Connection lost.** Please try again.', 'error');
  }
}

function appendUserMessage(text) {
  const container = $('#chat-msgs');
  if (!container) return;
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `
    <div class="msg-content">${renderMarkdown(text)}</div>
    <div class="msg-actions">
      <button class="msg-action" title="Edit" onclick="editUserMessage(this)" aria-label="Edit">✎</button>
      <button class="msg-action" title="Copy" onclick="copyUserMessage(this)" aria-label="Copy">⧉</button>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  updateTopbarTitle(text.slice(0, 60) || 'New chat');
}

function createAssistantBubble() {
  const container = $('#chat-msgs');
  if (!container) return null;
  const div = document.createElement('div');
  div.className = 'msg assistant streaming';
  div.innerHTML = `
    <div class="msg-role"><span>IVA</span></div>
    <div class="msg-content"></div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

// ── Inline progress UI for agent steps, tool calls, memory events ────────

function _ensureProgressArea(bubble) {
  if (!bubble) return null;
  let area = bubble.querySelector('.progress-area');
  if (!area) {
    area = document.createElement('div');
    area.className = 'progress-area';
    const content = bubble.querySelector('.msg-content');
    if (content) bubble.insertBefore(area, content);
    else bubble.appendChild(area);
  }
  return area;
}

function appendMemoryRecall(bubble, memories) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  if (!memories.length) return;
  const chip = document.createElement('div');
  chip.className = 'memory-recall-chip';
  chip.innerHTML = `<span class="chip-icon">🧠</span> <span>${memories.length} memor${memories.length === 1 ? 'y' : 'ies'} used</span>`;
  const detail = document.createElement('div');
  detail.className = 'memory-recall-detail';
  detail.style.display = 'none';
  detail.innerHTML = memories.map(m =>
    `<div class="memory-recall-item"><span class="memory-type">${escapeHtml(m.type || 'memory')}</span> ${escapeHtml(m.content || '')}</div>`
  ).join('');
  chip.addEventListener('click', () => {
    detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
  });
  area.appendChild(chip);
  area.appendChild(detail);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function appendAgentStep(bubble, evt) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  const step = document.createElement('div');
  step.className = 'agent-step';
  step.innerHTML = `<span class="step-icon">🧠</span> <span>Reasoning iteration ${evt.n}/${evt.max || '?'}</span>`;
  area.appendChild(step);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function appendToolCall(bubble, evt) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  const card = document.createElement('div');
  card.className = 'tool-call pending';
  card.dataset.toolId = evt.id;
  const argsPreview = JSON.stringify(evt.args || {}).slice(0, 120);
  card.innerHTML = `
    <div class="tool-call-header">
      <span class="tool-icon">⚙️</span>
      <span class="tool-name">${escapeHtml(evt.name || 'tool')}</span>
      <span class="tool-status">⏳</span>
    </div>
    <div class="tool-call-args">${escapeHtml(argsPreview)}</div>
  `;
  area.appendChild(card);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function updateToolCall(bubble, evt) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  const card = area.querySelector(`.tool-call[data-tool-id="${evt.id}"]`);
  if (!card) return;
  card.classList.remove('pending');
  card.classList.add(evt.ok ? 'done' : 'error');
  const status = card.querySelector('.tool-status');
  if (status) status.textContent = evt.ok ? `✓ ${evt.duration_ms || 0}ms` : '✗';
  const result = document.createElement('div');
  result.className = 'tool-call-result';
  const content = (evt.content || '').slice(0, 400);
  result.textContent = content;
  card.appendChild(result);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function appendApprovalRequest(bubble, evt) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  const bar = document.createElement('div');
  bar.className = 'approval-bar';
  bar.innerHTML = `
    <span class="approval-icon">🔐</span>
    <span class="approval-text">${escapeHtml(evt.description || 'Action requires approval')}</span>
    <button class="approval-yes" data-approval-id="${escapeHtml(evt.approval_id || '')}">Approve</button>
    <button class="approval-no" data-approval-id="${escapeHtml(evt.approval_id || '')}">Deny</button>
  `;
  bar.querySelector('.approval-yes').addEventListener('click', () => respondApproval(evt.approval_id, true, bar));
  bar.querySelector('.approval-no').addEventListener('click', () => respondApproval(evt.approval_id, false, bar));
  area.appendChild(bar);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

async function respondApproval(approvalId, approved, bar) {
  if (!approvalId) return;
  bar.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const res = await fetch('/api/chat/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_id: approvalId, approved, session_id: state.currentSession || 'web' }),
    });
    const data = await res.json();
    if (approved && data.success) {
      bar.innerHTML = `<span class="approval-icon">✅</span> <span class="approval-text">Approved: ${escapeHtml(String(data.text || '').slice(0, 200))}</span>`;
    } else if (!approved) {
      bar.innerHTML = `<span class="approval-icon">⛔</span> <span class="approval-text">Denied</span>`;
    } else {
      bar.innerHTML = `<span class="approval-icon">⚠️</span> <span class="approval-text">Failed: ${escapeHtml(String(data.text || '').slice(0, 200))}</span>`;
    }
  } catch (e) {
    bar.innerHTML = `<span class="approval-icon">⚠️</span> <span class="approval-text">Network error</span>`;
  }
}

function appendMemoryProposed(bubble, evt) {
  const area = _ensureProgressArea(bubble);
  if (!area) return;
  const chip = document.createElement('div');
  chip.className = 'memory-proposed-chip';
  chip.innerHTML = `
    <span class="chip-icon">💡</span>
    <span class="chip-content">I learned: ${escapeHtml(evt.content || '')}</span>
    <span class="chip-type">${escapeHtml(evt.memory_type || '')}</span>
    <button class="chip-accept" data-memory-id="${escapeHtml(evt.memory_id || '')}">✓</button>
    <button class="chip-reject" data-memory-id="${escapeHtml(evt.memory_id || '')}">✗</button>
  `;
  chip.querySelector('.chip-accept').addEventListener('click', () => respondMemory(evt.memory_id, 'approve', chip));
  chip.querySelector('.chip-reject').addEventListener('click', () => respondMemory(evt.memory_id, 'reject', chip));
  area.appendChild(chip);
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

async function respondMemory(memoryId, action, chip) {
  if (!memoryId) return;
  chip.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const res = await fetch(`/api/memory/${memoryId}/${action}`, { method: 'POST' });
    if (res.ok) {
      chip.classList.add(action === 'approve' ? 'accepted' : 'rejected');
      chip.querySelector('.chip-content').textContent =
        (action === 'approve' ? '✓ Accepted: ' : '✗ Rejected: ') + (chip.querySelector('.chip-content').textContent.replace(/^I learned: /, ''));
    }
  } catch (e) {
    chip.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}

function updateAssistantBubble(bubble, full, sources) {
  if (!bubble) return;
  const c = bubble.querySelector('.msg-content');
  if (c) c.innerHTML = renderMarkdown(full);
  bubble.dataset.content = full;
  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function finalizeAssistantBubble(bubble, full, sources) {
  if (!bubble) return;
  bubble.classList.remove('streaming');
  const c = bubble.querySelector('.msg-content');
  if (c) c.innerHTML = renderMarkdown(full);
  bubble.dataset.content = full;

  const actions = document.createElement('div');
  actions.className = 'msg-actions';
  actions.innerHTML = `
    <button class="msg-action" title="Copy" onclick="copyAssistantMessage(this)" aria-label="Copy">⧉</button>
    <button class="msg-action" title="Regenerate" onclick="regenerateLast(this)" aria-label="Regenerate">↻</button>
  `;
  bubble.appendChild(actions);

  if (sources?.length) {
    const cEl = document.createElement('div');
    cEl.className = 'msg citations';
    cEl.innerHTML = `
      <div class="citations-head" onclick="this.parentElement.classList.toggle('open')">
        <span>📄 ${sources.length} source${sources.length === 1 ? '' : 's'}</span>
        <span class="chev">▾</span>
      </div>
      <div class="citations-body">
        ${sources.map((s, i) => `
          <div class="citation">
            <span class="citation-num">[${i+1}]</span>
            ${s.title ? `<div><strong>${escapeHtml(s.title)}</strong></div>` : ''}
            ${s.source ? `<div class="citation-source">${escapeHtml(s.source)}</div>` : ''}
            <div class="citation-content">${escapeHtml(s.content || '').substring(0, 240)}${(s.content||'').length > 240 ? '…' : ''}</div>
          </div>
        `).join('')}
      </div>
    `;
    bubble.appendChild(cEl);
  }

  const container = $('#chat-msgs');
  if (container) container.scrollTop = container.scrollHeight;
}

function appendAssistantMessage(text, role = 'assistant') {
  const container = $('#chat-msgs');
  if (!container) return;
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="msg-role"><span>${role.toUpperCase()}</span></div><div class="msg-content">${renderMarkdown(text)}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendCommandResult(evt) {
  const container = $('#chat-msgs');
  if (!container) return;
  const div = document.createElement('div');
  div.className = 'command-result';
  div.innerHTML = `
    <div class="command-card">
      <div class="command-title">/${escapeHtml(evt.title || 'command')}</div>
      <div class="command-text">${renderMarkdown(evt.text || '')}</div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function ensureTypingIndicator() {
  const container = $('#chat-msgs');
  if (!container) return null;
  let el = $('#typing-indicator');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'typing-indicator';
  el.className = 'typing';
  el.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span><span>IVA thinking…</span>';
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  return el;
}

function removeTyping(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
  const t = $('#typing-indicator');
  if (t && t !== el) t.remove();
}

/* ── Message actions ────────────────────────────────────────────── */

function copyUserMessage(btn) {
  const msg = btn.closest('.msg');
  const text = msg?.querySelector('.msg-content')?.textContent || '';
  doCopy(btn, text);
}

function copyAssistantMessage(btn) {
  const msg = btn.closest('.msg');
  const text = msg?.dataset.content || msg?.querySelector('.msg-content')?.textContent || '';
  doCopy(btn, text);
}

function doCopy(btn, text) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('ok');
    const orig = btn.textContent;
    btn.textContent = '✓';
    setTimeout(() => { btn.classList.remove('ok'); btn.textContent = orig; }, 1500);
  }).catch(() => toast('Copy failed', 'error'));
}

function editUserMessage(btn) {
  const msg = btn.closest('.msg');
  if (!msg) return;
  const text = msg.querySelector('.msg-content')?.textContent || '';
  let next = msg.nextElementSibling;
  while (next) { const n = next.nextElementSibling; next.remove(); next = n; }
  msg.remove();
  const input = $('#chat-input');
  if (input) {
    input.value = text;
    input.focus();
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
    const send = $('#btn-send'); if (send) send.disabled = false;
  }
}

function regenerateLast(btn) {
  const msg = btn.closest('.msg');
  if (!msg) return;
  const prev = msg.previousElementSibling;
  while (prev && !prev.classList.contains('user')) prev.remove();
  if (!prev || !prev.classList.contains('user')) {
    toast('No previous user message to regenerate from', 'warn');
    return;
  }
  const text = prev.querySelector('.msg-content')?.textContent || '';
  msg.remove();
  prev.remove();
  const input = $('#chat-input');
  if (input) {
    input.value = text;
    sendMessage();
  }
}

/* ── Voice input ────────────────────────────────────────────────── */

function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $('#btn-voice');
  if (!SR) { if (btn) btn.hidden = true; return; }
  if (btn) btn.hidden = false;
  const r = new SR();
  r.continuous = false;
  r.interimResults = true;
  r.lang = navigator.language || 'en-US';

  r.onresult = (e) => {
    let final = '', interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t; else interim += t;
    }
    const input = $('#chat-input');
    if (input) {
      input.value = (state.voiceBase || '') + (final || interim);
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 200) + 'px';
      const send = $('#btn-send'); if (send) send.disabled = false;
    }
    if (final) state.voiceBase = input?.value || '';
  };
  r.onend = () => {
    state.voiceRecording = false;
    btn?.classList.remove('recording');
    state.voiceBase = '';
  };
  r.onerror = (e) => {
    state.voiceRecording = false;
    btn?.classList.remove('recording');
    state.voiceBase = '';
    if (e.error === 'not-allowed') toast('Microphone access denied', 'error');
    else if (e.error !== 'aborted') toast(`Voice: ${e.error}`, 'warn');
  };
  state.recognition = r;

  btn?.addEventListener('click', () => {
    if (state.voiceRecording) {
      r.stop();
    } else {
      const input = $('#chat-input');
      state.voiceBase = input?.value ? input.value + ' ' : '';
      try { r.start(); state.voiceRecording = true; btn.classList.add('recording'); }
      catch (err) { toast('Voice failed: ' + err.message, 'error'); }
    }
  });
}

/* ── Sessions ───────────────────────────────────────────────────── */

async function loadSessions() {
  try {
    const data = await apiFetch('/api/sessions');
    const list = $('#sessions-list');
    if (!list) return;
    if (!data.sessions?.length) {
      list.innerHTML = '<div class="drawer-empty">No sessions yet — start chatting to create one.</div>';
      return;
    }
    list.innerHTML = data.sessions.slice(0, 50).map(s => `
      <div class="session-item ${s.id === state.currentSession ? 'active' : ''}" data-id="${escapeHtml(s.id)}">
        <div class="session-title">${escapeHtml(s.title || 'Untitled')}</div>
        <div class="session-meta">${escapeHtml(s.channel || 'web')} · ${formatRelative(s.updated_at)}</div>
      </div>
    `).join('');
    list.querySelectorAll('.session-item').forEach(el => {
      el.addEventListener('click', () => loadSession(el.dataset.id));
    });
  } catch {}
}

async function loadSession(id) {
  state.currentSession = id;
  try {
    const data = await apiFetch(`/api/sessions/${id}/messages`);
    const container = $('#chat-msgs');
    if (!container) return;
    container.innerHTML = '';
    const messages = data.messages || [];
    if (!messages.length) { showWelcome(); }
    else messages.forEach(m => {
      if (m.role === 'user') appendUserMessage(m.content);
      else {
        const bubble = createAssistantBubble();
        finalizeAssistantBubble(bubble, m.content, null);
      }
    });
    const sess = data.messages?.[0];
    updateTopbarTitle((sess?.content?.slice(0, 60)) || 'Session');
    closeDrawer();
    loadSessions();
  } catch (err) {
    toast('Failed to load session', 'error');
  }
}

function showWelcome() {
  const container = $('#chat-msgs');
  if (!container) return;
  container.innerHTML = `
    <div class="welcome" id="chat-welcome">
      <div class="welcome-logo">N1</div>
      <h1 class="welcome-title">How can I help today?</h1>
      <p class="welcome-sub">Ask me anything. I can research, analyze, write code, run commands, and remember our conversations.</p>
      <div class="welcome-grid">
        <button class="welcome-card" data-prompt="What systems are currently online?">
          <span class="welcome-card-icon">⚡</span>
          <span class="welcome-card-title">Check status</span>
          <span class="welcome-card-desc">Get a snapshot of running services and agents</span>
        </button>
        <button class="welcome-card" data-prompt="Search the knowledge base for recent project documentation">
          <span class="welcome-card-icon">📚</span>
          <span class="welcome-card-title">Search knowledge</span>
          <span class="welcome-card-desc">Find docs and notes in the RAG index</span>
        </button>
        <button class="welcome-card" data-prompt="Write a Python function that fetches JSON from a URL with retries">
          <span class="welcome-card-icon">💻</span>
          <span class="welcome-card-title">Write code</span>
          <span class="welcome-card-desc">Generate scripts in any language</span>
        </button>
        <button class="welcome-card" data-prompt="Analyze the most recent 5 messages and summarize any action items">
          <span class="welcome-card-icon">📊</span>
          <span class="welcome-card-title">Analyze &amp; summarize</span>
          <span class="welcome-card-desc">Find patterns and extract insights</span>
        </button>
      </div>
      <div class="welcome-stats" id="welcome-stats">
        <div class="welcome-stat"><span class="welcome-stat-value" id="ws-sessions">—</span><span class="welcome-stat-label">Sessions</span></div>
        <div class="welcome-stat"><span class="welcome-stat-value" id="ws-messages">—</span><span class="welcome-stat-label">Messages</span></div>
        <div class="welcome-stat"><span class="welcome-stat-value" id="ws-knowledge">—</span><span class="welcome-stat-label">Knowledge</span></div>
        <div class="welcome-stat"><span class="welcome-stat-value" id="ws-rag">—</span><span class="welcome-stat-label">RAG docs</span></div>
        <div class="welcome-stat"><span class="welcome-stat-value" id="ws-uptime">—</span><span class="welcome-stat-label">Uptime</span></div>
      </div>
      <div class="welcome-hint">Tip: type <code>/help</code> for commands, or <code>/status</code> to see what's online.</div>
    </div>
  `;
  $$('.welcome-card').forEach(b => b.addEventListener('click', () => {
    input.value = b.dataset.prompt;
    sendMessage();
  }));
  loadOverview();
}

function newChat() {
  state.currentSession = null;
  const container = $('#chat-msgs');
  if (container) container.innerHTML = '';
  showWelcome();
  updateTopbarTitle('New chat');
  closeDrawer();
}

function updateTopbarTitle(t) {
  const el = $('#topbar-title');
  if (el) el.textContent = t;
}

/* ── Overview / welcome stats ────────────────────────────────────── */

async function loadOverview() {
  try {
    const data = await apiFetch('/api/overview');
    setText('ws-sessions', data.total_sessions);
    setText('ws-messages', data.total_messages);
    setText('ws-knowledge', data.knowledge_count);
    setText('ws-rag', data.rag_docs);
    setText('ws-uptime', data.uptime);
    const prov = $('#stat-providers');
    if (prov) prov.textContent = (data.providers || []).filter(p => p.available).length + ' / ' + (data.providers || []).length;
  } catch {}
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '—';
}

function formatRelative(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff/86400) + 'd ago';
  return d.toLocaleDateString();
}

/* ── Approvals ──────────────────────────────────────────────────── */

function showApproval(msg) {
  state.pendingApproval = msg;
  const bar = $('#approval-bar');
  const text = $('#approval-text');
  if (bar) bar.hidden = false;
  if (text) text.textContent = msg.description || 'Execution requires approval';
}

function respondApproval(approved) {
  if (!state.pendingApproval) return;
  apiFetch('/api/approvals/' + state.pendingApproval.approval_id + '/respond', {
    method: 'POST',
    body: JSON.stringify({ approved }),
  }).then(() => {
    $('#approval-bar').hidden = true;
    state.pendingApproval = null;
  }).catch(() => toast('Failed to respond', 'error'));
}

/* ── Permission mode ────────────────────────────────────────────── */

async function loadPermissionMode() {
  if (!state.currentSession) {
    updateModeBadge();
    return;
  }
  try {
    const data = await apiFetch('/api/permissions/' + state.currentSession);
    state.permissionMode = data.mode;
    updateModeBadge();
  } catch {}
}

async function setPermissionMode(mode) {
  if (!state.currentSession) {
    state.permissionMode = mode;
    updateModeBadge();
    toast(`Mode set to ${mode} for next session`, 'info');
    return;
  }
  try {
    const data = await apiFetch('/api/permissions/' + state.currentSession, {
      method: 'PUT', body: JSON.stringify({ mode }),
    });
    state.permissionMode = data.mode;
    updateModeBadge();
    toast(`Permission mode: ${mode}`, 'success');
  } catch (err) {
    toast('Failed to set mode', 'error');
  }
}

function updateModeBadge() {
  const el = $('#topbar-mode');
  if (!el) return;
  el.dataset.mode = state.permissionMode;
  const label = el.querySelector('.topbar-mode-label');
  if (label) label.textContent = state.permissionMode;
}

/* ── API key modal ──────────────────────────────────────────────── */

function initKeyModal() {
  if (localStorage.getItem('iva_api_key')) return;
  showKeyModal();
}

function showKeyModal() {
  const m = $('#modal-key');
  if (m) m.hidden = false;
  setTimeout(() => $('#modal-key-input')?.focus(), 100);
}

function hideKeyModal() {
  const m = $('#modal-key');
  if (m) m.hidden = true;
}

$('#modal-key-save')?.addEventListener('click', () => {
  const v = $('#modal-key-input')?.value?.trim();
  if (!v) return;
  localStorage.setItem('iva_api_key', v);
  hideKeyModal();
  toast('API key saved', 'success');
  loadOverview();
  loadSessions();
});

$('#modal-key-toggle')?.addEventListener('click', () => {
  const i = $('#modal-key-input');
  if (i) i.type = i.type === 'password' ? 'text' : 'password';
});

/* ── Toasts ─────────────────────────────────────────────────────── */

function toast(msg, type = 'info') {
  const container = $('#toasts');
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

/* ── Theme button ──────────────────────────────────────────────── */

document.addEventListener('click', e => {
  const themeBtn = e.target.closest('[data-action="theme"]');
  if (themeBtn) {
    applyTheme(state.theme === 'dark' ? 'light' : 'dark');
    toast(`Theme: ${state.theme}`, 'info');
  }
  const newBtn = e.target.closest('[data-action="new-chat"]');
  if (newBtn) { e.preventDefault(); newChat(); }
});

/* ── Cross-script bridge (admin.js needs to refresh tabs) ──── */

window.AppSwitchTab = function (tab) {
  if (!tab) return;
  if (window.AdminViews) window.AdminViews.activeTab = tab;
  state.activeAdminTab = tab;
  $$('.admin-tab').forEach(t => t.classList.toggle('active', t.dataset.admin === tab));
  const titles = {
    overview: 'Overview', memory: 'Memory', projects: 'Projects', rag: 'Knowledge',
    agents: 'Agents', approvals: 'Approvals', events: 'Event log',
    soul: 'Soul', costs: 'Costs', settings: 'Settings',
  };
  const t = $('#admin-title');
  if (t) t.textContent = titles[tab] || tab;
  renderActiveAdmin();
};

window.appState = state;
