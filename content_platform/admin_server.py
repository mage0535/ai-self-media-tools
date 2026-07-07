import json
import secrets
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .admin_data import build_overview, build_platform_detail
from .admin_store import AdminStore


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
    def __init__(self, db_path, password):
        self.db_path = db_path
        self.password = str(password)
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
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --panel: rgba(255,255,255,0.78);
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--font);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(59,130,246,0.16), transparent 30%),
        radial-gradient(circle at top right, rgba(139,92,246,0.12), transparent 24%),
        linear-gradient(180deg, #f7f9fc 0%, #eef3fa 100%);
      min-height: 100vh;
    }}
    .shell {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    .header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 20px;
    }}
    .brand {{ font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }}
    .sub {{ color: var(--muted); font-size: 14px; }}
    .panel {{
      backdrop-filter: blur(24px);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .grid {{ display: grid; gap: 18px; }}
    .overview-grid {{ grid-template-columns: 2fr 1fr; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
    .card {{ padding: 18px; }}
    .kpi {{ font-size: 28px; font-weight: 700; margin: 6px 0; }}
    .muted {{ color: var(--muted); }}
    .table {{ width: 100%; border-collapse: collapse; }}
    .table th, .table td {{ text-align: left; padding: 12px 10px; border-bottom: 1px solid var(--line); font-size: 14px; vertical-align: top; }}
    .table th {{ color: var(--muted); font-weight: 600; }}
    .platform-link {{
      display: block; color: inherit; text-decoration: none; padding: 18px;
      transition: transform .18s ease, background .18s ease;
    }}
    .platform-link:hover {{ transform: translateY(-2px); background: rgba(255,255,255,0.92); }}
    .tag {{
      display: inline-flex; align-items: center; padding: 5px 10px; border-radius: 999px;
      font-size: 12px; background: var(--accent-soft); color: var(--accent);
      margin-right: 6px; margin-bottom: 6px;
    }}
    .status-connected {{ color: var(--success); }}
    .status-pending {{ color: var(--warn); }}
    .status-error {{ color: var(--danger); }}
    .chart {{ min-height: 180px; padding: 18px; }}
    .bars {{ display: flex; align-items: end; gap: 12px; min-height: 150px; }}
    .bar {{ flex: 1; background: linear-gradient(180deg, rgba(10,100,255,.9), rgba(10,100,255,.55)); border-radius: 18px 18px 6px 6px; position: relative; min-width: 42px; }}
    .bar-label {{ font-size: 12px; color: var(--muted); margin-top: 8px; text-align: center; }}
    .bar-value {{ position: absolute; top: -22px; width: 100%; text-align: center; font-size: 12px; color: var(--text); }}
    .split {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 18px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .btn {{
      appearance: none; border: 0; border-radius: 14px; padding: 11px 16px;
      background: linear-gradient(180deg, #0a64ff, #0849bf); color: white;
      font-weight: 600; cursor: pointer;
      box-shadow: 0 10px 24px rgba(10,100,255,.18);
    }}
    .btn.secondary {{ background: white; color: var(--text); border: 1px solid var(--line); box-shadow: none; }}
    .btn.ghost {{ background: transparent; color: var(--accent); border: 1px solid var(--accent-soft); box-shadow: none; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }}
    .field {{ display: flex; flex-direction: column; gap: 6px; }}
    .field label {{ font-size: 13px; color: var(--muted); }}
    .field input, .field textarea, .field select {{
      border: 1px solid var(--line); background: rgba(255,255,255,0.9); border-radius: 14px;
      padding: 11px 12px; font: inherit;
    }}
    .field textarea {{ min-height: 92px; resize: vertical; }}
    .hero {{
      padding: 24px;
      margin-bottom: 18px;
    }}
    .back {{
      display: inline-flex; gap: 8px; align-items: center; color: var(--accent); text-decoration: none; font-weight: 600;
    }}
    .login-wrap {{ max-width: 520px; margin: 80px auto; padding: 30px; }}
    @media (max-width: 980px) {{
      .overview-grid, .split, .form-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div id="app"></div>
  <script>
    const app = document.getElementById("app");
    const state = {{ overview: null, platform: null, route: "overview" }};

    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>\\"]/g, (char) => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}}[char]));
    }}

    async function api(path, options = {{}}) {{
      const response = await fetch(path, {{
        headers: {{ "Content-Type": "application/json" }},
        credentials: "same-origin",
        ...options,
      }});
      if (!response.ok) {{
        const text = await response.text();
        throw new Error(text || `HTTP ${{response.status}}`);
      }}
      return response.json();
    }}

    function renderBars(targetId, rows) {{
      const host = document.getElementById(targetId);
      if (!host) return;
      if (!rows || !rows.length) {{
        host.innerHTML = '<div class="muted">暂无数据</div>';
        return;
      }}
      const max = Math.max(...rows.map(item => item.value), 1);
      host.innerHTML = '<div class="bars">' + rows.map(item => `\n        <div style="flex:1;">\n          <div class="bar" style="height:${{Math.max(18, item.value / max * 130)}}px"><div class="bar-value">${{item.value}}</div></div>\n          <div class="bar-label">${{escapeHtml(item.label)}}</div>\n        </div>`).join('') + '</div>';
    }}

    function latestWorkRows(rows) {{
      return rows.map(row => `\n        <tr>\n          <td><strong>${{escapeHtml(row.title || row.topic)}}</strong><div class="muted">${{escapeHtml(row.topic)}}</div></td>\n          <td>${{escapeHtml(row.job_state)}}</td>\n          <td>${{escapeHtml(row.delivery_status)}}</td>\n          <td>${{row.performance.views}}</td>\n          <td>${{row.performance.likes + row.performance.comments + row.performance.shares}}</td>\n        </tr>`).join('');
    }}

    function bindingRows(rows, platformKey) {{
      return rows.map(row => `\n        <tr>\n          <td><strong>${{escapeHtml(row.display_name)}}</strong><div class="muted">${{escapeHtml(row.account_key)}}</div></td>\n          <td>${{escapeHtml(row.auth_type)}}</td>\n          <td class="status-${{escapeHtml(row.status)}}">${{escapeHtml(row.status)}}</td>\n          <td>${{row.enabled ? "启用" : "停用"}}</td>\n          <td>\n            <div class="actions">\n              <button class="btn secondary" onclick="checkBinding(${{row.id}}, '${{platformKey}}')">检测</button>\n              <button class="btn ghost" onclick="toggleBinding(${{row.id}}, '${{platformKey}}', ${{!row.enabled}})">${{row.enabled ? "停用" : "启用"}}</button>\n            </div>\n          </td>\n        </tr>`).join('');
    }}

    function renderOverview() {{
      const data = state.overview;
      app.innerHTML = `\n        <div class="shell">\n          <div class="header">\n            <div>\n              <div class="brand">AI Self-Media Control Center</div>\n              <div class="sub">Win11 / Edge 风格管理台 · 一次性访问会话</div>\n            </div>\n            <div class="actions"><button class="btn secondary" onclick="logout()">退出登录</button></div>\n          </div>\n          <div class="panel hero">\n            <div class="cards">\n              <div class="card"><div class="muted">平台数</div><div class="kpi">${{data.platforms.length}}</div></div>\n              <div class="card"><div class="muted">待审核任务</div><div class="kpi">${{data.review_queue.length}}</div></div>\n              <div class="card"><div class="muted">最近失败</div><div class="kpi">${{data.recent_failures.length}}</div></div>\n              <div class="card"><div class="muted">最近作品</div><div class="kpi">${{data.latest_works.length}}</div></div>\n            </div>\n          </div>\n          <div class="grid overview-grid">\n            <div class="panel chart"><h3>全平台投递状态</h3><div id="deliveries-chart"></div></div>\n            <div class="panel chart"><h3>全平台绑定数</h3><div id="bindings-chart"></div></div>\n          </div>\n          <div class="grid" style="margin-top:18px;">\n            <div class="panel card">\n              <h3>平台总览</h3>\n              <div class="cards">\n                ${{data.platforms.map(item => `\n                  <a class="panel platform-link" href="#platform/${{item.key}}" onclick="openPlatform('${{item.key}}'); return false;">\n                    <div style="display:flex;justify-content:space-between;align-items:flex-start;">\n                      <div>\n                        <div style="font-size:18px;font-weight:700;">${{escapeHtml(item.label)}}</div>\n                        <div class="muted">${{escapeHtml(item.group)}} · 账号 ${{item.binding_count}} · 已连接 ${{item.connected_count}}</div>\n                      </div>\n                      <div class="tag">${{escapeHtml(item.key)}}</div>\n                    </div>\n                    <div style="margin-top:12px;">${{item.supports.map(tag => `<span class='tag'>${{escapeHtml(tag)}}</span>`).join('')}}</div>\n                    <div style="margin-top:12px;" class="muted">草稿/发布：${{JSON.stringify(item.delivery_counts)}}</div>\n                  </a>`).join('')}}\n              </div>\n            </div>\n            <div class="split">\n              <div class="panel card">\n                <h3>最新 5 个作品</h3>\n                <table class="table"><thead><tr><th>作品</th><th>状态</th><th>投递</th><th>浏览</th><th>互动</th></tr></thead><tbody>${{latestWorkRows(data.latest_works)}}</tbody></table>\n              </div>\n              <div class="panel card">\n                <h3>待审核与异常</h3>\n                <div class="muted" style="margin-bottom:10px;">待审核任务</div>\n                ${{data.review_queue.map(row => `<div class='tag'>${{escapeHtml(row.topic)}} · ${{escapeHtml(row.risk_level || 'review')}}</div>`).join('') || '<div class=\"muted\">暂无</div>'}}\n                <div class="muted" style="margin:16px 0 10px;">最近失败</div>\n                ${{data.recent_failures.map(row => `<div class='tag'>${{escapeHtml(row.title || row.topic)}} · ${{escapeHtml(row.error || 'unknown')}}</div>`).join('') || '<div class=\"muted\">暂无</div>'}}\n              </div>\n            </div>\n          </div>\n        </div>`;\n+      renderBars("deliveries-chart", data.charts.deliveries_by_status);\n+      renderBars("bindings-chart", data.charts.bindings_by_platform);\n+    }}\n+\n+    function renderPlatformDetail() {{\n+      const data = state.platform;\n+      app.innerHTML = `\n+        <div class=\"shell\">\n+          <div class=\"header\">\n+            <div>\n+              <a class=\"back\" href=\"#\" onclick=\"goBack(); return false;\">← 返回首页</a>\n+              <div class=\"brand\" style=\"margin-top:8px;\">${{escapeHtml(data.platform.label)}}</div>\n+              <div class=\"sub\">${{escapeHtml(data.platform.key)}} · 支持 ${{data.platform.supports.join(', ')}}</div>\n+            </div>\n+            <div class=\"actions\"><button class=\"btn secondary\" onclick=\"logout()\">退出登录</button></div>\n+          </div>\n+          <div class=\"cards\" style=\"margin-bottom:18px;\">\n+            <div class=\"panel card\"><div class=\"muted\">绑定账号</div><div class=\"kpi\">${{data.bindings.length}}</div></div>\n+            <div class=\"panel card\"><div class=\"muted\">投递状态</div><div class=\"kpi\">${{Object.values(data.stats.delivery_counts).reduce((a,b)=>a+b,0)}}</div></div>\n+            <div class=\"panel card\"><div class=\"muted\">浏览总量</div><div class=\"kpi\">${{data.stats.performance_totals.views}}</div></div>\n+            <div class=\"panel card\"><div class=\"muted\">互动总量</div><div class=\"kpi\">${{data.stats.performance_totals.likes + data.stats.performance_totals.comments + data.stats.performance_totals.shares}}</div></div>\n+          </div>\n+          <div class=\"split\">\n+            <div class=\"panel chart\"><h3>平台投递状态</h3><div id=\"platform-deliveries-chart\"></div></div>\n+            <div class=\"panel chart\"><h3>最新作品浏览</h3><div id=\"platform-views-chart\"></div></div>\n+          </div>\n+          <div class=\"split\" style=\"margin-top:18px;\">\n+            <div class=\"panel card\">\n+              <h3>账号绑定</h3>\n+              <table class=\"table\"><thead><tr><th>账号</th><th>认证</th><th>状态</th><th>启用</th><th>操作</th></tr></thead><tbody>${{bindingRows(data.bindings, data.platform.key)}}</tbody></table>\n+            </div>\n+            <div class=\"panel card\">\n+              <h3>绑定向导</h3>\n+              <ol>${{data.binding_guide.map(step => `<li style='margin:10px 0;'>${{escapeHtml(step)}}</li>`).join('')}}</ol>\n+              <div class=\"muted\" style=\"margin-top:10px;\">支持认证：${{data.platform.auth_modes.join(', ')}}</div>\n+            </div>\n+          </div>\n+          <div class=\"panel card\" style=\"margin-top:18px;\">\n+            <h3>新增 / 更新账号</h3>\n+            <form id=\"binding-form\" class=\"form-grid\" onsubmit=\"saveBinding(event, '${{data.platform.key}}')\">\n+              <div class=\"field\"><label>账号显示名</label><input name=\"display_name\" required /></div>\n+              <div class=\"field\"><label>账号唯一键</label><input name=\"account_key\" required /></div>\n+              <div class=\"field\"><label>认证方式</label><select name=\"auth_type\">${{data.platform.auth_modes.map(mode => `<option value='${{escapeHtml(mode)}}'>${{escapeHtml(mode)}}</option>`).join('')}}</select></div>\n+              <div class=\"field\"><label>状态</label><select name=\"status\"><option value=\"pending\">pending</option><option value=\"connected\">connected</option><option value=\"error\">error</option></select></div>\n+              <div class=\"field\"><label>凭据引用</label><input name=\"credentials_ref\" placeholder=\"例如环境变量名或文件位置\" /></div>\n+              <div class=\"field\"><label>是否启用</label><select name=\"enabled\"><option value=\"true\">启用</option><option value=\"false\">停用</option></select></div>\n+              <div class=\"field\" style=\"grid-column:1/-1;\"><label>备注</label><textarea name=\"notes\"></textarea></div>\n+              <div><button class=\"btn\" type=\"submit\">保存账号</button></div>\n+            </form>\n+          </div>\n+          <div class=\"panel card\" style=\"margin-top:18px;\">\n+            <h3>最新 5 个作品</h3>\n+            <table class=\"table\"><thead><tr><th>作品</th><th>状态</th><th>投递</th><th>浏览</th><th>互动</th></tr></thead><tbody>${{latestWorkRows(data.latest_works)}}</tbody></table>\n+          </div>\n+        </div>`;\n+      renderBars("platform-deliveries-chart", data.charts.deliveries_by_status);\n+      renderBars("platform-views-chart", data.charts.latest_views);\n+    }}\n+\n+    async function loadOverview() {{\n+      state.overview = await api('/api/overview');\n+      state.route = 'overview';\n+      renderOverview();\n+    }}\n+\n+    async function openPlatform(platform) {{\n+      state.platform = await api(`/api/platforms/${{platform}}`);\n+      state.route = `platform/${{platform}}`;\n+      renderPlatformDetail();\n+    }}\n+\n+    function goBack() {{ loadOverview(); }}\n+\n+    async function saveBinding(event, platform) {{\n+      event.preventDefault();\n+      const form = new FormData(event.target);\n+      const payload = Object.fromEntries(form.entries());\n+      payload.enabled = payload.enabled === 'true';\n+      await api(`/api/platforms/${{platform}}/bindings`, {{ method: 'POST', body: JSON.stringify(payload) }});\n+      await openPlatform(platform);\n+    }}\n+\n+    async function checkBinding(bindingId, platform) {{\n+      await api(`/api/platforms/${{platform}}/bindings/${{bindingId}}/check`, {{ method: 'POST', body: JSON.stringify({{}}) }});\n+      await openPlatform(platform);\n+    }}\n+\n+    async function toggleBinding(bindingId, platform, enabled) {{\n+      await api(`/api/platforms/${{platform}}/bindings/${{bindingId}}/toggle`, {{ method: 'POST', body: JSON.stringify({{ enabled }}) }});\n+      await openPlatform(platform);\n+    }}\n+\n+    async function logout() {{\n+      await api('/api/auth/logout', {{ method: 'POST', body: JSON.stringify({{}}) }});\n+      window.location.reload();\n+    }}\n+\n+    async function boot() {{\n+      try {{\n+        await loadOverview();\n+      }} catch (error) {{\n+        const query = new URLSearchParams(window.location.search);\n+        const launch = query.get('launch') || '';\n+        app.innerHTML = `\n+          <div class=\"shell\">\n+            <div class=\"panel login-wrap\">\n+              <div class=\"brand\">AI Self-Media Control Center</div>\n+              <div class=\"sub\" style=\"margin:10px 0 20px;\">一次性访问链接 + 密码登录，浏览器关闭后会话失效。</div>\n+              <form id=\"login-form\">\n+                <div class=\"field\"><label>访问密码</label><input name=\"password\" type=\"password\" required /></div>\n+                <div style=\"margin-top:18px;\"><button class=\"btn\" type=\"submit\">登录</button></div>\n+              </form>\n+              <div id=\"login-error\" class=\"muted\" style=\"margin-top:12px;color:var(--danger);\"></div>\n+            </div>\n+          </div>`;\n+        document.getElementById('login-form').addEventListener('submit', async (event) => {{\n+          event.preventDefault();\n+          const password = new FormData(event.target).get('password');\n+          try {{\n+            await api(`/api/auth/login?launch=${{encodeURIComponent(launch)}}`, {{ method: 'POST', body: JSON.stringify({{ password }}) }});\n+            history.replaceState(null, '', window.location.pathname);\n+            await loadOverview();\n+          }} catch (err) {{\n+            document.getElementById('login-error').textContent = '登录失败：' + err.message;\n+          }}\n+        }});\n+      }}\n+    }}\n+\n+    boot();\n+  </script>\n+</body>\n+</html>"""


def make_admin_server(db_path, password, host="127.0.0.1", port=0):
    state = AdminState(db_path, password)

    class Handler(BaseHTTPRequestHandler):
        def _session_ok(self):
            session_id = _extract_cookie(self.headers, "cp_admin_session")
            return state.valid_session(session_id)

        def _body_json(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if route == "/":
                if self._session_ok() or query.get("launch", [""])[0] == state.launch_token:
                    return _html_response(self, _page_shell("AI Self-Media Control Center"))
                return _html_response(self, "<h1>Invalid or expired link</h1>", status=HTTPStatus.FORBIDDEN)
            if route == "/api/overview":
                if not self._session_ok():
                    return _json_response(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return _json_response(self, build_overview(state.db_path))
            if route.startswith("/api/platforms/"):
                if not self._session_ok():
                    return _json_response(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                platform = route.split("/")[3]
                return _json_response(self, build_platform_detail(state.db_path, platform))
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
                return _json_response(
                    self,
                    {"ok": True, "launch": "consumed"},
                    headers={"Set-Cookie": f"cp_admin_session={session_id}; Path=/; HttpOnly; SameSite=Lax"},
                )
            if route == "/api/auth/logout":
                return _json_response(self, {"ok": True}, headers={"Set-Cookie": "cp_admin_session=; Path=/; Max-Age=0"})
            if not self._session_ok():
                return _json_response(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            if route.endswith("/bindings"):
                platform = route.split("/")[3]
                binding = state.admin_store.upsert_binding(platform, self._body_json())
                return _json_response(self, binding)
            if route.endswith("/check"):
                parts = route.strip("/").split("/")
                platform = parts[2]
                binding_id = parts[4]
                binding = state.admin_store.get_binding(binding_id)
                status = "connected" if binding.get("credentials_ref") else "pending"
                checked = state.admin_store.mark_binding_check(binding_id, status, "" if status == "connected" else "missing credentials reference")
                return _json_response(self, checked)
            if route.endswith("/toggle"):
                parts = route.strip("/").split("/")
                platform = parts[2]
                binding_id = parts[4]
                payload = self._body_json()
                toggled = state.admin_store.toggle_binding(binding_id, bool(payload.get("enabled", True)))
                return _json_response(self, toggled)
            return _json_response(self, {"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.db_path = db_path
    server.launch_url = f"http://{host}:{server.server_port}/?launch={state.launch_token}"
    server.admin_state = state
    return server
