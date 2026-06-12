(function () {
  'use strict';

  const DATASET_STATUS_ENDPOINT = '/admin/dataset/status-summary';
  const FAISS_STATUS_ENDPOINT = '/admin/faiss/status';
  const STEP4_STATUS_ENDPOINT = '/admin/dataset-builder/step4/status';
  const STEP4_STATS_ENDPOINT = '/admin/dataset-builder/step4/stats';
  const STEP5_STATUS_ENDPOINT = '/admin/dataset-builder/step5/status';
  const SOURCE_STATUS_ENDPOINT = '/admin/rag-source/status';
  const SOURCE_FILES_ENDPOINT = '/admin/rag-source/files?limit=10';
  const METADATA_STATS_ENDPOINT = '/admin/metadata-review/stats';
  const METADATA_DOCS_ENDPOINT = '/admin/metadata-review/documents?limit=10';
  const FAISS_INDEXES_ENDPOINT = '/admin/faiss/indexes';
  const FAISS_JOBS_ENDPOINT = '/admin/faiss/jobs';
  const FAISS_STAGED_ENDPOINT = '/admin/faiss/staged-summary';
  const GRAPH_STATUS_ENDPOINT = '/graph/status';
  const GRAPH_STATS_ENDPOINT = '/graph/statistics';
  const STEP8_STATUS_ENDPOINT = '/admin/dataset-builder/step8/status';
  const STEP9_STATUS_ENDPOINT = '/admin/dataset-builder/step9/status';
  const WIKI_STATS_ENDPOINT = '/wiki/stats';
  const LLM_SETTINGS_ENDPOINT = '/admin/llm-settings';

  let apiClient;
  let adminConsole;
  let lastDatasetStatus = null;
  let lastFaissStatus = null;
  let lastOcrGateStatus = null;

  function getEl(id) {
    return document.getElementById(id);
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === '') return '-';
    if (typeof value === 'number') return value.toLocaleString('ko-KR');
    return String(value);
  }

  function setText(id, value) {
    const el = getEl(id);
    if (el) el.textContent = value;
  }

  function renderLiveKpis(datasetStatus, faissStatus) {
    const kpiRow = getEl('kpiRow');
    if (!kpiRow || !datasetStatus) return;

    const active = faissStatus?.active || {};
    const stats = faissStatus?.stats || {};
    const serverConfig = faissStatus?.server_config || {};
    const activeSnapshot = datasetStatus.step10_active_snapshot || active.snapshot || serverConfig.active_snapshot || '-';
    const vectorCount = datasetStatus.step7_total_vectors || stats.chunk_count || 0;

    kpiRow.innerHTML = [
      ['Source Documents', formatNumber(datasetStatus.total_documents), `Scan 완료 ${formatNumber(datasetStatus.step1_completed)} / 실패 ${formatNumber(datasetStatus.step1_failed)}`, 'bi-folder2-open'],
      ['Metadata Review', formatNumber(datasetStatus.step3_review_required), `승인 ${formatNumber(datasetStatus.step3_reviewed)} / 반려 ${formatNumber(datasetStatus.step3_rejected)}`, 'bi-ui-checks-grid'],
      ['FAISS Vectors', formatNumber(vectorCount), `Index ${stats.index_exists ? 'exists' : 'not found'}`, 'bi-hdd-network'],
      ['Active Snapshot', activeSnapshot, `Graph ${formatNumber(datasetStatus.step8_nodes_created)} nodes / Wiki ${formatNumber(datasetStatus.step9_wiki_count)}`, 'bi-broadcast']
    ].map(([label, value, note, icon]) => `
      <div class="col-12 col-sm-6 col-xl-3">
        <div class="wr-card-flat p-3 h-100">
          <div class="d-flex justify-content-between gap-2">
            <div class="small fw-bold wr-muted">${label}</div>
            <i class="bi ${icon} text-success"></i>
          </div>
          <div class="wr-kpi-value mt-2">${value}</div>
          <div class="small wr-muted mt-1">${note}</div>
        </div>
      </div>
    `).join('');
  }

  function renderKpiCards(items) {
    const kpiRow = getEl('kpiRow');
    if (!kpiRow) return;

    kpiRow.innerHTML = items.map(([label, value, note, icon, tone]) => `
      <div class="col-12 col-sm-6 col-xl-3">
        <div class="wr-card-flat p-3 h-100">
          <div class="d-flex justify-content-between gap-2">
            <div class="small fw-bold wr-muted">${label}</div>
            <i class="bi ${icon || 'bi-info-circle'} text-${tone || 'success'}"></i>
          </div>
          <div class="wr-kpi-value mt-2">${formatNumber(value)}</div>
          <div class="small wr-muted mt-1">${note || ''}</div>
        </div>
      </div>
    `).join('');
  }

  function renderApiRows(rows) {
    const apiRows = getEl('apiRows');
    if (!apiRows) return;

    apiRows.innerHTML = rows.map((row) => {
      const tone = row.ok ? 'success' : 'danger';
      return `
        <tr>
          <td><span class="badge text-bg-light border wr-api-code">${row.method}</span></td>
          <td class="wr-api-code">${row.endpoint}</td>
          <td><span class="badge text-bg-${tone}">${row.label}</span></td>
        </tr>
      `;
    }).join('');
  }

  function apiRow(method, endpoint, result) {
    return {
      method,
      endpoint: `${apiClient.baseUrl}${endpoint}`,
      ok: result.ok,
      label: result.ok ? `${result.status} OK` : errorLabel(result.error)
    };
  }

  function setPanelBadge(text, tone) {
    const badge = getEl('panelBadge');
    if (!badge) return;
    badge.className = `badge rounded-pill text-bg-${tone || 'info'} px-3 py-2`;
    badge.textContent = text;
  }

  function setStep3ProgressState(reviewRequired) {
    const stepControl = document.querySelector('[data-action="show-step3-status"], [data-step-complete="03"]');
    if (!stepControl) return;

    if (Number(reviewRequired || 0) > 0) {
      if (stepControl.matches('[data-action="show-step3-status"]')) {
        stepControl.className = 'btn btn-sm btn-warning fw-bold';
        stepControl.disabled = false;
        stepControl.textContent = '진행 필요';
        stepControl.setAttribute('aria-label', `Step 3 Metadata Review 검수 대기 ${formatNumber(reviewRequired)}건`);
      }
      return;
    }

    if (stepControl.matches('[data-step-complete="03"]')) return;

    const completeBadge = document.createElement('span');
    completeBadge.className = 'badge text-bg-success';
    completeBadge.dataset.stepComplete = '03';
    completeBadge.textContent = '완료';
    stepControl.replaceWith(completeBadge);
  }

  function renderInfoCards(cards) {
    const panelBody = getEl('panelBody');
    if (!panelBody) return;

    panelBody.innerHTML = `
      <div class="row g-3">
        ${cards.map(([title, text, icon, tone]) => `
          <div class="col-12 col-lg-4">
            <div class="wr-card-flat p-3 h-100">
              <div class="d-flex justify-content-between gap-2">
                <h3 class="h6 fw-bold mb-2">${title}</h3>
                <i class="bi ${icon || 'bi-info-circle'} text-${tone || 'success'}"></i>
              </div>
              <p class="small wr-muted mb-0">${text}</p>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderLiveTable(headers, rows, emptyMessage) {
    const tableRows = rows && rows.length ? rows.map((row) => `
      <tr>
        ${row.map((cell, index) => `<td class="${index === 0 ? 'fw-semibold' : 'wr-muted'}">${cell ?? '-'}</td>`).join('')}
      </tr>
    `).join('') : `
      <tr>
        <td colspan="${headers.length}" class="text-center wr-muted py-3">${emptyMessage || '표시할 데이터가 없습니다.'}</td>
      </tr>
    `;

    return `
      <div class="table-responsive border rounded mt-3">
        <table class="table table-sm table-hover align-middle mb-0 wr-table">
          <thead class="table-light">
            <tr>${headers.map((header) => `<th>${header}</th>`).join('')}</tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    `;
  }

  function replacePanelBodyWithCardsAndTable(cards, headers, rows, emptyMessage) {
    const panelBody = getEl('panelBody');
    if (!panelBody) return;

    panelBody.innerHTML = `
      <div class="row g-3">
        ${cards.map(([title, text, icon, tone]) => `
          <div class="col-12 col-lg-4">
            <div class="wr-card-flat p-3 h-100">
              <div class="d-flex justify-content-between gap-2">
                <h3 class="h6 fw-bold mb-2">${title}</h3>
                <i class="bi ${icon || 'bi-info-circle'} text-${tone || 'success'}"></i>
              </div>
              <p class="small wr-muted mb-0">${text}</p>
            </div>
          </div>
        `).join('')}
      </div>
      ${renderLiveTable(headers, rows, emptyMessage)}
    `;
  }

  function pct(done, total) {
    const totalValue = Number(total || 0);
    if (!totalValue) return 0;
    return Math.max(0, Math.min(100, Math.round((Number(done || 0) / totalValue) * 100)));
  }

  function badgeClass(el, tone) {
    if (!el) return;
    el.className = `badge rounded-pill text-bg-${tone}`;
  }

  function renderOcrGateMetrics(step4Status, step4Stats, step5Status) {
    const badge = getEl('ocrGateBadge');
    const metrics = getEl('ocrGateMetrics');
    const breakdown = getEl('ocrGateBreakdown');
    const rate = getEl('ocrGateRate');
    const progress = getEl('ocrGateProgress');

    if (!metrics || !breakdown) return;

    const total = Number(step4Status?.total || step4Stats?.total || 0);
    const completed = Number(step4Status?.completed || step4Stats?.done || 0);
    const failed = Number(step4Status?.failed || step4Stats?.failed || 0);
    const pending = Number(step4Status?.pending || step4Stats?.pending || 0);
    const chunkReady = Number(step5Status?.total_documents || total || 0) - Number(step5Status?.not_chunked || 0);
    const totalChars = Number(step4Stats?.total_chars || 0);
    const doneRate = pct(completed, total);

    const gatePass = total > 0 && completed === total && failed === 0 && pending === 0;
    if (badge) {
      badge.textContent = gatePass ? 'Step 5 진입 가능' : '품질 확인 필요';
      badgeClass(badge, gatePass ? 'success' : 'warning');
    }

    if (rate) rate.textContent = total ? `${doneRate}% (${formatNumber(completed)} / ${formatNumber(total)})` : '-';
    if (progress) progress.style.width = `${doneRate}%`;

    metrics.innerHTML = [
      ['Step 4 Done', formatNumber(completed), `대상 ${formatNumber(total)}건`, 'bi-file-earmark-check', 'success'],
      ['Failed', formatNumber(failed), failed ? '재처리 필요' : '실패 없음', 'bi-exclamation-triangle', failed ? 'danger' : 'success'],
      ['Chunk Ready', formatNumber(chunkReady), `미청킹 ${formatNumber(step5Status?.not_chunked || 0)}건`, 'bi-text-paragraph', 'primary'],
      ['Total Chars', formatNumber(totalChars), '추출 텍스트 합계', 'bi-body-text', 'success']
    ].map(([label, value, note, icon, tone]) => `
      <div class="wr-quality-metric">
        <div class="d-flex justify-content-between gap-2">
          <div class="wr-quality-label">${label}</div>
          <i class="bi ${icon} text-${tone}"></i>
        </div>
        <div class="wr-quality-value">${value}</div>
        <div class="wr-quality-note">${note}</div>
      </div>
    `).join('');

    const byFileType = step4Status?.by_file_type || {};
    const rows = Object.entries(byFileType).map(([fileType, item]) => `
      <tr>
        <td class="fw-semibold">${fileType || 'unknown'}</td>
        <td><span class="badge text-bg-success">${formatNumber(item.completed || 0)}</span></td>
        <td><span class="badge text-bg-${item.failed ? 'danger' : 'light'} border">${formatNumber(item.failed || 0)}</span></td>
        <td><span class="badge text-bg-${item.pending ? 'warning' : 'light'} border">${formatNumber(item.pending || 0)}</span></td>
      </tr>
    `);

    breakdown.innerHTML = rows.length ? rows.join('') : `
      <tr>
        <td colspan="4" class="text-center wr-muted py-3">파일 형식별 OCR/Parser 상태가 없습니다.</td>
      </tr>
    `;

    lastOcrGateStatus = { total, completed, failed, pending, chunkReady, totalChars, gatePass };
    renderBuilderOcrKpis(lastOcrGateStatus, step5Status);
  }

  function renderBuilderOcrKpis(gateStatus, step5Status) {
    const kpiRow = getEl('kpiRow');
    const activeTarget = document.querySelector('[data-target].active')?.dataset?.target;
    if (!kpiRow || activeTarget !== 'builder' || !gateStatus) return;

    const total = Number(gateStatus.total || 0);
    const completed = Number(gateStatus.completed || 0);
    const failed = Number(gateStatus.failed || 0);
    const pending = Number(gateStatus.pending || 0);
    const chunked = Number(step5Status?.chunked_documents || gateStatus.chunkReady || 0);
    const notChunked = Number(step5Status?.not_chunked || 0);
    const gateLabel = gateStatus.gatePass ? 'PASS' : 'CHECK';
    const gateNote = gateStatus.gatePass
      ? `done ${formatNumber(completed)} / failed 0`
      : `failed ${formatNumber(failed)} / pending ${formatNumber(pending)}`;

    kpiRow.innerHTML = [
      ['OCR Gate', gateLabel, gateNote, 'bi-file-earmark-check', gateStatus.gatePass ? 'success' : 'warning'],
      ['Step 4 Done', `${formatNumber(completed)} / ${formatNumber(total)}`, `pending ${formatNumber(pending)}`, 'bi-check2-circle', failed ? 'warning' : 'success'],
      ['Chunk Ready', `${formatNumber(chunked)} / ${formatNumber(total)}`, `not chunked ${formatNumber(notChunked)}`, 'bi-text-paragraph', notChunked ? 'primary' : 'success'],
      ['Total Chars', formatNumber(gateStatus.totalChars), '추출 텍스트 합계', 'bi-body-text', 'success']
    ].map(([label, value, note, icon, tone]) => `
      <div class="col-12 col-sm-6 col-xl-3">
        <div class="wr-card-flat p-3 h-100">
          <div class="d-flex justify-content-between gap-2">
            <div class="small fw-bold wr-muted">${label}</div>
            <i class="bi ${icon} text-${tone}"></i>
          </div>
          <div class="wr-kpi-value mt-2">${value}</div>
          <div class="small wr-muted mt-1">${note}</div>
        </div>
      </div>
    `).join('');

    setText('nextTitle', gateStatus.gatePass ? 'OCR Gate는 통과했습니다. Step 5 미청킹 문서를 확인하세요.' : 'OCR Gate 품질 확인이 필요합니다.');
    setText('nextText', gateStatus.gatePass
      ? `Step 4는 ${formatNumber(completed)}건 모두 완료됐고, Step 5는 ${formatNumber(chunked)}건 청킹 완료 / ${formatNumber(notChunked)}건 미청킹 상태입니다.`
      : `Step 4 실패 ${formatNumber(failed)}건, 대기 ${formatNumber(pending)}건을 먼저 처리해야 합니다.`
    );
  }

  function errorLabel(error) {
    if (error.type === 'timeout') return 'timeout';
    if (error.type === 'network') return 'network';
    if (error.status) return `HTTP ${error.status}`;
    return 'error';
  }

  async function loadEndpoint(label, endpoint) {
    adminConsole.info(`GET ${endpoint} 요청`);
    try {
      const result = await apiClient.get(endpoint);
      adminConsole.success(`${label} ${result.status} OK`);
      return { ok: true, status: result.status, data: result.data };
    } catch (error) {
      const labelText = errorLabel(error);
      adminConsole.error(`${label} ${labelText} - ${error.message}`);
      return { ok: false, status: error.status || 0, error };
    }
  }

  async function loadDashboardLiveStatus() {
    const datasetResult = await loadEndpoint('Dataset Status', DATASET_STATUS_ENDPOINT);
    const faissResult = await loadEndpoint('FAISS Status', FAISS_STATUS_ENDPOINT);

    renderApiRows([
      {
        method: 'GET',
        endpoint: `${apiClient.baseUrl}${DATASET_STATUS_ENDPOINT}`,
        ok: datasetResult.ok,
        label: datasetResult.ok ? `${datasetResult.status} OK` : errorLabel(datasetResult.error)
      },
      {
        method: 'GET',
        endpoint: `${apiClient.baseUrl}${FAISS_STATUS_ENDPOINT}`,
        ok: faissResult.ok,
        label: faissResult.ok ? `${faissResult.status} OK` : errorLabel(faissResult.error)
      }
    ]);

    if (datasetResult.ok) lastDatasetStatus = datasetResult.data || {};
    if (faissResult.ok) lastFaissStatus = faissResult.data || {};

    if (lastDatasetStatus) {
      renderLiveKpis(lastDatasetStatus, lastFaissStatus);
      setText('panelBadge', lastDatasetStatus.step3_review_required > 0 ? `검수 대기 ${lastDatasetStatus.step3_review_required}건` : '읽기 API 연결 완료');
      getEl('panelBadge')?.classList.remove('text-bg-warning', 'text-bg-info', 'text-bg-danger');
      getEl('panelBadge')?.classList.add(lastDatasetStatus.step3_review_required > 0 ? 'text-bg-warning' : 'text-bg-success');
      adminConsole.success('Dashboard KPI를 서버 응답값으로 갱신했습니다');
    }
  }

  async function loadSourceLiveStatus() {
    const statusResult = await loadEndpoint('Source Status', SOURCE_STATUS_ENDPOINT);
    const filesResult = await loadEndpoint('Source Files', SOURCE_FILES_ENDPOINT);

    renderApiRows([
      apiRow('GET', SOURCE_STATUS_ENDPOINT, statusResult),
      apiRow('GET', SOURCE_FILES_ENDPOINT, filesResult),
      { method: 'POST', endpoint: `${apiClient.baseUrl}/admin/rag-source/scan`, ok: true, label: 'Ready' }
    ]);

    const status = statusResult.data || {};
    const files = filesResult.data || {};
    const documentStats = status.documents || {};
    const fileRows = (files.files || []).slice(0, 10).map((item) => [
      item.file_name || item.filename || item.name || item.file_path || `문서 ${item.id || '-'}`,
      item.status || item.file_status || '-',
      item.meta_status || item.document_type || '-',
      item.file_path || item.path || item.source_path || '-'
    ]);

    renderKpiCards([
      ['Total Files', files.total ?? documentStats.total ?? documentStats.total_documents ?? '-', 'RAG Source DB 기준', 'bi-files', 'success'],
      ['Listed', (files.files || []).length, `limit ${formatNumber(files.limit || 10)}`, 'bi-list-ul', 'primary'],
      ['Snapshot', status.snapshot || '-', '현재 설정 snapshot', 'bi-broadcast', 'success'],
      ['FAISS Chunks', status.faiss?.chunk_count ?? status.faiss?.chunks ?? '-', '검색 인덱스 기준', 'bi-hdd-network', 'info']
    ]);

    setPanelBadge(statusResult.ok || filesResult.ok ? '읽기 API 연결 완료' : '조회 실패', statusResult.ok || filesResult.ok ? 'success' : 'danger');
    setText('nextTitle', 'Source Documents 조회 API가 연결되었습니다.');
    setText('nextText', `파일 목록 ${formatNumber(files.total ?? '-')}건 기준으로 신규/오류 문서와 Metadata Build 대상을 확인하세요.`);
    replacePanelBodyWithCardsAndTable(
      [
        ['Source Status', `snapshot=${status.snapshot || '-'} 기준 RAG Source 상태를 조회합니다.`, 'bi-folder2-open', 'success'],
        ['Inventory', `현재 화면에는 최대 ${formatNumber(files.limit || 10)}건을 샘플로 표시합니다.`, 'bi-table', 'primary'],
        ['Next Step', '오류 문서는 재스캔하고 정상 문서는 Metadata Build로 이동합니다.', 'bi-arrow-right-circle', 'warning']
      ],
      ['파일', '상태', '메타 상태', '경로'],
      fileRows,
      '조회된 Source 파일이 없습니다.'
    );
  }

  async function loadMetadataLiveStatus() {
    const statsResult = await loadEndpoint('Metadata Review Stats', METADATA_STATS_ENDPOINT);
    const docsResult = await loadEndpoint('Metadata Review Documents', METADATA_DOCS_ENDPOINT);

    renderApiRows([
      apiRow('GET', METADATA_STATS_ENDPOINT, statsResult),
      apiRow('GET', METADATA_DOCS_ENDPOINT, docsResult),
      { method: 'PATCH', endpoint: `${apiClient.baseUrl}/admin/metadata-review/documents/{id}`, ok: true, label: 'Ready' }
    ]);

    const stats = statsResult.data || {};
    const docs = docsResult.data || {};
    const counts = stats.status_counts || docs.status_counts || {};
    const rows = (docs.documents || []).slice(0, 10).map((doc) => [
      doc.file_name || doc.file_path || `문서 ${doc.document_id}`,
      doc.meta_status || '-',
      doc.category_id || doc.document_type || '-',
      doc.project_name || (doc.keywords || []).slice(0, 3).join(', ') || '-'
    ]);

    renderKpiCards([
      ['Review Required', stats.review_required ?? counts.review_required ?? '-', '관리자 검수 필요', 'bi-clipboard-check', 'warning'],
      ['Reviewed', stats.reviewed ?? counts.metadata_reviewed ?? counts.confirmed ?? '-', '검수 완료', 'bi-check-circle', 'success'],
      ['Rejected', stats.rejected ?? counts.rejected ?? '-', '재처리 필요', 'bi-x-circle', 'danger'],
      ['Total', stats.total_documents ?? docs.total ?? '-', 'Metadata Review 기준', 'bi-ui-checks-grid', 'primary']
    ]);

    setPanelBadge(stats.review_required || counts.review_required ? `검수 대기 ${formatNumber(stats.review_required ?? counts.review_required)}건` : '검수 조회 완료', stats.review_required || counts.review_required ? 'warning' : 'success');
    setText('nextTitle', 'Metadata Review 조회 API가 연결되었습니다.');
    setText('nextText', '검수 대기 문서는 승인/반려 후 Step 4 OCR/Parser 대상으로 넘기는 흐름을 유지해야 합니다.');
    replacePanelBodyWithCardsAndTable(
      [
        ['Status Counts', `상태별 집계를 Metadata Review API에서 조회합니다.`, 'bi-bar-chart', 'success'],
        ['Review Queue', `현재 화면에는 최대 ${formatNumber(docs.limit || 10)}건을 표시합니다.`, 'bi-list-check', 'warning'],
        ['Pipeline Rule', '승인된 문서만 OCR, Chunk, FAISS 단계로 이동해야 합니다.', 'bi-shield-check', 'primary']
      ],
      ['문서', '상태', '분류', '프로젝트/키워드'],
      rows,
      '검수 대상 문서가 없습니다.'
    );
  }

  function statusCountValue(stats, docs, key) {
    return stats?.status_counts?.[key] ?? docs?.status_counts?.[key];
  }

  async function loadStep3ProgressToConsole() {
    adminConsole.info('Step 3 Metadata Review 진행 상태 조회 시작');

    const statsResult = await loadEndpoint('Step 3 Metadata Review Stats', METADATA_STATS_ENDPOINT);
    const docsResult = await loadEndpoint('Step 3 Review Queue', `${METADATA_DOCS_ENDPOINT}&status=review_required`);

    renderApiRows([
      apiRow('GET', METADATA_STATS_ENDPOINT, statsResult),
      apiRow('GET', `${METADATA_DOCS_ENDPOINT}&status=review_required`, docsResult)
    ]);

    if (!statsResult.ok && !docsResult.ok) {
      adminConsole.error('Step 3 Metadata Review 상태 API를 불러오지 못했습니다');
      return;
    }

    const stats = statsResult.data || {};
    const docs = docsResult.data || {};
    const total = Number(stats.total_documents ?? docs.total ?? 0);
    const reviewRequired = Number(stats.review_required ?? statusCountValue(stats, docs, 'review_required') ?? 0);
    const reviewed = Number(stats.reviewed ?? statusCountValue(stats, docs, 'metadata_reviewed') ?? statusCountValue(stats, docs, 'confirmed') ?? 0);
    const rejected = Number(stats.rejected ?? statusCountValue(stats, docs, 'rejected') ?? 0);
    const doneRate = pct(reviewed + rejected, total);
    const queue = docs.documents || [];

    adminConsole.info(`Step 3 총 문서: ${formatNumber(total)}건`);
    adminConsole.info(`Step 3 검수 대기: ${formatNumber(reviewRequired)}건`);
    adminConsole.success(`Step 3 검수 완료: ${formatNumber(reviewed)}건 / 반려: ${formatNumber(rejected)}건 / 진행률: ${doneRate}%`);

    if (queue.length) {
      adminConsole.warn(`Step 3 검수 대기 샘플 ${formatNumber(queue.length)}건을 확인했습니다`);
      queue.slice(0, 3).forEach((doc) => {
        adminConsole.info(`대기 문서: ${doc.file_name || doc.file_path || `document_id=${doc.document_id}`}`);
      });
    } else {
      adminConsole.success('Step 3 검수 대기 문서가 없습니다');
    }

    setPanelBadge(
      reviewRequired ? `Step 3 검수 대기 ${formatNumber(reviewRequired)}건` : 'Step 3 검수 완료',
      reviewRequired ? 'warning' : 'success'
    );
    setStep3ProgressState(reviewRequired);
    setText(
      'nextTitle',
      reviewRequired ? 'Step 3 Metadata Review 진행 상태를 확인했습니다.' : 'Step 3 Metadata Review 대기 문서가 없습니다.'
    );
    setText(
      'nextText',
      reviewRequired
        ? `검수 대기 ${formatNumber(reviewRequired)}건을 처리한 뒤 Step 4 OCR / Parser로 이동하세요.`
        : 'Step 4 OCR / Parser 상태를 확인하고 다음 단계로 진행할 수 있습니다.'
    );
  }

  async function loadFaissLiveStatus() {
    const statusResult = await loadEndpoint('FAISS Status', FAISS_STATUS_ENDPOINT);
    const indexesResult = await loadEndpoint('FAISS Indexes', FAISS_INDEXES_ENDPOINT);
    const jobsResult = await loadEndpoint('FAISS Jobs', FAISS_JOBS_ENDPOINT);
    const stagedResult = await loadEndpoint('FAISS Staged Summary', FAISS_STAGED_ENDPOINT);

    renderApiRows([
      apiRow('GET', FAISS_STATUS_ENDPOINT, statusResult),
      apiRow('GET', FAISS_INDEXES_ENDPOINT, indexesResult),
      apiRow('GET', FAISS_JOBS_ENDPOINT, jobsResult),
      apiRow('GET', FAISS_STAGED_ENDPOINT, stagedResult)
    ]);

    const status = statusResult.data || {};
    const indexes = indexesResult.data || {};
    const jobs = jobsResult.data || {};
    const active = status.active || {};
    const stats = status.stats || {};
    const config = status.server_config || {};
    const jobList = jobs.jobs || [];

    renderKpiCards([
      ['Active Snapshot', active.snapshot || config.active_snapshot || '-', '서버 적용값', 'bi-broadcast-pin', 'success'],
      ['Vectors / Chunks', stats.chunk_count ?? '-', stats.index_exists ? 'index exists' : 'index missing', 'bi-hdd-stack', stats.index_exists ? 'success' : 'warning'],
      ['Embedding', config.embedding_model || '-', `${config.embedding_provider || '-'} / dim ${formatNumber(config.embedding_dim)}`, 'bi-cpu', 'primary'],
      ['Jobs', jobList.length, 'FAISS JobTracker', 'bi-terminal', jobList.length ? 'warning' : 'success']
    ]);

    const rows = (indexes.indexes || []).slice(0, 10).map((item) => [
      item.snapshot,
      item.is_active ? 'active' : 'available',
      item.index_exists ? 'index OK' : 'index 없음',
      `${formatNumber(item.chunk_count)} chunks / ${formatNumber(item.index_size_mb)} MB`
    ]);

    setPanelBadge(statusResult.ok ? 'FAISS 조회 완료' : 'FAISS 인증/조회 필요', statusResult.ok ? 'success' : 'danger');
    setText('nextTitle', statusResult.ok ? 'FAISS 서버 적용값을 조회했습니다.' : 'FAISS 상태 조회에 실패했습니다.');
    setText('nextText', '화면 입력값이 아니라 /admin/faiss/status 응답을 기준으로 임베딩 모델, active snapshot, index 파일 상태를 판단합니다.');
    replacePanelBodyWithCardsAndTable(
      [
        ['Runtime Truth', `answer=${config.answer_model || '-'}, embed=${config.embedding_model || '-'}`, 'bi-sliders', 'success'],
        ['Staged Summary', stagedResult.ok ? 'staged 디렉토리 상태 API가 응답했습니다.' : 'staged 상태 확인이 필요합니다.', 'bi-folder-check', stagedResult.ok ? 'primary' : 'warning'],
        ['Jobs', `최근 Job ${formatNumber(jobList.length)}건을 조회했습니다.`, 'bi-terminal', jobList.length ? 'warning' : 'success']
      ],
      ['Snapshot', '상태', 'Index', '크기/청크'],
      rows,
      '조회된 FAISS index가 없습니다.'
    );
  }

  async function loadGraphWikiLiveStatus() {
    const graphResult = await loadEndpoint('Graph Status', GRAPH_STATUS_ENDPOINT);
    const graphStatsResult = await loadEndpoint('Graph Stats', GRAPH_STATS_ENDPOINT);
    const step8Result = await loadEndpoint('Step 8 Status', STEP8_STATUS_ENDPOINT);
    const step9Result = await loadEndpoint('Step 9 Status', STEP9_STATUS_ENDPOINT);
    const wikiResult = await loadEndpoint('Wiki Stats', WIKI_STATS_ENDPOINT);

    renderApiRows([
      apiRow('GET', GRAPH_STATUS_ENDPOINT, graphResult),
      apiRow('GET', GRAPH_STATS_ENDPOINT, graphStatsResult),
      apiRow('GET', STEP8_STATUS_ENDPOINT, step8Result),
      apiRow('GET', STEP9_STATUS_ENDPOINT, step9Result),
      apiRow('GET', WIKI_STATS_ENDPOINT, wikiResult)
    ]);

    const graph = graphResult.data || {};
    const step8 = step8Result.data || {};
    const step9 = step9Result.data || {};
    const wiki = wikiResult.data || {};
    const nodeCount = graph.node_count ?? step8.node_count ?? graphStatsResult.data?.node_count ?? '-';
    const edgeCount = graph.edge_count ?? step8.edge_count ?? graphStatsResult.data?.edge_count ?? '-';
    const wikiCount = step9.total_wikis ?? wiki.total ?? wiki.project_count ?? '-';

    renderKpiCards([
      ['Graph Nodes', nodeCount, graph.status || step8.graph_status || 'JSON graph', 'bi-diagram-2', 'success'],
      ['Graph Edges', edgeCount, '관계 수', 'bi-share', 'primary'],
      ['Wiki Docs', wikiCount, 'LLM Wiki', 'bi-journal-text', wikiCount ? 'success' : 'warning'],
      ['Storage', 'JSON', 'Neo4j 전제 없음', 'bi-filetype-json', 'success']
    ]);

    setPanelBadge(graphResult.ok || step8Result.ok ? 'Graph/Wiki 조회 완료' : 'Graph/Wiki 조회 필요', graphResult.ok || step8Result.ok ? 'success' : 'danger');
    setText('nextTitle', 'Graph JSON과 LLM Wiki 상태 조회 API가 연결되었습니다.');
    setText('nextText', 'Graph JSON 파일 상태와 Wiki 문서 수를 같은 화면에서 확인한 뒤 사용자 검색 품질 검증으로 이동하세요.');
    renderInfoCards([
      ['Graph JSON', `status=${graph.status || step8.graph_status || '-'}, nodes=${formatNumber(nodeCount)}, edges=${formatNumber(edgeCount)}`, 'bi-diagram-3', 'success'],
      ['LLM Wiki', `project=${formatNumber(wiki.project_count ?? step9.project_wikis ?? '-')}, total=${formatNumber(wikiCount)}`, 'bi-journal-text', 'primary'],
      ['User 연결', 'rag-assistant.html에서 Graph RAG / LLM Wiki 결과 탭을 함께 확인해야 합니다.', 'bi-search-heart', 'warning']
    ]);
  }

  async function loadQualityLiveStatus() {
    const datasetResult = await loadEndpoint('Dataset Status', DATASET_STATUS_ENDPOINT);
    const graphResult = await loadEndpoint('Graph Status', GRAPH_STATUS_ENDPOINT);
    const wikiResult = await loadEndpoint('Wiki Stats', WIKI_STATS_ENDPOINT);

    renderApiRows([
      apiRow('GET', DATASET_STATUS_ENDPOINT, datasetResult),
      apiRow('GET', GRAPH_STATUS_ENDPOINT, graphResult),
      apiRow('GET', WIKI_STATS_ENDPOINT, wikiResult),
      { method: 'GET', endpoint: `${apiClient.baseUrl}/rag/search`, ok: true, label: 'User API' }
    ]);

    const dataset = datasetResult.data || {};
    const graph = graphResult.data || {};
    const wiki = wikiResult.data || {};
    const qualityPassed = dataset.step10_quality_passed === true;

    renderKpiCards([
      ['Active Snapshot', dataset.step10_active_snapshot || '-', '검색 공개 기준', 'bi-broadcast', 'success'],
      ['Quality', qualityPassed ? 'PASS' : 'CHECK', `score ${formatNumber(dataset.step10_quality_score)}`, 'bi-search-heart', qualityPassed ? 'success' : 'warning'],
      ['Graph Ready', graph.has_data ? 'YES' : 'CHECK', `${formatNumber(graph.node_count)} nodes`, 'bi-diagram-2', graph.has_data ? 'success' : 'warning'],
      ['Wiki Docs', wiki.total ?? wiki.project_count ?? '-', 'Wiki 검색 근거', 'bi-journal-text', 'primary']
    ]);

    setPanelBadge(qualityPassed ? '검색 품질 통과' : '검증 필요', qualityPassed ? 'success' : 'warning');
    setText('nextTitle', qualityPassed ? '검색 품질 기준을 통과했습니다.' : '대표 질문 세트로 검색 품질을 검증해야 합니다.');
    setText('nextText', 'LangSmith 추적과 대표 질문 세트를 함께 사용해 질문, 검색 근거, 답변, 평가 결과를 확인하세요.');
    renderInfoCards([
      ['RAG Search', `active snapshot=${dataset.step10_active_snapshot || '-'}`, 'bi-search', 'success'],
      ['Graph RAG', `graph status=${graph.status || '-'}`, 'bi-share', graph.has_data ? 'success' : 'warning'],
      ['LLM Wiki', `wiki total=${formatNumber(wiki.total ?? wiki.project_count ?? '-')}`, 'bi-journal-text', 'primary']
    ]);
  }

  async function loadJobsLiveStatus() {
    const jobsResult = await loadEndpoint('FAISS Jobs', FAISS_JOBS_ENDPOINT);
    const stagedResult = await loadEndpoint('FAISS Staged Summary', FAISS_STAGED_ENDPOINT);

    renderApiRows([
      apiRow('GET', FAISS_JOBS_ENDPOINT, jobsResult),
      apiRow('GET', FAISS_STAGED_ENDPOINT, stagedResult)
    ]);

    const jobs = jobsResult.data?.jobs || [];
    const failed = jobs.filter((job) => String(job.status || '').toLowerCase().includes('fail')).length;
    const running = jobs.filter((job) => String(job.status || '').toLowerCase().includes('run')).length;
    const rows = jobs.slice(0, 10).map((job) => [
      job.job_id || job.id || '-',
      job.stage || job.pipeline || job.snapshot || '-',
      job.status || '-',
      job.error || job.message || job.updated_at || '-'
    ]);

    renderKpiCards([
      ['Jobs', jobs.length, 'FAISS pipeline jobs', 'bi-terminal', jobs.length ? 'primary' : 'success'],
      ['Running', running, '진행 중', 'bi-play-circle', running ? 'warning' : 'success'],
      ['Failed', failed, '조치 필요', 'bi-bug', failed ? 'danger' : 'success'],
      ['Staged', stagedResult.ok ? 'OK' : 'CHECK', 'staged summary', 'bi-folder-check', stagedResult.ok ? 'success' : 'warning']
    ]);

    setPanelBadge(failed ? `실패 Job ${formatNumber(failed)}건` : 'Job 조회 완료', failed ? 'danger' : 'success');
    setText('nextTitle', failed ? '실패 Job의 서버 로그와 API 경로를 확인하세요.' : '최근 Job 상태를 조회했습니다.');
    setText('nextText', '현재 화면은 FAISS JobTracker 중심의 읽기 조회이며, 재시도 실행 버튼은 아직 연결하지 않았습니다.');
    replacePanelBodyWithCardsAndTable(
      [
        ['FAISS Jobs', `최근 Job ${formatNumber(jobs.length)}건`, 'bi-terminal', 'primary'],
        ['Failure Split', `failed=${formatNumber(failed)}, running=${formatNumber(running)}`, 'bi-bug', failed ? 'danger' : 'success'],
        ['Next', '실패 원인은 서버 로그와 Job error 메시지를 함께 확인해야 합니다.', 'bi-journal-code', 'warning']
      ],
      ['Job', 'Stage', 'Status', 'Message'],
      rows,
      '조회된 Job이 없습니다.'
    );
  }

  async function loadSettingsLiveStatus() {
    const faissResult = await loadEndpoint('FAISS Status', FAISS_STATUS_ENDPOINT);
    const llmResult = await loadEndpoint('LLM Settings', LLM_SETTINGS_ENDPOINT);

    renderApiRows([
      apiRow('GET', FAISS_STATUS_ENDPOINT, faissResult),
      apiRow('GET', LLM_SETTINGS_ENDPOINT, llmResult)
    ]);

    const config = faissResult.data?.server_config || {};
    const llm = llmResult.data || {};

    renderKpiCards([
      ['Answer Model', config.answer_model || llm.answer_model || '-', config.answer_provider || llm.answer_provider || 'provider', 'bi-chat-square-text', 'success'],
      ['Embedding', config.embedding_model || '-', config.embedding_provider || 'provider', 'bi-cpu', 'primary'],
      ['Dimension', config.embedding_dim || '-', 'embedding dim', 'bi-braces', 'success'],
      ['API Base', apiClient.baseUrl, 'frontend config', 'bi-server', 'info']
    ]);

    setPanelBadge(faissResult.ok || llmResult.ok ? '서버 설정 조회 완료' : '설정 조회 필요', faissResult.ok || llmResult.ok ? 'success' : 'danger');
    setText('nextTitle', '서버 적용 설정값을 조회했습니다.');
    setText('nextText', '관리자 화면 입력값보다 서버 API 응답값을 우선해 모델, 임베딩, snapshot 상태를 판단합니다.');
    renderInfoCards([
      ['Runtime Truth', `answer=${config.answer_model || '-'}, embedding=${config.embedding_model || '-'}`, 'bi-sliders', 'success'],
      ['Snapshot', `active=${config.active_snapshot || faissResult.data?.active?.snapshot || '-'}`, 'bi-broadcast', 'primary'],
      ['Frontend', `API Base=${apiClient.baseUrl}`, 'bi-server', 'info']
    ]);
  }

  async function loadOcrQualityGate() {
    if (!getEl('ocrQualityGate')) return;

    adminConsole.info('Dataset Builder Step 4 OCR / Parser 실행 상태 확인 시작');
    adminConsole.info('OCR Quality Gate 읽기 API 요청');
    const step4Status = await loadEndpoint('Step 4 Status', STEP4_STATUS_ENDPOINT);
    const step4Stats = await loadEndpoint('Step 4 Stats', STEP4_STATS_ENDPOINT);
    const step5Status = await loadEndpoint('Step 5 Status', STEP5_STATUS_ENDPOINT);

    renderApiRows([
      {
        method: 'GET',
        endpoint: `${apiClient.baseUrl}${STEP4_STATUS_ENDPOINT}`,
        ok: step4Status.ok,
        label: step4Status.ok ? `${step4Status.status} OK` : errorLabel(step4Status.error)
      },
      {
        method: 'GET',
        endpoint: `${apiClient.baseUrl}${STEP4_STATS_ENDPOINT}`,
        ok: step4Stats.ok,
        label: step4Stats.ok ? `${step4Stats.status} OK` : errorLabel(step4Stats.error)
      },
      {
        method: 'GET',
        endpoint: `${apiClient.baseUrl}${STEP5_STATUS_ENDPOINT}`,
        ok: step5Status.ok,
        label: step5Status.ok ? `${step5Status.status} OK` : errorLabel(step5Status.error)
      }
    ]);

    if (step4Status.ok || step4Stats.ok || step5Status.ok) {
      renderOcrGateMetrics(
        step4Status.data || {},
        step4Stats.data || {},
        step5Status.data || {}
      );

      if (lastOcrGateStatus?.gatePass) {
        adminConsole.success(`OCR Gate 통과: done=${lastOcrGateStatus.completed}, failed=${lastOcrGateStatus.failed}, pending=${lastOcrGateStatus.pending}`);
      } else if (lastOcrGateStatus) {
        adminConsole.warn(`OCR Gate 확인 필요: done=${lastOcrGateStatus.completed}, failed=${lastOcrGateStatus.failed}, pending=${lastOcrGateStatus.pending}`);
      }
    } else {
      adminConsole.error('OCR Quality Gate API를 불러오지 못했습니다');
    }
  }

  function checkAdminAuth() {
    if (apiClient.hasToken()) return true;

    adminConsole.warn('관리자 토큰이 없어 admin.html로 이동합니다');
    window.alert('관리자 로그인이 필요합니다.');
    window.location.href = './admin.html';
    return false;
  }

  function wireRefreshButton() {
    const refreshButton = document.querySelector('[data-simulate="refresh"]');
    if (!refreshButton) return;

    refreshButton.addEventListener('click', () => {
      loadActivePanelLiveStatus();
    });
  }

  function wireRunButton() {
    const runButton = document.querySelector('[data-simulate="run"]');
    if (!runButton) return;

    runButton.addEventListener('click', (event) => {
      // 기존 HTML 인라인 시뮬레이션 로그 대신 현재 메뉴의 실제 read API를 실행한다.
      event.preventDefault();
      event.stopImmediatePropagation();

      const activeTarget = document.querySelector('[data-target].active')?.dataset?.target || 'dashboard';
      if (activeTarget === 'builder') {
        adminConsole.info('실행 버튼 클릭: Step 4 OCR / Parser 상태와 Step 5 진입 조건을 조회합니다');
        loadOcrQualityGate();
        return;
      }

      adminConsole.info(`실행 버튼 클릭: ${activeTarget} 메뉴의 조회 API를 실행합니다`);
      loadActivePanelLiveStatus();
    }, true);
  }

  function wireMenuLiveLoaders() {
    document.querySelectorAll('[data-target]').forEach((button) => {
      button.addEventListener('click', () => {
        window.setTimeout(loadActivePanelLiveStatus, 0);
      });
    });
  }

  function wireStep3ProgressButton() {
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action="show-step3-status"]');
      if (!button) return;

      event.preventDefault();
      loadStep3ProgressToConsole();
    });
  }

  function wireHomeLink() {
    const homeButton = document.querySelector('[data-action="go-home"]');
    if (!homeButton) return;

    homeButton.addEventListener('click', () => {
      const dashboardButton = document.querySelector('[data-target="dashboard"]');
      if (dashboardButton) {
        dashboardButton.click();
      } else {
        loadDashboardLiveStatus();
      }
    });
  }

  function loadActivePanelLiveStatus() {
    const activeTarget = document.querySelector('[data-target].active')?.dataset?.target || 'dashboard';

    if (activeTarget === 'dashboard') return loadDashboardLiveStatus();
    if (activeTarget === 'source') return loadSourceLiveStatus();
    if (activeTarget === 'metadata') return loadMetadataLiveStatus();
    if (activeTarget === 'builder') return loadOcrQualityGate();
    if (activeTarget === 'faiss') return loadFaissLiveStatus();
    if (activeTarget === 'graph') return loadGraphWikiLiveStatus();
    if (activeTarget === 'quality') return loadQualityLiveStatus();
    if (activeTarget === 'jobs') return loadJobsLiveStatus();
    if (activeTarget === 'settings') return loadSettingsLiveStatus();

    return loadDashboardLiveStatus();
  }

  function init() {
    apiClient = window.apiClient || new window.WeesleeApiClient();
    adminConsole = new window.WeesleeAdminConsole('#consoleBody');
    window.adminConsole = adminConsole;

    adminConsole.info('rag-admin2 API 연동 스크립트 초기화');
    adminConsole.info(`API Base URL: ${apiClient.baseUrl}`);

    wireRefreshButton();
    wireRunButton();
    wireMenuLiveLoaders();
    wireStep3ProgressButton();
    wireHomeLink();

    if (!checkAdminAuth()) return;
    loadActivePanelLiveStatus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
