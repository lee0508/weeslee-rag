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

  async function fetchJson(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...headers(), ...(options.headers || {}) },
    });
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

  window.openWrDocsPage = function openWrDocsPage(pageName) {
    const target = app.querySelector(`.wr-page[data-wr-page-panel="${pageName}"]`);
    if (!target) return false;

    const legacy = document.getElementById('legacyAdminTabs');
    if (legacy) legacy.hidden = true;

    setActivePage(pageName);
    app.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return true;
  };

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

  function setHtml(selector, html) {
    const el = app.querySelector(selector);
    if (el) el.innerHTML = html;
  }

  async function refreshSourceDocuments() {
    try {
      const [sources, mountStatus] = await Promise.all([
        fetchJson('/admin/document-sources'),
        fetchJson('/admin/mounts/status').catch(() => ({ sources: [] })),
      ]);

      const sourceList = Array.isArray(sources) ? sources : [];
      const mountList = Array.isArray(mountStatus?.sources) ? mountStatus.sources : [];
      const accessibleCount = mountList.filter(source => {
        const mi = source.mount_path_info;
        const ui = source.source_uri_info;
        return Boolean(mi?.accessible || ui?.accessible);
      }).length;
      const defaultSource = sourceList[0];

      setText('wrSourceCount', String(sourceList.length));
      setText('wrSourceAccessibleCount', String(accessibleCount));
      setText('wrSourceDefaultName', defaultSource?.source_name || 'No source');
      setText('wrSourceCallout', sourceList.length
        ? `등록된 source ${sourceList.length}개 중 접근 가능 source ${accessibleCount}개를 확인했습니다.`
        : '등록된 source가 없습니다. Legacy Document Source에서 먼저 등록하세요.');

      const registryHtml = sourceList.length
        ? sourceList.slice(0, 4).map(source => `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
              <div class="wr-doc-list-meta">client=${escapeHtml(source.client_id || '-')} · type=${escapeHtml(source.source_type || '-')}</div>
              <div class="wr-doc-list-meta">${escapeHtml(source.mount_path || source.source_uri || '-')}</div>
            </div>
          `).join('')
        : '<div class="wr-doc-list-empty">등록된 source가 없습니다.</div>';
      setHtml('#wrSourceRegistryList', registryHtml);

      const mountHtml = mountList.length
        ? mountList.slice(0, 4).map(source => {
            const mi = source.mount_path_info;
            const ui = source.source_uri_info;
            const ok = mi?.accessible || ui?.accessible;
            return `
              <div class="wr-doc-list-item">
                <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
                <div class="wr-doc-list-meta">status=${ok ? 'accessible' : 'inaccessible'} · mount=${escapeHtml(source.mount_path || '-')}</div>
                <div class="wr-doc-list-meta">uri=${escapeHtml(source.source_uri || '-')}</div>
              </div>
            `;
          }).join('')
        : '<div class="wr-doc-list-empty">마운트 상태 데이터가 없습니다.</div>';
      setHtml('#wrSourceMountList', mountHtml);

      const pathInput = app.querySelector('#wrSourceDefaultPath');
      const clientInput = app.querySelector('#wrSourceDefaultClient');
      if (pathInput && defaultSource?.mount_path) pathInput.value = defaultSource.mount_path;
      if (clientInput && defaultSource?.client_id) clientInput.value = defaultSource.client_id;
    } catch (error) {
      setText('wrSourceCount', 'Not connected');
      setText('wrSourceAccessibleCount', 'Not connected');
      setText('wrSourceDefaultName', 'Not connected');
      setText('wrSourceCallout', `Source Documents API 연결 실패: ${error.message}`);
      setHtml('#wrSourceRegistryList', `<div class="wr-doc-list-empty">${escapeHtml(error.message)}</div>`);
      setHtml('#wrSourceChangeList', '<div class="wr-doc-list-empty">새 파일 감지 상태를 읽지 못했습니다.</div>');
      setHtml('#wrSourceMountList', '<div class="wr-doc-list-empty">마운트 상태를 읽지 못했습니다.</div>');
    }
  }

  function refreshWizardSummary() {
    const legacySummary = document.getElementById('wizardResultSummary');
    setText('wrWizardSummary', legacySummary?.textContent?.trim() || '아직 실행 요약이 없습니다.');
    syncWizardStepperState();
  }

  function syncWizardStepperState() {
    const stepper = app.querySelector('#wrWizardStepper');
    if (!stepper) return;

    for (let step = 1; step <= 10; step++) {
      const legacyStep = document.querySelector(`.wizard-step[data-step="${step}"]`);
      const wrStep = stepper.querySelector(`[data-wr-step="${step}"]`);
      const statusEl = stepper.querySelector(`[data-wr-step-status="${step}"]`);
      if (!wrStep) continue;

      wrStep.classList.remove('wr-done', 'wr-running', 'wr-error');

      if (legacyStep) {
        const isDone = legacyStep.classList.contains('done');
        const isActive = legacyStep.classList.contains('active-step');
        const legacyStatus = document.getElementById(`wstatus-${step}`);
        const statusText = legacyStatus?.textContent?.trim() || '-';
        const isError = legacyStatus?.classList.contains('err');

        if (isDone) {
          wrStep.classList.add('wr-done');
          if (statusEl) statusEl.textContent = '완료';
        } else if (isError) {
          wrStep.classList.add('wr-error');
          if (statusEl) statusEl.textContent = '오류';
        } else if (isActive) {
          wrStep.classList.add('wr-running');
          if (statusEl) statusEl.textContent = '실행 중';
        } else {
          if (statusEl) statusEl.textContent = statusText !== '-' ? statusText : '-';
        }
      } else {
        if (statusEl) statusEl.textContent = '-';
      }
    }
  }

  window.syncWizardStepperState = syncWizardStepperState;

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

  async function refreshFaissSummary() {
    try {
      const page = app.querySelector('.wr-page[data-wr-page-panel="faiss-index"]');
      if (!page) return;

      const cards = page.querySelectorAll('.wr-card');
      const activeCard = cards[0];
      const pipelineCard = cards[1];

      if (activeCard && !page.querySelector('#wrFaissActiveList')) {
        const list = document.createElement('div');
        list.className = 'wr-doc-list';
        list.id = 'wrFaissActiveList';
        list.innerHTML = '<div class="wr-doc-list-empty">Active index를 불러오는 중입니다.</div>';
        activeCard.appendChild(list);
      }

      if (pipelineCard && !page.querySelector('#wrFaissJobList')) {
        const button = pipelineCard.querySelector('[data-wr-legacy-tab="faiss"]');
        const list = document.createElement('div');
        list.className = 'wr-doc-list';
        list.id = 'wrFaissJobList';
        list.innerHTML = '<div class="wr-doc-list-empty">Recent jobs를 불러오는 중입니다.</div>';
        pipelineCard.insertBefore(list, button || null);
      }

      const [statusData, jobsData] = await Promise.all([
        fetchJson('/admin/faiss/status'),
        fetchJson('/admin/faiss/jobs').catch(() => ({ jobs: [] })),
      ]);

      const active = statusData?.active || null;
      const stats = statusData?.stats || null;
      const jobs = Array.isArray(jobsData?.jobs) ? jobsData.jobs : [];
      const recentJobs = jobs.slice(0, 4);
      const runningJobs = jobs.filter(job => job.status === 'running').length;

      setText('wrFaissSnapshot', active?.snapshot || 'No active');
      setText('wrFaissChunkCount', String(Number(stats?.chunk_count || 0)));
      setText('wrFaissJobCount', String(jobs.length));
      setText('wrFaissCallout', active?.snapshot
        ? `활성 snapshot ${active.snapshot} 기준으로 최근 job ${jobs.length}건을 확인했습니다.`
        : '아직 활성화된 FAISS snapshot이 없습니다.');

      const activeHtml = active?.snapshot
        ? `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(active.snapshot)}</div>
              <div class="wr-doc-list-meta">provider=${escapeHtml(active.embedding_provider || '-')} | dim=${escapeHtml(active.dim || '-')}</div>
              <div class="wr-doc-list-meta">chunks=${escapeHtml(stats?.chunk_count ?? 0)} | index=${escapeHtml(stats?.index_size_mb ?? 0)}MB</div>
            </div>
          `
        : '<div class="wr-doc-list-empty">활성 snapshot이 없습니다.</div>';
      setHtml('#wrFaissActiveList', activeHtml);

      const jobsHtml = recentJobs.length
        ? recentJobs.map(job => `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(job.snapshot || job.job_id || '-')}</div>
              <div class="wr-doc-list-meta">status=${escapeHtml(job.status || '-')} | progress=${escapeHtml(job.progress ?? 0)}%</div>
              <div class="wr-doc-list-meta">stage=${escapeHtml(job.stage || '-')} | created=${escapeHtml(job.created_at || '-')}</div>
            </div>
          `).join('')
        : '<div class="wr-doc-list-empty">최근 job이 없습니다.</div>';
      setHtml('#wrFaissJobList', jobsHtml);

      if (runningJobs) {
        setText('wrFaissCallout', `실행 중인 FAISS job ${runningJobs}건이 있습니다.`);
      }
    } catch (error) {
      setText('wrFaissSnapshot', 'Not connected');
      setText('wrFaissChunkCount', 'Not connected');
      setText('wrFaissJobCount', 'Not connected');
      setText('wrFaissCallout', `FAISS API 연결 실패: ${error.message}`);
      setHtml('#wrFaissActiveList', `<div class="wr-doc-list-empty">${escapeHtml(error.message)}</div>`);
      setHtml('#wrFaissJobList', '<div class="wr-doc-list-empty">Job 상태를 읽지 못했습니다.</div>');
    }
  }

  async function refreshGraphSummary() {
    try {
      const page = app.querySelector('.wr-page[data-wr-page-panel="json-graph"]');
      if (!page) return;

      const cards = page.querySelectorAll('.wr-card');
      const summaryCard = cards[0];
      const viewCard = cards[1];

      if (summaryCard && !page.querySelector('#wrGraphSummaryList')) {
        const list = document.createElement('div');
        list.className = 'wr-doc-list';
        list.id = 'wrGraphSummaryList';
        list.innerHTML = '<div class="wr-doc-list-empty">Graph summary를 불러오는 중입니다.</div>';
        summaryCard.appendChild(list);
      }

      if (viewCard && !page.querySelector('#wrGraphViewList')) {
        const button = viewCard.querySelector('[data-wr-legacy-tab="graph"]');
        const list = document.createElement('div');
        list.className = 'wr-doc-list';
        list.id = 'wrGraphViewList';
        list.innerHTML = '<div class="wr-doc-list-empty">Graph view 상태를 불러오는 중입니다.</div>';
        viewCard.insertBefore(list, button || null);
      }

      const data = await fetchJson('/graph/summary');
      const hasData = Boolean(data?.has_data);

      setText('wrGraphProjectCount', String(Number(data?.project_count || 0)));
      setText('wrGraphDocumentCount', String(Number(data?.document_count || 0)));
      setText('wrGraphEdgeCount', String(Number(data?.edge_count || 0)));
      setText('wrGraphCallout', hasData
        ? `Graph 데이터가 준비되어 있습니다. 최근 build 시각은 ${data?.built_at || 'unknown'}입니다.`
        : '아직 Graph 데이터가 없습니다. Legacy Graph 또는 build flow에서 먼저 생성해 주세요.');

      const summaryHtml = hasData
        ? `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(data?.source_type || 'graph')}</div>
              <div class="wr-doc-list-meta">projects=${escapeHtml(data?.project_count ?? 0)} | documents=${escapeHtml(data?.document_count ?? 0)}</div>
              <div class="wr-doc-list-meta">edges=${escapeHtml(data?.edge_count ?? 0)} | built_at=${escapeHtml(data?.built_at || '-')}</div>
            </div>
          `
        : '<div class="wr-doc-list-empty">Graph summary 데이터가 없습니다.</div>';
      setHtml('#wrGraphSummaryList', summaryHtml);

      const viewHtml = hasData
        ? `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">Legacy Graph View</div>
              <div class="wr-doc-list-meta">Cytoscape 기반 상세 화면은 기존 graph 탭에서 계속 사용합니다.</div>
              <div class="wr-doc-list-meta">운영 요약은 이 docs 페이지에서 확인하고, 탐색/편집은 legacy로 이동합니다.</div>
            </div>
          `
        : '<div class="wr-doc-list-empty">표시할 Graph view 요약이 없습니다.</div>';
      setHtml('#wrGraphViewList', viewHtml);
    } catch (error) {
      setText('wrGraphProjectCount', 'Not connected');
      setText('wrGraphDocumentCount', 'Not connected');
      setText('wrGraphEdgeCount', 'Not connected');
      setText('wrGraphCallout', `Graph API 연결 실패: ${error.message}`);
      setHtml('#wrGraphSummaryList', `<div class="wr-doc-list-empty">${escapeHtml(error.message)}</div>`);
      setHtml('#wrGraphViewList', '<div class="wr-doc-list-empty">Graph view 상태를 읽지 못했습니다.</div>');
    }
  }

  function refreshPageData(pageName) {
    if (pageName === 'source-documents') renderSourceDocumentsPage();
    if (pageName === 'rag-build-wizard') refreshWizardSummary();
    if (pageName === 'faiss-index') refreshFaissSummary();
    if (pageName === 'json-graph') refreshGraphSummary();
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

  function ensureSourceDocumentsUi() {
    const page = app.querySelector('.wr-page[data-wr-page-panel="source-documents"]');
    if (!page) return {};

    const lead = page.querySelector('.wr-page-lead');
    if (lead) {
      lead.textContent = '등록된 문서 소스와 마운트 상태를 이 화면에서 바로 확인하고, 상세 편집은 Legacy Document Source로 이동합니다.';
    }

    const callouts = page.querySelectorAll('.wr-callout');
    callouts.forEach((callout, index) => {
      if (index > 0) callout.hidden = true;
    });

    const cards = page.querySelectorAll('.wr-card');
    const registryCard = cards[0];
    const mountCard = cards[1];

    if (registryCard && !page.querySelector('#wrSourceRegistryList')) {
      const button = registryCard.querySelector('[data-wr-legacy-tab="docsource"]');
      const list = document.createElement('div');
      list.className = 'wr-doc-list';
      list.id = 'wrSourceRegistryList';
      list.innerHTML = '<div class="wr-doc-list-empty">Source registry를 불러오는 중입니다.</div>';
      registryCard.insertBefore(list, button || null);
    }

    if (registryCard && !page.querySelector('#wrSourceChangeList')) {
      const button = registryCard.querySelector('[data-wr-legacy-tab="docsource"]');
      const actionWrap = document.createElement('div');
      actionWrap.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0';
      actionWrap.innerHTML = `
        <button class="wr-btn wr-primary" id="wrSourceScanNow" type="button">새 파일 확인</button>
        <span class="wr-doc-list-meta" id="wrSourceScanHint">화면 진입 시 10분 간격으로 자동 확인합니다.</span>
      `;
      const list = document.createElement('div');
      list.className = 'wr-doc-list';
      list.id = 'wrSourceChangeList';
      list.innerHTML = '<div class="wr-doc-list-empty">Source Document 변경 상태를 불러오는 중입니다.</div>';
      registryCard.insertBefore(actionWrap, button || null);
      registryCard.insertBefore(list, button || null);
      actionWrap.querySelector('#wrSourceScanNow')?.addEventListener('click', () => renderSourceDocumentsPage(true));
    }

    if (mountCard && !page.querySelector('#wrSourceMountList')) {
      const list = document.createElement('div');
      list.className = 'wr-doc-list';
      list.id = 'wrSourceMountList';
      list.innerHTML = '<div class="wr-doc-list-empty">Mount status를 불러오는 중입니다.</div>';
      mountCard.appendChild(list);
    }

    const sourceSettingsInputs = page.querySelectorAll('.wr-form-grid input');
    const pathInput = page.querySelector('#wrSourceDefaultPath') || sourceSettingsInputs[0] || null;
    const clientInput = page.querySelector('#wrSourceDefaultClient') || sourceSettingsInputs[1] || null;
    if (pathInput && !pathInput.id) pathInput.id = 'wrSourceDefaultPath';
    if (clientInput && !clientInput.id) clientInput.id = 'wrSourceDefaultClient';

    return { pathInput, clientInput };
  }

  const SOURCE_SCAN_THROTTLE_MS = 10 * 60 * 1000;

  function sourceScanKey(sourceId) {
    return `wr_source_scan_checked_at:${sourceId || 'source'}`;
  }

  function shouldAutoScanSource(source, force) {
    if (force) return true;
    if (source?.enabled === false) return false;
    const sourceId = source?.source_id || source?.id;
    const lastAttempt = Number(localStorage.getItem(sourceScanKey(sourceId)) || '0');
    if (Date.now() - lastAttempt < SOURCE_SCAN_THROTTLE_MS) return false;
    if (!source?.last_scanned_at) return true;
    const lastScanTime = Date.parse(source.last_scanned_at);
    return !Number.isFinite(lastScanTime) || Date.now() - lastScanTime > SOURCE_SCAN_THROTTLE_MS;
  }

  async function scanSourceDocumentsIfNeeded(sourceList, force = false) {
    const candidates = sourceList.filter(source => shouldAutoScanSource(source, force));
    if (!candidates.length) return sourceList;

    const hint = app.querySelector('#wrSourceScanHint');
    if (hint) hint.textContent = 'Source Document 변경 여부를 확인하는 중입니다.';

    await Promise.all(candidates.map(async source => {
      const sourceId = source.source_id || source.id;
      try {
        localStorage.setItem(sourceScanKey(sourceId), String(Date.now()));
        await fetchJson(`/admin/document-sources/${encodeURIComponent(sourceId)}/scan`, { method: 'POST' });
      } catch (error) {
        console.warn(`[admin] source scan failed: ${sourceId}`, error);
      }
    }));

    if (hint) hint.textContent = force
      ? '수동 확인이 완료되었습니다.'
      : '자동 확인이 완료되었습니다.';
    const refreshed = await fetchJson('/admin/document-sources');
    return Array.isArray(refreshed) ? refreshed : sourceList;
  }

  function formatScanDate(value) {
    if (!value) return '아직 스캔 없음';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('ko-KR');
  }

  function renderSourceChangeList(sourceList) {
    if (!sourceList.length) {
      return '<div class="wr-doc-list-empty">등록된 source가 없어 새 파일을 확인할 수 없습니다.</div>';
    }

    return sourceList.slice(0, 6).map(source => {
      const sourceId = source.source_id || source.id || '';
      const newCount = Number(source.new_file_count || 0);
      const changedCount = Number(source.changed_file_count || 0);
      const removedCount = Number(source.removed_file_count || 0);
      const needsWork = Boolean(source.needs_rag_build || newCount || changedCount || removedCount);
      const nextAction = source.next_action || 'Source Document 기준 스캔을 먼저 실행하세요.';
      const sampleFiles = [
        ...(source.last_scan_new_files || []),
        ...(source.last_scan_changed_files || []),
        ...(source.last_scan_removed_files || []),
      ].slice(0, 4);

      return `
        <div class="wr-doc-list-item">
          <div class="wr-doc-list-title">${escapeHtml(source.source_name || sourceId || '-')}</div>
          <div class="wr-doc-list-meta">마지막 확인 ${escapeHtml(formatScanDate(source.last_scanned_at))} | 전체 ${escapeHtml(source.last_scan_file_count ?? '-')}개</div>
          <div class="wr-doc-list-meta">새 파일 ${newCount}개 | 변경 ${changedCount}개 | 삭제 ${removedCount}개</div>
          <div class="wr-doc-list-meta">${needsWork ? '작업 필요' : '추가 작업 없음'} | ${escapeHtml(nextAction)}</div>
          ${sampleFiles.length ? `<div class="wr-doc-list-meta">예시 파일 ${sampleFiles.map(escapeHtml).join(' | ')}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  async function renderSourceDocumentsPage(forceScan = false) {
    try {
      const { pathInput, clientInput } = ensureSourceDocumentsUi();
      const [sources, mountStatus] = await Promise.all([
        fetchJson('/admin/document-sources'),
        fetchJson('/admin/mounts/status').catch(() => ({ sources: [] })),
      ]);

      let sourceList = Array.isArray(sources) ? sources : [];
      sourceList = await scanSourceDocumentsIfNeeded(sourceList, forceScan);
      const mountList = Array.isArray(mountStatus?.sources) ? mountStatus.sources : [];
      const accessibleCount = mountList.filter(source => {
        const mi = source.mount_path_info;
        const ui = source.source_uri_info;
        return Boolean(mi?.accessible || ui?.accessible);
      }).length;
      const defaultSource = sourceList[0];

      setText('wrSourceCount', String(sourceList.length));
      setText('wrSourceAccessibleCount', String(accessibleCount));
      setText('wrSourceDefaultName', defaultSource?.source_name || 'No source');
      setText('wrSourceCallout', sourceList.length
        ? `등록된 source ${sourceList.length}개 중 접근 가능한 source ${accessibleCount}개를 확인했습니다. 새 파일 감지 결과를 확인하고 작업 필요 메시지가 있으면 RAG 작업을 진행하세요.`
        : '등록된 source가 없습니다. Legacy Document Source에서 먼저 등록해 주세요.');

      const registryHtml = sourceList.length
        ? sourceList.slice(0, 4).map(source => `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
              <div class="wr-doc-list-meta">client=${escapeHtml(source.client_id || '-')} | type=${escapeHtml(source.source_type || '-')}</div>
              <div class="wr-doc-list-meta">${escapeHtml(source.mount_path || source.source_uri || '-')}</div>
            </div>
          `).join('')
        : '<div class="wr-doc-list-empty">등록된 source가 없습니다.</div>';
      setHtml('#wrSourceRegistryList', registryHtml);
      setHtml('#wrSourceChangeList', renderSourceChangeList(sourceList));

      const mountHtml = mountList.length
        ? mountList.slice(0, 4).map(source => {
            const mi = source.mount_path_info;
            const ui = source.source_uri_info;
            const ok = mi?.accessible || ui?.accessible;
            return `
              <div class="wr-doc-list-item">
                <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
                <div class="wr-doc-list-meta">status=${ok ? 'accessible' : 'inaccessible'} | mount=${escapeHtml(source.mount_path || '-')}</div>
                <div class="wr-doc-list-meta">uri=${escapeHtml(source.source_uri || '-')}</div>
              </div>
            `;
          }).join('')
        : '<div class="wr-doc-list-empty">마운트 상태 데이터가 없습니다.</div>';
      setHtml('#wrSourceMountList', mountHtml);

      if (pathInput && defaultSource?.mount_path) pathInput.value = defaultSource.mount_path;
      if (clientInput && defaultSource?.client_id) clientInput.value = defaultSource.client_id;
    } catch (error) {
      ensureSourceDocumentsUi();
      setText('wrSourceCount', 'Not connected');
      setText('wrSourceAccessibleCount', 'Not connected');
      setText('wrSourceDefaultName', 'Not connected');
      setText('wrSourceCallout', `Source Documents API 연결 실패: ${error.message}`);
      setHtml('#wrSourceRegistryList', `<div class="wr-doc-list-empty">${escapeHtml(error.message)}</div>`);
      setHtml('#wrSourceMountList', '<div class="wr-doc-list-empty">마운트 상태를 읽지 못했습니다.</div>');
    }
  }

  refreshSourceDocuments = async function refreshSourceDocumentsOverride() {
    try {
      const { pathInput, clientInput } = ensureSourceDocumentsUi();
      const [sources, mountStatus] = await Promise.all([
        fetchJson('/admin/document-sources'),
        fetchJson('/admin/mounts/status').catch(() => ({ sources: [] })),
      ]);

      const sourceList = Array.isArray(sources) ? sources : [];
      const mountList = Array.isArray(mountStatus?.sources) ? mountStatus.sources : [];
      const accessibleCount = mountList.filter(source => {
        const mi = source.mount_path_info;
        const ui = source.source_uri_info;
        return Boolean(mi?.accessible || ui?.accessible);
      }).length;
      const defaultSource = sourceList[0];

      setText('wrSourceCount', String(sourceList.length));
      setText('wrSourceAccessibleCount', String(accessibleCount));
      setText('wrSourceDefaultName', defaultSource?.source_name || 'No source');
      setText('wrSourceCallout', sourceList.length
        ? `등록된 source ${sourceList.length}개 중 접근 가능한 source ${accessibleCount}개를 확인했습니다.`
        : '등록된 source가 없습니다. Legacy Document Source에서 먼저 등록해 주세요.');

      const registryHtml = sourceList.length
        ? sourceList.slice(0, 4).map(source => `
            <div class="wr-doc-list-item">
              <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
              <div class="wr-doc-list-meta">client=${escapeHtml(source.client_id || '-')} | type=${escapeHtml(source.source_type || '-')}</div>
              <div class="wr-doc-list-meta">${escapeHtml(source.mount_path || source.source_uri || '-')}</div>
            </div>
          `).join('')
        : '<div class="wr-doc-list-empty">등록된 source가 없습니다.</div>';
      setHtml('#wrSourceRegistryList', registryHtml);

      const mountHtml = mountList.length
        ? mountList.slice(0, 4).map(source => {
            const mi = source.mount_path_info;
            const ui = source.source_uri_info;
            const ok = mi?.accessible || ui?.accessible;
            return `
              <div class="wr-doc-list-item">
                <div class="wr-doc-list-title">${escapeHtml(source.source_name || source.source_id || '-')}</div>
                <div class="wr-doc-list-meta">status=${ok ? 'accessible' : 'inaccessible'} | mount=${escapeHtml(source.mount_path || '-')}</div>
                <div class="wr-doc-list-meta">uri=${escapeHtml(source.source_uri || '-')}</div>
              </div>
            `;
          }).join('')
        : '<div class="wr-doc-list-empty">마운트 상태 데이터가 없습니다.</div>';
      setHtml('#wrSourceMountList', mountHtml);

      if (pathInput && defaultSource?.mount_path) pathInput.value = defaultSource.mount_path;
      if (clientInput && defaultSource?.client_id) clientInput.value = defaultSource.client_id;
    } catch (error) {
      ensureSourceDocumentsUi();
      setText('wrSourceCount', 'Not connected');
      setText('wrSourceAccessibleCount', 'Not connected');
      setText('wrSourceDefaultName', 'Not connected');
      setText('wrSourceCallout', `Source Documents API 연결 실패: ${error.message}`);
      setHtml('#wrSourceRegistryList', `<div class="wr-doc-list-empty">${escapeHtml(error.message)}</div>`);
      setHtml('#wrSourceMountList', '<div class="wr-doc-list-empty">마운트 상태를 읽지 못했습니다.</div>');
    }
  };

  refreshSourceDocuments = renderSourceDocumentsPage;

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
