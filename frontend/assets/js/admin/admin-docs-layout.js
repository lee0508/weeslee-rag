// 관리자 Docs 레이아웃 상호작용을 관리하는 스크립트
(function () {
  const app = document.getElementById('wrAdminDocsApp');
  if (!app) return;

  const TOKEN_KEY = 'admin_token';
  const API_BASE = window.__API_BASE__ || `${window.location.origin}/api`;
  const navLinks = Array.from(app.querySelectorAll('[data-wr-page]'));
  const navControls = Array.from(app.querySelectorAll('.wr-nav-link'));
  const pages = Array.from(app.querySelectorAll('.wr-page'));
  const searchInput = app.querySelector('#wrDocsSearch');
  const onThisPage = app.querySelector('#wrOnThisPage');
  const toast = app.querySelector('#wrDocsToast');

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function headers() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function fetchJson(path) {
    const response = await fetch(`${API_BASE}${path}`, { headers: headers() });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => {
      toast.hidden = true;
    }, 2800);
  }

  function setActivePage(pageName) {
    const fallback = pages[0]?.dataset.wrPagePanel || 'overview';
    const targetName = pageName || fallback;

    pages.forEach(page => {
      page.classList.toggle('wr-is-active', page.dataset.wrPagePanel === targetName);
    });

    navLinks.forEach(link => {
      link.classList.toggle('wr-is-active', link.dataset.wrPage === targetName);
    });

    renderOnThisPage(targetName);
    refreshPageData(targetName);
  }

  function renderOnThisPage(pageName) {
    if (!onThisPage) return;
    const page = app.querySelector(`.wr-page[data-wr-page-panel="${pageName}"]`);
    const headings = page ? Array.from(page.querySelectorAll('[data-wr-anchor]')) : [];

    if (!headings.length) {
      onThisPage.innerHTML = '<span style="color:var(--wr-muted);font-size:12px">표시할 섹션이 없습니다.</span>';
      return;
    }

    onThisPage.innerHTML = headings.map(heading => {
      const id = heading.id;
      return `<a href="#${id}">${escapeHtml(heading.textContent.trim())}</a>`;
    }).join('');
  }

  function filterNav(query) {
    const normalized = query.trim().toLowerCase();
    navControls.forEach(link => {
      const text = link.textContent.toLowerCase();
      link.classList.toggle('wr-is-hidden', Boolean(normalized) && !text.includes(normalized));
    });
  }

  function openLegacy(tabName) {
    const legacy = document.getElementById('legacyAdminTabs');
    if (!legacy) return;
    legacy.hidden = false;
    legacy.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (tabName && typeof window.switchTab === 'function') {
      window.switchTab(tabName);
    }
  }

  function setStatus(id, label, state) {
    const el = app.querySelector(`#${id}`);
    if (!el) return;
    el.textContent = label;
    el.className = `wr-status-badge ${state ? `wr-${state}` : ''}`.trim();
  }

  async function checkApiStatus() {
    const checks = [
      ['wrStorageStatus', 'Storage API', '/knowledge-sources/status'],
      ['wrJobStatus', 'Job API', '/admin/faiss/jobs'],
      ['wrJobPageStatus', 'Job API', '/admin/faiss/jobs'],
      ['wrFaissStatus', 'FAISS API', '/admin/faiss/status'],
      ['wrGraphStatus', 'Graph API', '/graph/summary'],
      ['wrWikiStatus', 'Wiki API', '/wiki/list'],
    ];

    await Promise.all(checks.map(async ([id, label, path]) => {
      try {
        await fetchJson(path);
        setStatus(id, 'Connected', 'ok');
      } catch (_) {
        setStatus(id, 'Not connected', 'warn');
      }
    }));
  }

  function setText(id, value) {
    const el = app.querySelector(`#${id}`);
    if (el) el.textContent = value;
  }

  function refreshWizardSummary() {
    const legacySummary = document.getElementById('wizardResultSummary');
    setText('wrWizardSummary', legacySummary?.textContent?.trim() || '아직 실행 요약이 없습니다.');
  }

  async function refreshLogSummary() {
    try {
      const data = await fetchJson('/admin/query-logs/summary?days=7');
      setText('wrLogSummaryRecent', String(Number(data.total || 0)));
      setText('wrLogSummaryFailures', String((data.recent_failures || []).length));
      setText('wrLogSummaryDuration', `${Math.round(Number(data.avg_duration_ms || 0))}ms`);
    } catch (_) {
      setText('wrLogSummaryRecent', 'Not connected');
      setText('wrLogSummaryFailures', 'Not connected');
      setText('wrLogSummaryDuration', 'Not connected');
    }
  }

  function refreshBenchmarkSummary() {
    try {
      const raw = localStorage.getItem('admin_bm_history');
      const items = raw ? JSON.parse(raw) : [];
      const latest = Array.isArray(items) && items.length ? items[0] : null;
      setText('wrDocsBenchmarkCount', String(Array.isArray(items) ? items.length : 0));
      setText('wrDocsBenchmarkScore', latest ? `${Number(latest.pass_rate || 0).toFixed(1)}%` : 'No data');
      setText('wrDocsBenchmarkSnapshot', latest?.snapshot || 'No data');
    } catch (_) {
      setText('wrDocsBenchmarkCount', 'Unavailable');
      setText('wrDocsBenchmarkScore', 'Unavailable');
      setText('wrDocsBenchmarkSnapshot', 'Unavailable');
    }
  }

  function refreshPageData(pageName) {
    if (pageName === 'rag-build-wizard') refreshWizardSummary();
    if (pageName === 'logs') refreshLogSummary();
    if (pageName === 'search-quality') refreshBenchmarkSummary();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  navLinks.forEach(link => {
    link.addEventListener('click', () => setActivePage(link.dataset.wrPage));
  });

  app.querySelectorAll('[data-wr-legacy-tab]').forEach(button => {
    button.addEventListener('click', () => openLegacy(button.dataset.wrLegacyTab));
  });

  app.querySelector('#wrThemeToggle')?.addEventListener('click', () => {
    console.info('Theme toggle will be implemented later.');
    showToast('Theme toggle will be implemented later.');
  });

  app.querySelector('#wrRefreshStatus')?.addEventListener('click', () => {
    checkApiStatus();
    refreshPageData(app.querySelector('.wr-page.wr-is-active')?.dataset.wrPagePanel || 'overview');
    showToast('API 상태를 다시 확인했습니다.');
  });

  searchInput?.addEventListener('input', event => filterNav(event.target.value));

  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      searchInput?.focus();
    }
  });

  setActivePage('overview');
  checkApiStatus();
  refreshWizardSummary();
  refreshBenchmarkSummary();
})();
