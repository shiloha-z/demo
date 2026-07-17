'use strict';

// 后端基地址：同源即可（把本目录用 http.server 起在后端同域，或直接访问后端地址）。
// 若前端静态服务与后端不同源，可修改 API_BASE 为后端地址，例如 'http://localhost:8000'。
const API_BASE = 'http://127.0.0.1:8000';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let state = {
  tab: 'users',
  rows: [],          // 当前 tab 的行
  search: '',
  detail: null,      // 当前打开的详情 {kind, id}
  pendingDelete: null, // {kind, id, name}
};

// ── API ─────────────────────────────────────────────────────────────
async function apiGet(path) {
  const res = await fetch(API_BASE + path, { credentials: 'include' });
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(API_BASE + path, { method: 'DELETE', credentials: 'include' });
  if (!res.ok) {
    let msg = `删除失败 (${res.status})`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

// ── 列定义 ──────────────────────────────────────────────────────────
const COLUMNS = {
  users: [
    { key: 'id', label: 'ID' },
    { key: 'username', label: '用户名' },
    { key: 'display_name', label: '昵称' },
    { key: 'project_count', label: '项目数' },
    { key: 'agent_count', label: 'Agent数' },
    { key: 'skill_count', label: '技能数' },
  ],
  projects: [
    { key: 'id', label: 'ID' },
    { key: 'name', label: '名称' },
    { key: 'project_id', label: '规范ID' },
    { key: 'owner_name', label: '拥有者' },
    { key: 'task_count', label: '任务数' },
    { key: 'member_count', label: '成员数' },
  ],
  agents: [
    { key: 'id', label: 'ID' },
    { key: 'name', label: '名称' },
    { key: 'role', label: '角色' },
    { key: 'model', label: '模型' },
    { key: 'status', label: '状态', pill: true },
    { key: 'creator_name', label: '创建者' },
  ],
};

const KIND_LABEL = { users: '账号', projects: '项目', agents: 'Agent' };

// ── 渲染 ─────────────────────────────────────────────────────────────
function renderHead() {
  const cols = COLUMNS[state.tab];
  $('#tableHead').innerHTML =
    '<tr>' + cols.map((c) => `<th>${c.label}</th>`).join('') +
    '<th>操作</th></tr>';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderBody() {
  const cols = COLUMNS[state.tab];
  const body = $('#tableBody');
  const rows = state.rows;
  if (!rows.length) {
    body.innerHTML = '';
    $('#emptyState').classList.add('show');
    return;
  }
  $('#emptyState').classList.remove('show');
  body.innerHTML = rows.map((r) => {
    const tds = cols.map((c) => {
      let val = r[c.key];
      if (c.pill) {
        const cls = String(val).toLowerCase();
        return `<td><span class="pill ${cls}">${escapeHtml(val)}</span></td>`;
      }
      if (c.key === 'project_id' || c.key === 'model') {
        return `<td><span class="mono">${escapeHtml(val)}</span></td>`;
      }
      return `<td>${escapeHtml(val)}</td>`;
    }).join('');
    const idKey = state.tab === 'projects' ? 'project_id' : 'id';
    return `<tr>
      ${tds}
      <td>
        <button class="btn sm" data-act="detail" data-id="${r.id}">详情</button>
        <button class="btn sm danger" data-act="delete" data-id="${r.id}" data-name="${escapeHtml(r.username || r.name)}">删除</button>
      </td>
    </tr>`;
  }).join('');
}

function setCount(tab, n) { $('#count-' + tab).textContent = n; }

function renderSummary() {
  $('#listSummary').textContent =
    `共 ${state.rows.length} 个${KIND_LABEL[state.tab]}` +
    (state.search ? `（筛选「${state.search}」）` : '');
}

// ── 数据加载 ─────────────────────────────────────────────────────────
async function loadTab(tab, search = '') {
  const path = `/api/admin/${tab}?limit=1000` + (search ? `&q=${encodeURIComponent(search)}` : '');
  const data = await apiGet(path);
  state.rows = data.items || [];
  setCount(tab, data.total ?? state.rows.length);
  renderHead();
  renderBody();
  renderSummary();
}

async function loadAllCounts() {
  try {
    const [u, p, a] = await Promise.all([
      apiGet('/api/admin/users?limit=1'),
      apiGet('/api/admin/projects?limit=1'),
      apiGet('/api/admin/agents?limit=1'),
    ]);
    setCount('users', u.total ?? 0);
    setCount('projects', p.total ?? 0);
    setCount('agents', a.total ?? 0);
  } catch (_) { /* 数量仅展示，失败不影响主流程 */ }
}

// ── 详情抽屉 ─────────────────────────────────────────────────────────
async function openDetail(kind, id) {
  state.detail = { kind, id };
  let data;
  try {
    data = await apiGet(`/api/admin/${kind}/${id}`);
  } catch (e) {
    toast(e.message, 'err');
    return;
  }
  $('#drawerTitle').textContent = `${KIND_LABEL[kind]}详情 #${id}`;
  $('#drawerBody').innerHTML = renderDetail(kind, data);
  $('#drawerDelete').dataset.kind = kind;
  $('#drawerDelete').dataset.id = id;
  $('#drawerDelete').dataset.name = data.username || data.name || ('#' + id);
  $('#drawerMask').classList.remove('hidden');
}

function kv(label, value) {
  return `<div class="kv"><div class="k">${label}</div><div class="v">${escapeHtml(value)}</div></div>`;
}

function renderDetail(kind, d) {
  if (kind === 'users') {
    const s = d.stats || {};
    let html = '';
    html += kv('用户名', d.username);
    html += kv('昵称', d.display_name);
    html += kv('邮箱', d.email);
    html += kv('电话', d.phone);
    html += kv('简介', d.bio);
    html += `<div class="section-title">统计</div>`;
    html += kv('拥有项目 / 创建Agent / 技能', `${s.project_count} / ${s.agent_count} / ${s.skill_count}`);
    html += kv('关联任务 / 审查 / 审计', `${s.task_count} / ${s.review_count} / ${s.audit_count}`);
    if (d.owned_projects && d.owned_projects.length) {
      html += `<div class="section-title">拥有的项目</div><ul class="sub-list">` +
        d.owned_projects.map((p) => `<li><span>${escapeHtml(p.name)}</span><span class="mono">#${p.id} · ${escapeHtml(p.project_id)}</span></li>`).join('') +
        `</ul>`;
    }
    if (d.created_agents && d.created_agents.length) {
      html += `<div class="section-title">创建的 Agent</div><ul class="sub-list">` +
        d.created_agents.map((a) => `<li><span>${escapeHtml(a.name)}</span><span class="mono">#${a.id} · ${escapeHtml(a.role)}</span></li>`).join('') +
        `</ul>`;
    }
    return html;
  }
  if (kind === 'projects') {
    let html = '';
    html += kv('名称', d.name);
    html += kv('规范 ID', d.project_id);
    html += kv('拥有者', `${d.owner_name} (#${d.owner_id})`);
    html += kv('工作目录', d.workspace_path);
    html += kv('创建时间', d.created_at);
    html += kv('更新时间', d.updated_at);
    if (d.members && d.members.length) {
      html += `<div class="section-title">成员</div><ul class="sub-list">` +
        d.members.map((m) => `<li><span>用户 #${m.user_id}</span><span class="pill">${escapeHtml(m.role)}</span></li>`).join('') +
        `</ul>`;
    }
    if (d.tasks && d.tasks.length) {
      html += `<div class="section-title">任务（${d.tasks.length}）</div><ul class="sub-list">` +
        d.tasks.map((t) => `<li><span>${escapeHtml(t.title)}</span><span class="pill ${t.status}">${escapeHtml(t.status)}</span></li>`).join('') +
        `</ul>`;
    }
    return html;
  }
  // agents
  let html = '';
  html += kv('名称', d.name);
  html += kv('角色', d.role);
  html += kv('模型', d.model);
  html += kv('运行器', d.runner_type);
  html += kv('状态', d.status);
  html += kv('创建者', `${d.creator_name} (#${d.creator_id})`);
  html += kv('系统提示', d.system_prompt);
  if (d.tasks && d.tasks.length) {
    html += `<div class="section-title">关联任务（${d.tasks.length}）</div><ul class="sub-list">` +
      d.tasks.map((t) => `<li><span>${escapeHtml(t.title)}</span><span class="pill ${t.status}">${escapeHtml(t.status)}</span></li>`).join('') +
      `</ul>`;
  }
  return html;
}

function closeDrawer() {
  $('#drawerMask').classList.add('hidden');
  state.detail = null;
}

// ── 删除确认 ─────────────────────────────────────────────────────────
function askDelete(kind, id, name) {
  state.pendingDelete = { kind, id, name };
  $('#confirmText').textContent =
    `确定要删除${KIND_LABEL[kind]}「${name}」(id=${id}) 及其全部关联数据吗？此操作不可恢复。`;
  $('#confirmMask').classList.remove('hidden');
}

function cancelDelete() {
  $('#confirmMask').classList.add('hidden');
  state.pendingDelete = null;
}

async function confirmDelete() {
  const { kind, id } = state.pendingDelete;
  cancelDelete();
  closeDrawer();
  try {
    const res = await apiDelete(`/api/admin/${kind}/${id}`);
    toast(res.message || '已删除', 'ok');
    await loadTab(state.tab, state.search);
    await loadAllCounts();
  } catch (e) {
    toast(e.message, 'err');
  }
}

// ── toast ─────────────────────────────────────────────────────────────
let toastTimer = null;
function toast(msg, type) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast ' + (type || '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2600);
}

// ── 事件绑定 ─────────────────────────────────────────────────────────
function bindEvents() {
  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.tab = btn.dataset.tab;
      loadTab(state.tab, state.search);
    });
  });

  $('#refreshBtn').addEventListener('click', () => {
    loadTab(state.tab, state.search);
    loadAllCounts();
  });

  let searchTimer = null;
  $('#globalSearch').addEventListener('input', (e) => {
    state.search = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadTab(state.tab, state.search), 250);
  });

  $('#tableBody').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (btn.dataset.act === 'detail') openDetail(state.tab, id);
    else if (btn.dataset.act === 'delete') askDelete(state.tab, id, btn.dataset.name);
  });

  $('#drawerClose').addEventListener('click', closeDrawer);
  $('#drawerMask').addEventListener('click', (e) => { if (e.target.id === 'drawerMask') closeDrawer(); });
  $('#drawerDelete').addEventListener('click', () => {
    const { kind, id, name } = $('#drawerDelete').dataset;
    askDelete(kind, Number(id), name);
  });

  $('#confirmCancel').addEventListener('click', cancelDelete);
  $('#confirmMask').addEventListener('click', (e) => { if (e.target.id === 'confirmMask') cancelDelete(); });
  $('#confirmOk').addEventListener('click', confirmDelete);
}

// ── 后端连通性检测 ─────────────────────────────────────────────────────
async function checkApi() {
  const el = $('#apiStatus');
  try {
    await apiGet('/api/admin/users?limit=1');
    el.textContent = '后端：已连接';
    el.className = 'api-status ok';
  } catch (e) {
    el.textContent = '后端：未连接（' + e.message + '）';
    el.className = 'api-status err';
  }
}

// ── 启动 ─────────────────────────────────────────────────────────────
async function main() {
  bindEvents();
  await checkApi();
  await loadTab('users', '');
  await loadAllCounts();
}

main();
