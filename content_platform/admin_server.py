import json
import secrets
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .admin_data import build_overview, build_platform_detail, build_task_center, build_task_detail
from .admin_store import AdminStore
from .platform_checks import evaluate_platform_binding


def _json_response(handler, payload, status=200, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler, html, status=200):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class AdminState:
    def __init__(self, db_path, password, config=None):
        self.db_path = db_path
        self.password = str(password)
        self.config = config or {}
        self.admin_store = AdminStore(db_path)
        self.admin_store.init()
        self.launch_token = secrets.token_urlsafe(24)
        self.launch_consumed = False
        self.sessions = {}

    def create_session(self):
        session_id = secrets.token_urlsafe(24)
        self.sessions[session_id] = {"active": True}
        return session_id

    def valid_session(self, session_id):
        return bool(session_id and session_id in self.sessions)


def _extract_cookie(headers, name):
    cookie = headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part.split("=", 1)[1]
    return ""


def _page_shell(title):
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --panel: rgba(255,255,255,0.84);
      --text: #111827;
      --muted: #64748b;
      --line: rgba(15,23,42,0.08);
      --accent: #0a64ff;
      --accent-soft: rgba(10,100,255,0.12);
      --success: #0f9d58;
      --warn: #d97706;
      --danger: #dc2626;
      --shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
      --radius: 22px;
      --font: "Segoe UI", "Segoe UI Variable", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(59,130,246,0.16), transparent 30%),
        radial-gradient(circle at top right, rgba(139,92,246,0.12), transparent 24%),
        linear-gradient(180deg, #f7f9fc 0%, #eef3fa 100%);
      min-height: 100vh;
    }
    .shell { max-width: 1460px; margin: 0 auto; padding: 24px; }
    .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; }
    .brand { font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }
    .sub { color: var(--muted); font-size: 14px; }
    .panel {
      backdrop-filter: blur(24px);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .grid { display:grid; gap:18px; }
    .cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:14px; }
    .card { padding:18px; }
    .kpi { font-size:28px; font-weight:700; margin:6px 0; }
    .muted { color: var(--muted); }
    .table { width:100%; border-collapse: collapse; }
    .table th, .table td { text-align:left; padding:12px 10px; border-bottom:1px solid var(--line); font-size:14px; vertical-align: top; }
    .table th { color: var(--muted); font-weight: 600; }
    .platform-link {
      display:block; color:inherit; text-decoration:none; padding:18px;
      transition: transform .18s ease, background .18s ease;
    }
    .platform-link:hover { transform: translateY(-2px); background: rgba(255,255,255,0.92); }
    .tag {
      display:inline-flex; align-items:center; padding:5px 10px; border-radius:999px;
      font-size:12px; background: var(--accent-soft); color: var(--accent);
      margin-right:6px; margin-bottom:6px;
    }
    .chart { min-height:180px; padding:18px; }
    .bars { display:flex; align-items:end; gap:12px; min-height:150px; }
    .bar { flex:1; background: linear-gradient(180deg, rgba(10,100,255,.9), rgba(10,100,255,.55)); border-radius:18px 18px 6px 6px; position:relative; min-width:42px; }
    .bar-label { font-size:12px; color:var(--muted); margin-top:8px; text-align:center; }
    .bar-value { position:absolute; top:-22px; width:100%; text-align:center; font-size:12px; color:var(--text); }
    .split { display:grid; grid-template-columns: 1.2fr 1fr; gap:18px; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; }
    .btn {
      appearance:none; border:0; border-radius:14px; padding:11px 16px;
      background: linear-gradient(180deg, #0a64ff, #0849bf); color:white;
      font-weight:600; cursor:pointer;
      box-shadow: 0 10px 24px rgba(10,100,255,.18);
    }
    .btn.secondary { background:white; color:var(--text); border:1px solid var(--line); box-shadow:none; }
    .btn.ghost { background:transparent; color:var(--accent); border:1px solid var(--accent-soft); box-shadow:none; }
    .form-grid { display:grid; grid-template-columns: repeat(2, 1fr); gap:14px; }
    .field { display:flex; flex-direction:column; gap:6px; }
    .field label { font-size:13px; color:var(--muted); }
    .field input, .field textarea, .field select {
      border:1px solid var(--line); background: rgba(255,255,255,0.9); border-radius:14px;
      padding:11px 12px; font:inherit;
    }
    .field textarea { min-height: 92px; resize: vertical; }
    .back { display:inline-flex; gap:8px; align-items:center; color:var(--accent); text-decoration:none; font-weight:600; }
    .login-wrap { max-width:520px; margin:80px auto; padding:30px; }
    pre.diff {
      white-space: pre-wrap;
      font-size: 12px;
      line-height: 1.55;
      background: rgba(15,23,42,0.04);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      overflow: auto;
    }
    @media (max-width: 980px) {
      .split, .form-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="app"></div>
  <script>
    const app = document.getElementById("app");
    const state = { overview: null, tasks: null, platform: null, taskDetail: null, route: "overview" };

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;" }[char]));
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        ...options,
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
      }
      return response.json();
    }

    function renderBars(targetId, rows) {
      const host = document.getElementById(targetId);
      if (!host) return;
      if (!rows || !rows.length) {
        host.innerHTML = '<div class="muted">暂无数据</div>';
        return;
      }
      const max = Math.max(...rows.map(item => item.value), 1);
      host.innerHTML = '<div class="bars">' + rows.map(item => `
        <div style="flex:1;">
          <div class="bar" style="height:${Math.max(18, item.value / max * 130)}px"><div class="bar-value">${item.value}</div></div>
          <div class="bar-label">${escapeHtml(item.label)}</div>
        </div>`).join('') + '</div>';
    }

    function latestWorkRows(rows) {
      return rows.map(row => `
        <tr>
          <td><strong>${escapeHtml(row.title || row.topic)}</strong><div class="muted">${escapeHtml(row.topic)}</div></td>
          <td>${escapeHtml(row.job_state || row.state)}</td>
          <td>${escapeHtml(row.delivery_status || "")}</td>
          <td>${row.performance ? row.performance.views : 0}</td>
          <td>${row.engagement ?? 0}</td>
        </tr>`).join('');
    }

    function taskRows(rows) {
      return rows.map(row => `
        <tr>
          <td><strong>${escapeHtml(row.title || row.topic)}</strong><div class="muted">${escapeHtml(row.id)}</div></td>
          <td>${escapeHtml(row.state)}</td>
          <td>${escapeHtml(row.risk_level || "")}</td>
          <td>${escapeHtml((row.platforms || []).join(", "))}</td>
          <td>
            <div class="actions">
              <button class="btn secondary" onclick="openTask('${row.id}')">详情</button>
              <button class="btn ghost" onclick="taskAction('${row.id}','run',{force:true})">重跑</button>
              <button class="btn ghost" onclick="taskAction('${row.id}','publish')">发布</button>
            </div>
          </td>
        </tr>`).join('');
    }

    function bindingRows(rows, platformKey) {
      return rows.map(row => `
        <tr>
          <td>
            <strong>${escapeHtml(row.display_name)}</strong>
            <div class="muted">${escapeHtml(row.account_key)}${row.track ? ' · ' + escapeHtml(row.track) : ''}</div>
            <div class="muted">${row.current_status ? '现状：' + escapeHtml(row.current_status) : ''}</div>
          </td>
          <td>${escapeHtml(row.auth_type)}</td>
          <td>${escapeHtml(row.status)}</td>
          <td>${row.enabled ? "启用" : "停用"}</td>
          <td>
            <div class="actions">
              <button class="btn secondary" onclick="checkBinding(${row.id}, '${platformKey}')">检测</button>
              <button class="btn ghost" onclick="toggleBinding(${row.id}, '${platformKey}', ${!row.enabled})">${row.enabled ? "停用" : "启用"}</button>
            </div>
          </td>
        </tr>`).join('');
    }

    function renderOverview() {
      const data = state.overview;
      const tasks = state.tasks || { tasks: [], summary: {} };
      app.innerHTML = `
        <div class="shell">
          <div class="header">
            <div>
              <div class="brand">AI Self-Media Control Center</div>
              <div class="sub">Win11 / Edge 风格管理台 · 一次性访问会话</div>
            </div>
            <div class="actions"><button class="btn secondary" onclick="logout()">退出登录</button></div>
          </div>
          <div class="panel card">
            <div class="cards">
              <div><div class="muted">平台数</div><div class="kpi">${data.platforms.length}</div></div>
              <div><div class="muted">待审核任务</div><div class="kpi">${data.review_queue.length}</div></div>
              <div><div class="muted">最近失败</div><div class="kpi">${data.recent_failures.length}</div></div>
              <div><div class="muted">任务总数</div><div class="kpi">${(tasks.tasks || []).length}</div></div>
            </div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel chart"><h3>全平台投递状态</h3><div id="deliveries-chart"></div></div>
            <div class="panel chart"><h3>全平台绑定数</h3><div id="bindings-chart"></div></div>
          </div>
          <div class="panel card" style="margin-top:18px;">
            <h3>平台总览</h3>
            <div class="cards">
              ${data.platforms.map(item => `
                <a class="panel platform-link" href="#" onclick="openPlatform('${item.key}'); return false;">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div style="font-size:18px;font-weight:700;">${escapeHtml(item.label)}</div>
                      <div class="muted">${escapeHtml(item.group)} · 账号 ${item.binding_count} · 已连接 ${item.connected_count}</div>
                    </div>
                    <div class="tag">${escapeHtml(item.key)}</div>
                  </div>
                  <div style="margin-top:12px;">${item.supports.map(tag => `<span class='tag'>${escapeHtml(tag)}</span>`).join('')}</div>
                  <div style="margin-top:12px;" class="muted">草稿/发布：${JSON.stringify(item.delivery_counts)}</div>
                  <div style="margin-top:12px;">${(item.account_summaries || []).map(row => `<span class='tag'>${escapeHtml(row.display_name)}${row.track ? ' · ' + escapeHtml(row.track) : ''}${row.current_status ? ' · ' + escapeHtml(row.current_status) : ''}</span>`).join('') || '<span class="tag">暂无账号摘要</span>'}</div>
                </a>`).join('')}
            </div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel card">
              <h3>任务中心</h3>
              <div style="margin-bottom:10px;">${Object.entries(tasks.summary || {}).map(([k,v]) => `<span class='tag'>${escapeHtml(k)}: ${v}</span>`).join('') || '<span class="tag">暂无任务</span>'}</div>
              <table class="table"><thead><tr><th>任务</th><th>状态</th><th>风险</th><th>平台</th><th>操作</th></tr></thead><tbody>${taskRows(tasks.tasks || [])}</tbody></table>
            </div>
            <div class="panel card">
              <h3>最新 5 个作品</h3>
              <table class="table"><thead><tr><th>作品</th><th>状态</th><th>投递</th><th>浏览</th><th>互动</th></tr></thead><tbody>${latestWorkRows(data.latest_works)}</tbody></table>
            </div>
          </div>
        </div>`;
      renderBars("deliveries-chart", data.charts.deliveries_by_status);
      renderBars("bindings-chart", data.charts.bindings_by_platform);
    }

    function renderPlatformDetail() {
      const data = state.platform;
      app.innerHTML = `
        <div class="shell">
          <div class="header">
            <div>
              <a class="back" href="#" onclick="goBack(); return false;">← 返回首页</a>
              <div class="brand" style="margin-top:8px;">${escapeHtml(data.platform.label)}</div>
              <div class="sub">${escapeHtml(data.platform.key)} · 支持 ${data.platform.supports.join(', ')}</div>
            </div>
            <div class="actions"><button class="btn secondary" onclick="logout()">退出登录</button></div>
          </div>
          <div class="cards">
            <div class="panel card"><div class="muted">绑定账号</div><div class="kpi">${data.bindings.length}</div></div>
            <div class="panel card"><div class="muted">投递状态</div><div class="kpi">${Object.values(data.stats.delivery_counts).reduce((a,b)=>a+b,0)}</div></div>
            <div class="panel card"><div class="muted">浏览总量</div><div class="kpi">${data.stats.performance_totals.views}</div></div>
            <div class="panel card"><div class="muted">互动总量</div><div class="kpi">${data.stats.performance_totals.likes + data.stats.performance_totals.comments + data.stats.performance_totals.shares}</div></div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel chart"><h3>平台投递状态</h3><div id="platform-deliveries-chart"></div></div>
            <div class="panel chart"><h3>最新作品浏览</h3><div id="platform-views-chart"></div></div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel card">
              <h3>账号绑定</h3>
              <table class="table"><thead><tr><th>账号</th><th>认证</th><th>状态</th><th>启用</th><th>操作</th></tr></thead><tbody>${bindingRows(data.bindings, data.platform.key)}</tbody></table>
            </div>
            <div class="panel card">
              <h3>绑定向导</h3>
              <ol>${data.binding_guide.map(step => `<li style='margin:10px 0;'>${escapeHtml(step)}</li>`).join('')}</ol>
              <div class="muted" style="margin-top:10px;">支持认证：${data.platform.auth_modes.join(', ')}</div>
            </div>
          </div>
          <div class="panel card" style="margin-top:18px;">
            <h3>新增 / 更新账号</h3>
            <form id="binding-form" class="form-grid" onsubmit="saveBinding(event, '${data.platform.key}')">
              <div class="field"><label>账号显示名</label><input name="display_name" required /></div>
              <div class="field"><label>账号唯一键</label><input name="account_key" required /></div>
              <div class="field"><label>赛道</label><input name="track" /></div>
              <div class="field"><label>现状</label><input name="current_status" /></div>
              <div class="field"><label>认证方式</label><select name="auth_type">${data.platform.auth_modes.map(mode => `<option value='${escapeHtml(mode)}'>${escapeHtml(mode)}</option>`).join('')}</select></div>
              <div class="field"><label>状态</label><select name="status"><option value="pending">pending</option><option value="connected">connected</option><option value="error">error</option></select></div>
              <div class="field"><label>凭据引用</label><input name="credentials_ref" /></div>
              <div class="field"><label>是否启用</label><select name="enabled"><option value="true">启用</option><option value="false">停用</option></select></div>
              <div class="field" style="grid-column:1/-1;"><label>备注</label><textarea name="notes"></textarea></div>
              <div><button class="btn" type="submit">保存账号</button></div>
            </form>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel card">
              <h3>账号分析</h3>
              ${(data.account_analysis || []).map(row => `<div style='padding:12px 0;border-bottom:1px solid var(--line);'><strong>${escapeHtml(row.display_name)}</strong><div class='muted'>${escapeHtml(row.account_key)}${row.track ? ' · 赛道：' + escapeHtml(row.track) : ''}${row.current_status ? ' · 现状：' + escapeHtml(row.current_status) : ''}</div><div class='muted'>${escapeHtml(row.diagnosis)}</div></div>`).join('') || '<div class="muted">暂无账号分析</div>'}
            </div>
            <div class="panel card">
              <h3>LLM 详细建议</h3>
              <div style='font-weight:600;margin-bottom:10px;'>${escapeHtml((data.llm_analysis || {}).summary || '暂无建议')}</div>
              <div>${((data.llm_analysis || {}).recommendations || []).map(row => `<div class='tag'>${escapeHtml(row)}</div>`).join('') || '<div class="muted">暂无建议</div>'}</div>
              <div class='muted' style='margin-top:10px;'>provider: ${escapeHtml((data.llm_analysis || {}).provider || 'unknown')}</div>
            </div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel chart"><h3>账号赛道分布</h3><div id="platform-tracks-chart"></div></div>
            <div class="panel chart"><h3>账号现状分布</h3><div id="platform-statuses-chart"></div></div>
          </div>
          <div class="panel card" style="margin-top:18px;">
            <h3>最近 5 个作品</h3>
            <table class="table"><thead><tr><th>作品</th><th>状态</th><th>投递</th><th>浏览</th><th>互动</th></tr></thead><tbody>${latestWorkRows(data.latest_works)}</tbody></table>
          </div>
        </div>`;
      renderBars("platform-deliveries-chart", data.charts.deliveries_by_status);
      renderBars("platform-views-chart", data.charts.latest_views);
      renderBars("platform-tracks-chart", data.charts.tracks || []);
      renderBars("platform-statuses-chart", data.charts.current_statuses || []);
    }

    function renderTaskDetail() {
      const data = state.taskDetail;
      app.innerHTML = `
        <div class="shell">
          <div class="header">
            <div>
              <a class="back" href="#" onclick="goBack(); return false;">← 返回首页</a>
              <div class="brand" style="margin-top:8px;">${escapeHtml(data.job.title || data.job.topic)}</div>
              <div class="sub">${escapeHtml(data.job.id)} · ${escapeHtml(data.job.state)} · ${escapeHtml((data.job.platforms || []).join(', '))}</div>
            </div>
            <div class="actions">
              <button class="btn secondary" onclick="taskAction('${data.job.id}','run',{force:true})">重跑</button>
              <button class="btn ghost" onclick="taskAction('${data.job.id}','approve',{actor:'admin',note:'admin approve'})">批准</button>
              <button class="btn ghost" onclick="taskAction('${data.job.id}','reject',{actor:'admin',note:'admin reject'})">驳回</button>
              <button class="btn" onclick="taskAction('${data.job.id}','publish')">发布</button>
            </div>
          </div>
          <div class="split">
            <div class="panel card">
              <h3>当前草稿</h3>
              <div class="muted" style="margin-bottom:12px;">${escapeHtml(data.job.title || '')}</div>
              <pre class="diff">${escapeHtml(data.job.body || '')}</pre>
            </div>
            <div class="panel card">
              <h3>平台草稿详情</h3>
              ${Object.entries(data.platform_payloads || {}).map(([platform, payload]) => `<div style='padding:12px 0;border-bottom:1px solid var(--line);'><strong>${escapeHtml(platform)}</strong><pre class='diff'>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></div>`).join('') || '<div class="muted">暂无平台草稿</div>'}
            </div>
          </div>
          <div class="split" style="margin-top:18px;">
            <div class="panel card">
              <h3>草稿版本历史</h3>
              ${(data.draft_versions || []).map((row, idx) => `<div style='padding:12px 0;border-bottom:1px solid var(--line);'><strong>版本 ${idx + 1}</strong><div class='muted'>${escapeHtml(row.created_at)} · ${escapeHtml(row.risk_level)}</div><div class='muted'>${escapeHtml((row.draft_meta || {}).hook || '')}</div></div>`).join('') || '<div class="muted">暂无版本历史</div>'}
            </div>
            <div class="panel card">
              <h3>草稿差异对比</h3>
              <pre class="diff">${escapeHtml((data.comparisons || []).join('\\n') || '暂无差异')}</pre>
            </div>
          </div>
          <div class="panel card" style="margin-top:18px;">
            <h3>Artifacts / Deliveries</h3>
            <div class="split">
              <div>
                <div class="muted" style="margin-bottom:8px;">Artifacts</div>
                ${(data.artifacts || []).map(row => `<div class='tag'>${escapeHtml(row.kind)} · ${escapeHtml(row.path)}</div>`).join('') || '<div class="muted">暂无</div>'}
              </div>
              <div>
                <div class="muted" style="margin-bottom:8px;">Deliveries</div>
                ${(data.deliveries || []).map(row => `<div class='tag'>${escapeHtml(row.platform)} · ${escapeHtml(row.status)}</div>`).join('') || '<div class="muted">暂无</div>'}
              </div>
            </div>
          </div>
        </div>`;
    }

    async function loadOverview() {
      state.overview = await api('/api/overview');
      state.tasks = await api('/api/tasks');
      state.route = 'overview';
      renderOverview();
    }

    async function openPlatform(platform) {
      state.platform = await api(`/api/platforms/${platform}`);
      state.route = `platform/${platform}`;
      renderPlatformDetail();
    }

    async function openTask(jobId) {
      state.taskDetail = await api(`/api/tasks/${jobId}`);
      state.route = `task/${jobId}`;
      renderTaskDetail();
    }

    function goBack() { loadOverview(); }

    async function saveBinding(event, platform) {
      event.preventDefault();
      const form = new FormData(event.target);
      const payload = Object.fromEntries(form.entries());
      payload.enabled = payload.enabled === 'true';
      await api(`/api/platforms/${platform}/bindings`, { method: 'POST', body: JSON.stringify(payload) });
      await openPlatform(platform);
    }

    async function checkBinding(bindingId, platform) {
      await api(`/api/platforms/${platform}/bindings/${bindingId}/check`, { method: 'POST', body: JSON.stringify({}) });
      await openPlatform(platform);
    }

    async function toggleBinding(bindingId, platform, enabled) {
      await api(`/api/platforms/${platform}/bindings/${bindingId}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) });
      await openPlatform(platform);
    }

    async function taskAction(jobId, action, payload = {}) {
      await api(`/api/tasks/${jobId}/${action}`, { method: 'POST', body: JSON.stringify(payload) });
      if (state.route.startsWith('task/')) {
        await openTask(jobId);
      } else {
        await loadOverview();
      }
    }

    async function logout() {
      await api('/api/auth/logout', { method: 'POST', body: JSON.stringify({}) });
      window.location.reload();
    }

    async function boot() {
      try {
        await loadOverview();
      } catch (error) {
        const query = new URLSearchParams(window.location.search);
        const launch = query.get('launch') || '';
        app.innerHTML = `
          <div class="shell">
            <div class="panel login-wrap">
              <div class="brand">AI Self-Media Control Center</div>
              <div class="sub" style="margin:10px 0 20px;">一次性访问链接 + 密码登录，浏览器关闭后会话失效。</div>
              <form id="login-form">
                <div class="field"><label>访问密码</label><input name="password" type="password" required /></div>
                <div style="margin-top:18px;"><button class="btn" type="submit">登录</button></div>
              </form>
              <div id="login-error" class="muted" style="margin-top:12px;color:var(--danger);"></div>
            </div>
          </div>`;
        document.getElementById('login-form').addEventListener('submit', async (event) => {
          event.preventDefault();
          const password = new FormData(event.target).get('password');
          try {
            await api(`/api/auth/login?launch=${encodeURIComponent(launch)}`, { method: 'POST', body: JSON.stringify({ password }) });
            history.replaceState(null, '', window.location.pathname);
            await loadOverview();
          } catch (err) {
            document.getElementById('login-error').textContent = '登录失败：' + err.message;
          }
        });
      }
    }

    boot();
  </script>
</body>
</html>"""
    return html.replace("__TITLE__", str(title))


def make_admin_server(db_path, password, host="127.0.0.1", port=0, config=None):
    state = AdminState(db_path, password, config=config)

    class Handler(BaseHTTPRequestHandler):
        def _session_ok(self):
            session_id = _extract_cookie(self.headers, "cp_admin_session")
            return state.valid_session(session_id)

        def _body_json(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8")) if raw else {}

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if route == "/":
                if self._session_ok() or query.get("launch", [""])[0] == state.launch_token:
                    return _html_response(self, _page_shell("AI Self-Media Control Center"))
                return _html_response(self, "<h1>Invalid or expired link</h1>", status=HTTPStatus.FORBIDDEN)
            if not self._session_ok():
                return _json_response(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            if route == "/api/overview":
                return _json_response(self, build_overview(state.db_path))
            if route == "/api/tasks":
                return _json_response(self, build_task_center(state.db_path))
            if route.startswith("/api/tasks/"):
                job_id = route.strip("/").split("/")[2]
                return _json_response(self, build_task_detail(state.db_path, job_id))
            if route.startswith("/api/platforms/"):
                platform = route.split("/")[3]
                return _json_response(self, build_platform_detail(state.db_path, platform, state.config))
            return _json_response(self, {"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if route == "/api/auth/login":
                launch = query.get("launch", [""])[0]
                payload = self._body_json()
                if launch != state.launch_token or state.launch_consumed:
                    return _json_response(self, {"ok": False, "error": "launch token expired"}, status=HTTPStatus.FORBIDDEN)
                if str(payload.get("password", "")) != state.password:
                    return _json_response(self, {"ok": False, "error": "invalid password"}, status=HTTPStatus.FORBIDDEN)
                state.launch_consumed = True
                session_id = state.create_session()
                return _json_response(self, {"ok": True, "launch": "consumed"}, headers={"Set-Cookie": f"cp_admin_session={session_id}; Path=/; HttpOnly; SameSite=Lax"})
            if route == "/api/auth/logout":
                return _json_response(self, {"ok": True}, headers={"Set-Cookie": "cp_admin_session=; Path=/; Max-Age=0"})
            if not self._session_ok():
                return _json_response(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)

            if route.startswith("/api/tasks/") and route.endswith("/run"):
                from .pipeline import Pipeline
                from .store import Store

                payload = self._body_json()
                job_id = route.strip("/").split("/")[2]
                result = Pipeline(Store(state.db_path), state.config).run(job_id, bool(payload.get("force", False)))
                return _json_response(self, result)
            if route.startswith("/api/tasks/") and route.endswith("/approve"):
                from .pipeline import Pipeline
                from .store import Store

                payload = self._body_json()
                job_id = route.strip("/").split("/")[2]
                result = Pipeline(Store(state.db_path), state.config).approve(job_id, payload.get("actor", "admin"), payload.get("note", ""))
                return _json_response(self, result)
            if route.startswith("/api/tasks/") and route.endswith("/reject"):
                from .pipeline import Pipeline
                from .store import Store

                payload = self._body_json()
                job_id = route.strip("/").split("/")[2]
                result = Pipeline(Store(state.db_path), state.config).reject(job_id, payload.get("actor", "admin"), payload.get("note", ""))
                return _json_response(self, result)
            if route.startswith("/api/tasks/") and route.endswith("/publish"):
                from .pipeline import Pipeline
                from .store import Store

                job_id = route.strip("/").split("/")[2]
                result = Pipeline(Store(state.db_path), state.config).publish(job_id)
                return _json_response(self, result)
            if route.endswith("/bindings"):
                platform = route.split("/")[3]
                binding = state.admin_store.upsert_binding(platform, self._body_json())
                return _json_response(self, binding)
            if route.endswith("/check"):
                parts = route.strip("/").split("/")
                platform = parts[2]
                binding_id = parts[4]
                binding = state.admin_store.get_binding(binding_id)
                readiness = build_platform_detail(state.db_path, platform, state.config).get("readiness", {})
                result = evaluate_platform_binding(platform, binding, readiness)
                checked = state.admin_store.mark_binding_check(binding_id, result["status"], result["error"])
                return _json_response(self, checked)
            if route.endswith("/toggle"):
                binding_id = route.strip("/").split("/")[4]
                payload = self._body_json()
                toggled = state.admin_store.toggle_binding(binding_id, bool(payload.get("enabled", True)))
                return _json_response(self, toggled)
            if route == "/api/schedules":
                from .scheduler import schedule_job
                from .store import Store
                payload = self._body_json()
                result = schedule_job(Store(state.db_path), **payload)
                return _json_response(self, result)
            return _json_response(self, {"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.db_path = db_path
    server.launch_url = f"http://{host}:{server.server_port}/?launch={state.launch_token}"
    server.admin_state = state
    return server
