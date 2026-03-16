const state = {
  user: null,
  authMode: "login",
  dashboard: null,
  profile: null,
  threads: [],
  activeThreadId: "",
  activeThread: null,
  searches: [],
  plans: [],
  artifacts: [],
  audits: [],
  githubSearches: [],
  activeGitHubSearch: null,
  githubLoading: false,
  currentView: "dashboard",
  toastTimer: null,
  toastMessage: "",
  loading: false,
};

const root = document.getElementById("app");

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "string" ? payload : payload.detail || "请求失败";
    throw new Error(detail);
  }
  return payload;
}

function setToast(message) {
  state.toastMessage = message;
  render();
  clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => {
    state.toastMessage = "";
    render();
  }, 2200);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(value) {
  if (!value) return "未知时间";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}

function routeView() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash || "dashboard";
}

function setView(view) {
  state.currentView = view;
  if (window.location.hash !== `#/${view}`) {
    window.location.hash = `#/${view}`;
  }
  render();
}

async function bootstrap() {
  state.currentView = routeView();
  try {
    const me = await api("/api/me");
    state.user = me.user;
    await refreshAll();
  } catch {
    state.user = null;
  }
  render();
}

async function refreshAll() {
  const [dashboard, profile, threads, searches, plans, artifacts, audits] = await Promise.all([
    api("/api/dashboard"),
    api("/api/profile"),
    api("/api/threads"),
    api("/api/searches"),
    api("/api/plans"),
    api("/api/artifacts"),
    api("/api/audits"),
  ]);
  state.dashboard = dashboard;
  state.profile = profile.profile;
  state.threads = threads.items;
  state.searches = searches.items;
  state.plans = plans.items;
  state.artifacts = artifacts.items;
  state.audits = audits.items;
  if (!state.activeThreadId && state.threads[0]) {
    state.activeThreadId = state.threads[0].id;
  }
  if (state.activeThreadId) {
    await loadThread(state.activeThreadId);
  }
}

async function loadThread(threadId) {
  state.activeThreadId = threadId;
  state.activeThread = await api(`/api/threads/${threadId}`);
  render();
}

function authShell() {
  const submitLabel = state.authMode === "login" ? "进入控制台" : "创建账号";
  const footnote =
    state.authMode === "login"
      ? "登录后会自动恢复该账号自己的历史、搜索、学习计划和产物。"
      : "首个注册用户会自动吸收当前本地单用户旧数据。";
  return `
    <div class="auth-shell">
      <section class="hero-panel">
        <div>
          <div class="eyebrow">智能职业规划平台 / 本地部署</div>
          <h1 class="hero-title">AI 求职助手<br/>智能职业规划平台</h1>
          <p class="hero-copy">基于大模型的个性化求职分析与学习路径规划系统。采用 OpenClaw 风格的 Agent 框架设计，本地部署，数据隐私保护。</p>
          <div class="hero-metrics">
            <div class="metric">
              <div class="metric-label">本地身份</div>
              <div class="metric-value">隐私保护</div>
            </div>
            <div class="metric">
              <div class="metric-label">历史记录</div>
              <div class="metric-value">自动恢复</div>
            </div>
            <div class="metric">
              <div class="metric-label">本地存储</div>
              <div class="metric-value">数据安全</div>
            </div>
          </div>
        </div>
        <div class="card">
          <h3 class="card-title">技术特色与核心功能</h3>
          <p class="card-copy"><strong>技术特色：</strong>基于大模型（DeepSeek/Codex）的智能分析 · OpenClaw 风格的 Agent 框架设计 · 本地部署，数据隐私保护</p>
          <p class="card-copy"><strong>核心功能：</strong>智能简历解析与画像构建 · 自主岗位搜索与匹配评分 · GitHub 项目推荐与学习规划 · 仓库审计与代码验证</p>
          <p class="card-copy"><strong>使用场景：</strong>求职者快速匹配适合的职位 · 技能提升发现优质学习项目 · 职业规划制定个性化学习路径</p>
        </div>
      </section>
      <section class="auth-panel">
        <div class="tabs">
          <button class="tab-button ${state.authMode === "login" ? "active" : ""}" data-action="switch-auth" data-mode="login">登录</button>
          <button class="tab-button ${state.authMode === "register" ? "active" : ""}" data-action="switch-auth" data-mode="register">注册</button>
        </div>
        <div>
          <h2 class="panel-title">${state.authMode === "login" ? "欢迎回来" : "创建本地账号"}</h2>
          <p class="panel-copy">${footnote}</p>
        </div>
        <form id="auth-form" class="form-grid">
          <label>Username<input name="username" autocomplete="username" placeholder="例如: alice" /></label>
          <label>Password<input name="password" type="password" autocomplete="${state.authMode === "login" ? "current-password" : "new-password"}" placeholder="至少 8 位" /></label>
          <div class="button-row">
            <button class="primary-button" type="submit">${submitLabel}</button>
          </div>
        </form>
        <p class="auth-footnote">所有数据都保存在本地 SQLite 与用户目录中，不会和其他账号互通。</p>
      </section>
    </div>
    ${toast()}
  `;
}

function appShell() {
  return `
    <div class="app-shell">
      ${sidebar()}
      <div class="content-shell">
        ${page()}
      </div>
    </div>
    ${toast()}
  `;
}

function sidebar() {
  const summary = escapeHtml(state.dashboard?.profile_summary || "尚未建立画像");
  const userName = escapeHtml(state.user?.username || "");
  return `
    <aside class="sidebar">
      <div class="brand-lockup">
        <div class="eyebrow">智能职业规划平台</div>
        <h1 class="brand-title">AI 求职<br/>助手</h1>
        <div class="brand-subtitle">基于大模型的个性化求职分析与学习路径规划系统</div>
      </div>
      <div class="nav-list">
        <div class="nav-group-title">核心功能</div>
        ${navButton("dashboard", "📊 总览", "近期活动与关键指标")}
        ${navButton("assistant", "💬 对话工作台", "AI 助手对话与分析")}
        <div class="nav-group-title">搜索与发现</div>
        ${navButton("searches", "🔍 岗位搜索", "职位发现与匹配")}
        ${navButton("github", "🐙 项目搜索", "GitHub 项目智能推荐")}
        <div class="nav-group-title">个人中心</div>
        ${navButton("profile", "👤 用户画像", "简历解析与技能管理")}
        ${navButton("artifacts", "📦 产物中心", "报告、审计与下载")}
      </div>
      <div class="identity-card">
        <p class="eyebrow">当前用户</p>
        <h3 class="identity-name">${userName}</h3>
        <div class="identity-summary">${summary}</div>
        <div class="toolbar" style="margin-top:14px;">
          <button class="ghost-button" data-action="refresh-all">刷新</button>
          <button class="secondary-button" data-action="logout">退出</button>
        </div>
      </div>
    </aside>
  `;
}

function navButton(view, title, copy) {
  return `
    <button class="nav-button ${state.currentView === view ? "active" : ""}" data-action="nav" data-view="${view}">
      <span class="nav-title">${title}</span>
      <span class="nav-copy">${copy}</span>
    </button>
  `;
}

function page() {
  switch (state.currentView) {
    case "assistant":
      return assistantPage();
    case "searches":
      return searchesPage();
    case "github":
      return githubPage();
    case "profile":
      return profilePage();
    case "artifacts":
      return artifactsPage();
    default:
      return dashboardPage();
  }
}

function dashboardPage() {
  const counts = state.dashboard?.counts || {};
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">总览</p>
          <h2 class="page-title">总览 - 近期活动与关键指标</h2>
          <p class="page-copy">这里汇总当前账号的最近线程、搜索、职位分析、学习计划与文件产物。每个账号只看得到自己的历史。</p>
        </div>
        <div class="toolbar">
          <button class="primary-button" data-action="create-thread">新建会话</button>
          <button class="secondary-button" data-action="nav" data-view="searches">开始搜索</button>
        </div>
      </div>
      <div class="stats-grid">
        ${statsCard("01", "Threads", counts.threads || 0)}
        ${statsCard("02", "Searches", counts.searches || 0)}
        ${statsCard("03", "Jobs", counts.jobs || 0)}
        ${statsCard("04", "Artifacts", counts.artifacts || 0)}
      </div>
      <div class="two-column" style="margin-top:16px;">
        <div class="detail-card">
          <h3 class="detail-title">最近线程</h3>
          <div class="list">${renderThreadList(state.dashboard?.recent_threads || [], true)}</div>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">最近搜索</h3>
          <div class="list">${renderSearchList(state.dashboard?.recent_searches || [])}</div>
        </div>
      </div>
      <div class="two-column" style="margin-top:16px;">
        <div class="detail-card">
          <h3 class="detail-title">最近职位快照</h3>
          <div class="list">${renderJobList(state.dashboard?.recent_jobs || [])}</div>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">最近产物</h3>
          <div class="list">${renderArtifactList(state.dashboard?.recent_artifacts || [])}</div>
        </div>
      </div>
    </section>
  `;
}

function statsCard(index, label, value) {
  return `
    <div class="card stats-card" data-index="${index}">
      <div class="stats-label">${label}</div>
      <div class="stats-value">${value}</div>
    </div>
  `;
}

function assistantPage() {
  const thread = state.activeThread;
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">对话工作台</p>
          <h2 class="page-title">对话工作台 - 与 AI 助手交流分析职位</h2>
          <p class="page-copy">线程级会话隔离、JD 输入、聊天补问和职位分析都在这里完成。用户重进页面后，会自动恢复自己的历史线程。</p>
        </div>
        <div class="toolbar">
          <button class="primary-button" data-action="create-thread">新建线程</button>
          ${thread ? `<button class="ghost-button" data-action="reload-thread">刷新当前线程</button>` : ""}
        </div>
      </div>
      <div class="workspace-grid">
        <div class="detail-card">
          <h3 class="detail-title">线程列表</h3>
          <div class="thread-list">${renderThreadList(state.threads, false)}</div>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">${escapeHtml(thread?.title || "尚未选择线程")}</h3>
          <div class="chat-stream">${renderMessages(thread?.messages || [])}</div>
          <form id="message-form" class="composer" style="margin-top:16px;">
            <label>给助手的消息<textarea name="message" placeholder="例如：帮我分析这个岗位、继续比较、生成学习计划"></textarea></label>
            <label>职位描述 JD<textarea name="jdText" placeholder="可选。粘贴一个或多个职位描述，多个职位用单独一行 --- 分隔"></textarea></label>
            <div class="field-grid">
              <label>岗位名称（可选）<input name="jdTitle" placeholder="无法自动识别时填写" /></label>
              <label>城市（可选）<input name="jdCity" placeholder="例如 上海" /></label>
            </div>
            <div class="button-row">
              <button class="primary-button" type="submit" ${thread ? "" : "disabled"}>发送并分析</button>
            </div>
          </form>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">线程里的职位</h3>
          <div class="list">${renderJobList(thread?.jobs || [])}</div>
        </div>
      </div>
    </section>
  `;
}

function searchesPage() {
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">岗位搜索</p>
          <h2 class="page-title">岗位搜索 - 发现适合你的职位</h2>
          <p class="page-copy">搜索条件、shortlist 和复用出来的职位分析结果都会按用户落到本地。再次登录后可以直接回看。</p>
        </div>
      </div>
      <div class="two-column">
        <div class="detail-card">
          <h3 class="detail-title">发起搜索</h3>
          <form id="search-form" class="form-grid">
            <label>关键词（逗号分隔）<input name="keywords" placeholder="AI Agent 工程师, LLM 应用开发" /></label>
            <label>城市（逗号分隔）<input name="cities" placeholder="上海, 杭州" /></label>
            <div class="field-grid">
              <label>最低薪资 K<input name="salaryMinK" type="number" min="0" /></label>
              <label>最高薪资 K<input name="salaryMaxK" type="number" min="0" /></label>
            </div>
            <div class="field-grid">
              <label>最多返回<input name="maxResults" type="number" min="1" value="10" /></label>
              <label>关联线程
                <select name="threadId">
                  <option value="">不关联</option>
                  ${state.threads.map((thread) => `<option value="${thread.id}">${escapeHtml(thread.title)}</option>`).join("")}
                </select>
              </label>
            </div>
            <label><input name="refresh" type="checkbox" /> 强制刷新公开搜索</label>
            <div class="button-row">
              <button class="primary-button" type="submit">开始搜索</button>
            </div>
          </form>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">搜索历史</h3>
          <div class="list">${renderSearchList(state.searches)}</div>
        </div>
      </div>
    </section>
  `;
}

function profilePage() {
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">用户画像</p>
          <h2 class="page-title">用户画像 - 简历解析与技能管理</h2>
          <p class="page-copy">你可以上传简历让后端重新解析画像，也可以直接编辑结构化画像 JSON。每个账号的画像相互隔离。</p>
        </div>
      </div>
      <div class="two-column">
        <div class="detail-card">
          <h3 class="detail-title">简历解析</h3>
          <form id="resume-form" class="form-grid">
            <label>粘贴简历文本<textarea name="resumeText" placeholder="直接粘贴简历文本，或选择文件上传"></textarea></label>
            <label>上传简历文件<div class="file-input"><input name="resumeFile" type="file" /></div></label>
            <div class="button-row">
              <button class="primary-button" type="submit">解析并更新画像</button>
            </div>
          </form>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">当前画像 JSON</h3>
          <form id="profile-form" class="form-grid">
            <label>Profile JSON<textarea name="profileJson">${escapeHtml(JSON.stringify(state.profile || {}, null, 2))}</textarea></label>
            <div class="button-row">
              <button class="secondary-button" type="submit">保存画像</button>
            </div>
          </form>
        </div>
      </div>
    </section>
  `;
}

function artifactsPage() {
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">产物中心</p>
          <h2 class="page-title">产物中心 - 报告、审计与下载</h2>
          <p class="page-copy">这里按当前用户聚合本地产物。报告和审计都可以直接下载，审计结论也会保留结构化摘要。</p>
        </div>
      </div>
      <div class="two-column">
        <div class="detail-card">
          <h3 class="detail-title">文件产物</h3>
          <div class="list">${renderArtifactList(state.artifacts)}</div>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">仓库审计</h3>
          <div class="list">${renderAuditList(state.audits)}</div>
        </div>
      </div>
    </section>
  `;
}

function githubPage() {
  return `
    <section class="page-panel">
      <div class="page-header">
        <div>
          <p class="eyebrow">项目搜索</p>
          <h2 class="page-title">项目搜索 - 发现优质 GitHub 项目</h2>
          <p class="page-copy">输入你的学习需求，AI 会帮你从 GitHub 上找到最适合的项目，并提供学习建议和仓库审计。</p>
        </div>
      </div>
      <div class="github-workspace">
        <div class="detail-card">
          <h3 class="detail-title">搜索表单</h3>
          <form id="github-search-form" class="form-grid">
            <label>描述你的需求<textarea name="userQuery" placeholder="例如：我想学习 RAG 开发、寻找 AI Agent 框架、学习 LangChain 实战项目" rows="4"></textarea></label>
            <div class="field-grid">
              <label>最低 Star 数
                <select name="minStars">
                  <option value="100">100+</option>
                  <option value="500">500+</option>
                  <option value="1000" selected>1000+</option>
                  <option value="5000">5000+</option>
                </select>
              </label>
              <label>返回数量
                <select name="topN">
                  <option value="3">3 个</option>
                  <option value="5" selected>5 个</option>
                  <option value="10">10 个</option>
                </select>
              </label>
            </div>
            <details class="advanced-options">
              <summary>高级选项</summary>
              <div class="form-grid" style="margin-top:12px;">
                <label><input name="includeAudit" type="checkbox" /> 自动审计第一个项目</label>
                <label><input name="includeSimilar" type="checkbox" checked /> 包含相似项目推荐</label>
              </div>
            </details>
            <div class="button-row">
              <button class="primary-button" type="submit" ${state.githubLoading ? "disabled" : ""}>
                ${state.githubLoading ? "搜索中..." : "搜索项目"}
              </button>
            </div>
          </form>
        </div>
        <div class="detail-card github-results">
          <h3 class="detail-title">搜索结果</h3>
          <div class="list">${renderGitHubResults()}</div>
        </div>
        <div class="detail-card">
          <h3 class="detail-title">搜索历史</h3>
          <div class="list">${renderGitHubHistory()}</div>
        </div>
      </div>
    </section>
  `;
}

function renderGitHubResults() {
  if (state.githubLoading) {
    return `<div class="loading-state">正在搜索 GitHub 项目...</div>`;
  }

  if (!state.activeGitHubSearch) {
    return `<div class="empty-state">输入需求并点击搜索按钮开始查找项目</div>`;
  }

  const search = state.activeGitHubSearch;

  if (search.status === "need_replan") {
    return `
      <div class="replan-prompt">
        <p>未找到满足条件的项目，请选择：</p>
        <div class="button-row" style="margin-top:12px;">
          <button class="secondary-button" data-action="github-replan" data-choice="replan">重新规划搜索</button>
          <button class="secondary-button" data-action="github-replan" data-choice="lower_stars">降低 Star 要求</button>
          <button class="secondary-button" data-action="github-replan" data-choice="use_local">使用本地目录</button>
        </div>
      </div>
    `;
  }

  if (!search.repos || search.repos.length === 0) {
    return `<div class="empty-state">未找到匹配的项目</div>`;
  }

  return search.repos.map(repo => `
    <div class="github-repo-card">
      <div class="item-topline">
        <h4 class="item-title">
          <a href="${escapeHtml(repo.url)}" target="_blank" rel="noreferrer">${escapeHtml(repo.name)}</a>
        </h4>
        <span class="badge badge-gold">⭐ ${repo.stars}</span>
      </div>
      <div class="item-subtitle">
        ${repo.language ? `<span class="badge">${escapeHtml(repo.language)}</span>` : ""}
        ${repo.difficulty ? `<span class="badge">难度: ${escapeHtml(repo.difficulty)}</span>` : ""}
        ${repo.time_estimate ? `<span class="badge">预计: ${escapeHtml(repo.time_estimate)}</span>` : ""}
      </div>
      <p class="repo-description">${escapeHtml(repo.description || "")}</p>
      ${repo.reason ? `<p class="repo-reason"><strong>推荐理由：</strong>${escapeHtml(repo.reason)}</p>` : ""}
      ${repo.fit_score ? `<div class="fit-score">匹配度: ${repo.fit_score}/100</div>` : ""}
      ${repo.community ? `
        <div class="community-stats">
          <span class="badge">Issues: ${repo.community.issues || 0}</span>
          <span class="badge">PRs: ${repo.community.pull_requests || 0}</span>
          <span class="badge">贡献者: ${repo.community.contributors || 0}</span>
          ${repo.community.last_updated ? `<span class="badge">更新: ${escapeHtml(repo.community.last_updated)}</span>` : ""}
        </div>
      ` : ""}
      ${repo.similar_repos && repo.similar_repos.length > 0 ? `
        <div class="similar-repos">
          <strong>相似项目：</strong>
          ${repo.similar_repos.map(similar => `
            <a href="${escapeHtml(similar.url)}" target="_blank" rel="noreferrer" class="similar-link">
              ${escapeHtml(similar.name)} (⭐${similar.stars})
            </a>
          `).join(" · ")}
        </div>
      ` : ""}
      ${repo.audit_summary ? `
        <div class="audit-summary">
          <span class="audit-badge audit-${repo.audit_summary.verdict}">${escapeHtml(repo.audit_summary.verdict)}</span>
          <p>${escapeHtml(repo.audit_summary.summary || "")}</p>
          ${repo.audit_summary.usable_modules && repo.audit_summary.usable_modules.length > 0 ? `
            <p><strong>可用模块：</strong>${repo.audit_summary.usable_modules.map(m => escapeHtml(m)).join(", ")}</p>
          ` : ""}
        </div>
      ` : ""}
      <div class="button-row" style="margin-top:12px;">
        <button class="ghost-button" data-action="audit-repo" data-repo-url="${escapeHtml(repo.url)}">审计仓库</button>
        <button class="secondary-button" data-action="generate-learning-path" data-repo-url="${escapeHtml(repo.url)}">生成学习路径</button>
      </div>
    </div>
  `).join("");
}

function renderGitHubHistory() {
  if (!state.githubSearches || state.githubSearches.length === 0) {
    return `<div class="empty-state">暂无搜索历史</div>`;
  }

  return state.githubSearches.slice(0, 10).map(search => `
    <button class="list-item github-history-item" data-action="load-github-search" data-search-id="${search.search_id}">
      <div class="item-topline">
        <h4 class="item-title">${escapeHtml(search.user_query)}</h4>
        <span class="badge">${search.repos ? search.repos.length : 0} 个</span>
      </div>
      <div class="item-meta">${formatTime(search.created_at)}</div>
    </button>
  `).join("");
}


function renderThreadList(items, compact) {
  if (!items.length) {
    return `<div class="empty-state">暂无线程记录。</div>`;
  }
  return items
    .map(
      (item) => `
        <button class="thread-item ${state.activeThreadId === item.id ? "active" : ""}" data-action="open-thread" data-thread-id="${item.id}">
          <div class="item-topline">
            <h4 class="item-title">${escapeHtml(item.title)}</h4>
            <span class="badge">${compact ? "History" : "Thread"}</span>
          </div>
          <div class="item-meta">${formatTime(item.updated_at)}</div>
        </button>
      `,
    )
    .join("");
}

function renderMessages(messages) {
  if (!messages.length) {
    return `<div class="empty-state">这个线程还没有消息。可以先贴一个 JD 或直接发问。</div>`;
  }
  return messages
    .map(
      (message) => `
        <div class="message ${message.role}">
          <div class="message-role">${message.role === "user" ? "You" : "Assistant"}</div>
          <div class="message-content">${escapeHtml(message.content)}</div>
        </div>
      `,
    )
    .join("");
}

function renderSearchList(items) {
  if (!items.length) {
    return `<div class="empty-state">暂无岗位搜索记录。</div>`;
  }
  return items
    .map((item) => {
      const keywords = (item.query?.keywords || []).join(" / ");
      const status = item.result?.status || "unknown";
      return `
        <div class="list-item">
          <div class="item-topline">
            <h4 class="item-title">${escapeHtml(item.title || keywords || "岗位搜索")}</h4>
            <span class="badge badge-accent">${escapeHtml(status)}</span>
          </div>
          <div class="item-subtitle">${escapeHtml(keywords || "未记录关键词")}</div>
          <div class="badge-row">
            <span class="badge">结果 ${(item.result?.shortlist || item.jobs || []).length}</span>
            <span class="badge">${formatTime(item.updated_at)}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderJobList(items) {
  if (!items.length) {
    return `<div class="empty-state">暂无职位快照。</div>`;
  }
  return items
    .map((job) => {
      const score = Number(job.match?.score || 0);
      return `
        <div class="job-item">
          <div class="item-topline">
            <h4 class="item-title">${escapeHtml(job.title || job.job_id)}</h4>
            <span class="badge ${score >= 80 ? "badge-green" : score >= 60 ? "badge-gold" : "badge-accent"}">匹配 ${score}</span>
          </div>
          <div class="item-subtitle">${escapeHtml(job.company || "未知公司")} · ${escapeHtml(job.city || "未知城市")} · ${escapeHtml(job.salary || "面议")}</div>
          <div class="badge-row">
            ${job.analysis?.job_level ? `<span class="badge">${escapeHtml(job.analysis.job_level)}</span>` : ""}
            ${job.match?.skill_gaps?.length ? `<span class="badge">缺口 ${job.match.skill_gaps.length}</span>` : ""}
            <span class="badge">${formatTime(job.updated_at)}</span>
          </div>
          <div class="button-row" style="margin-top:12px;">
            <button class="ghost-button" data-action="analyze-job" data-job-id="${job.job_id}">重新分析</button>
            <button class="secondary-button" data-action="create-plan" data-job-id="${job.job_id}">生成 3 个月计划</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderArtifactList(items) {
  if (!items.length) {
    return `<div class="empty-state">暂无文件产物。</div>`;
  }
  return items
    .map(
      (item) => `
        <div class="artifact-item">
          <div class="item-topline">
            <h4 class="item-title">${escapeHtml(item.title)}</h4>
            <span class="badge">${escapeHtml(item.kind)}</span>
          </div>
          <div class="item-subtitle">${escapeHtml(item.summary || "—")}</div>
          <div class="button-row" style="margin-top:12px;">
            <a class="ghost-button" href="/api/artifacts/${item.id}/download" target="_blank" rel="noreferrer">下载</a>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderAuditList(items) {
  if (!items.length) {
    return `<div class="empty-state">暂无仓库审计记录。</div>`;
  }
  return items
    .map(
      (item) => `
        <div class="list-item">
          <div class="item-topline">
            <h4 class="item-title">${escapeHtml(item.repo_url)}</h4>
            <span class="badge badge-green">${escapeHtml(item.verdict)}</span>
          </div>
          <div class="item-subtitle">${escapeHtml(item.summary)}</div>
        </div>
      `,
    )
    .join("");
}

function toast() {
  return `<div class="toast ${state.toastMessage ? "visible" : ""}">${escapeHtml(state.toastMessage)}</div>`;
}

function render() {
  root.innerHTML = state.user ? appShell() : authShell();
  bindEvents();
}

function bindEvents() {
  const authForm = document.getElementById("auth-form");
  if (authForm) {
    authForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(authForm);
      try {
        await api(`/api/auth/${state.authMode}`, {
          method: "POST",
          body: JSON.stringify({
            username: String(form.get("username") || ""),
            password: String(form.get("password") || ""),
          }),
        });
        const me = await api("/api/me");
        state.user = me.user;
        await refreshAll();
        setView("dashboard");
        setToast(state.authMode === "login" ? "登录成功" : "账号创建成功");
      } catch (error) {
        setToast(error.message);
      }
    };
  }

  const messageForm = document.getElementById("message-form");
  if (messageForm) {
    messageForm.onsubmit = async (event) => {
      event.preventDefault();
      if (!state.activeThreadId) return;
      const form = new FormData(messageForm);
      try {
        const payload = {
          message: String(form.get("message") || ""),
          jdText: String(form.get("jdText") || ""),
          jdTitle: String(form.get("jdTitle") || ""),
          jdCity: String(form.get("jdCity") || ""),
        };
        await api(`/api/threads/${state.activeThreadId}/messages`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        await refreshAll();
        await loadThread(state.activeThreadId);
        messageForm.reset();
        setToast("消息已提交");
      } catch (error) {
        setToast(error.message);
      }
    };
  }

  const searchForm = document.getElementById("search-form");
  if (searchForm) {
    searchForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(searchForm);
      try {
        await api("/api/searches", {
          method: "POST",
          body: JSON.stringify({
            keywords: String(form.get("keywords") || "")
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            cities: String(form.get("cities") || "")
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            salaryMinK: form.get("salaryMinK") ? Number(form.get("salaryMinK")) : null,
            salaryMaxK: form.get("salaryMaxK") ? Number(form.get("salaryMaxK")) : null,
            maxResults: Number(form.get("maxResults") || 10),
            refresh: Boolean(form.get("refresh")),
            threadId: String(form.get("threadId") || ""),
          }),
        });
        await refreshAll();
        setToast("搜索完成，结果已保存到本地");
      } catch (error) {
        setToast(error.message);
      }
    };
  }

  const profileForm = document.getElementById("profile-form");
  if (profileForm) {
    profileForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(profileForm);
      try {
        await api("/api/profile", {
          method: "PUT",
          body: JSON.stringify({ profile: JSON.parse(String(form.get("profileJson") || "{}")) }),
        });
        await refreshAll();
        setToast("画像已更新");
      } catch (error) {
        setToast(error.message);
      }
    };
  }

  const resumeForm = document.getElementById("resume-form");
  if (resumeForm) {
    resumeForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(resumeForm);
      try {
        await api("/api/profile/resume", {
          method: "POST",
          body: form,
        });
        await refreshAll();
        setToast("简历已解析并更新画像");
      } catch (error) {
        setToast(error.message);
      }
    };
  }

  const githubSearchForm = document.getElementById("github-search-form");
  if (githubSearchForm) {
    githubSearchForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(githubSearchForm);
      try {
        state.githubLoading = true;
        render();
        const result = await api("/api/github/search", {
          method: "POST",
          body: JSON.stringify({
            user_query: String(form.get("userQuery") || ""),
            min_stars: Number(form.get("minStars") || 1000),
            top_n: Number(form.get("topN") || 5),
            include_audit: Boolean(form.get("includeAudit")),
            include_similar: Boolean(form.get("includeSimilar")),
          }),
        });
        state.activeGitHubSearch = result;
        state.githubSearches = await api("/api/github/searches").then(r => r.items || []);
        state.githubLoading = false;
        render();
        setToast("搜索完成");
      } catch (error) {
        state.githubLoading = false;
        render();
        setToast(error.message);
      }
    };
  }

  document.querySelectorAll("[data-action]").forEach((element) => {
    element.addEventListener("click", async (event) => {
      const action = event.currentTarget.dataset.action;
      try {
        if (action === "switch-auth") {
          state.authMode = event.currentTarget.dataset.mode;
          render();
          return;
        }
        if (action === "nav") {
          setView(event.currentTarget.dataset.view);
          return;
        }
        if (action === "logout") {
          await api("/api/auth/logout", { method: "POST" });
          state.user = null;
          state.activeThread = null;
          state.activeThreadId = "";
          setToast("已退出");
          render();
          return;
        }
        if (action === "refresh-all") {
          await refreshAll();
          setToast("数据已刷新");
          return;
        }
        if (action === "create-thread") {
          const created = await api("/api/threads", {
            method: "POST",
            body: JSON.stringify({ title: "新会话" }),
          });
          await refreshAll();
          state.activeThreadId = created.id;
          await loadThread(created.id);
          setView("assistant");
          setToast("已创建新线程");
          return;
        }
        if (action === "open-thread") {
          await loadThread(event.currentTarget.dataset.threadId);
          setView("assistant");
          return;
        }
        if (action === "reload-thread" && state.activeThreadId) {
          await loadThread(state.activeThreadId);
          setToast("线程已刷新");
          return;
        }
        if (action === "analyze-job") {
          await api(`/api/jobs/${event.currentTarget.dataset.jobId}/analyze`, { method: "POST" });
          await refreshAll();
          if (state.activeThreadId) {
            await loadThread(state.activeThreadId);
          }
          setToast("职位已重新分析");
          return;
        }
        if (action === "create-plan") {
          await api(`/api/jobs/${event.currentTarget.dataset.jobId}/plan`, {
            method: "POST",
            body: JSON.stringify({ timeframe: "3months" }),
          });
          await refreshAll();
          setToast("学习计划已生成");
          return;
        }
        if (action === "load-github-search") {
          const searchId = event.currentTarget.dataset.searchId;
          const result = await api(`/api/github/searches/${searchId}`);
          state.activeGitHubSearch = result;
          render();
          return;
        }
        if (action === "github-replan") {
          const choice = event.currentTarget.dataset.choice;
          state.githubLoading = true;
          render();
          const result = await api("/api/github/search", {
            method: "POST",
            body: JSON.stringify({
              user_query: state.activeGitHubSearch.user_query,
              min_stars: state.activeGitHubSearch.min_stars,
              top_n: state.activeGitHubSearch.top_n,
              user_choice: choice,
              retry_context: state.activeGitHubSearch.retry_context,
            }),
          });
          state.activeGitHubSearch = result;
          state.githubSearches = await api("/api/github/searches").then(r => r.items || []);
          state.githubLoading = false;
          render();
          setToast("重新搜索完成");
          return;
        }
        if (action === "audit-repo") {
          const repoUrl = event.currentTarget.dataset.repoUrl;
          const match = repoUrl.match(/github\.com\/([^\/]+)\/([^\/]+)/);
          if (!match) {
            setToast("无效的仓库 URL");
            return;
          }
          const [, owner, repo] = match;
          setToast("正在审计仓库...");
          await api(`/api/github/repos/${owner}/${repo}/audit`, {
            method: "POST",
            body: JSON.stringify({
              expected_capabilities: [],
              allow_light_run: true,
              keep_workspace: false,
            }),
          });
          await refreshAll();
          setToast("审计完成，结果已保存到产物中心");
          return;
        }
        if (action === "generate-learning-path") {
          const repoUrl = event.currentTarget.dataset.repoUrl;
          setToast("学习路径生成功能开发中");
          return;
        }
      } catch (error) {
        setToast(error.message);
      }
    });
  });
}

window.addEventListener("hashchange", () => {
  state.currentView = routeView();
  render();
});

bootstrap();
