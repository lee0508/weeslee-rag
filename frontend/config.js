// 런타임 API 엔드포인트 설정 — 배포 환경에 맞게 수정
// 로컬 개발: window.__API_BASE__ = 'http://localhost:8001/api';
// 프로덕션: window.__API_BASE__ = '/weeslee-rag/api';
window.__API_BASE__ = '/weeslee-rag/api';

// 관리자 UI 공통 런타임 설정.
// 기존 admin.html은 window.__API_BASE__를 사용하므로 그대로 유지하고,
// rag-admin2.html의 API 연동 모듈은 아래 설정을 우선 참조한다.
window.WEESLEE_RAG_CONFIG = {
  API_BASE_URL: window.__API_BASE__ || '/api',
  ADMIN_TOKEN_KEY: 'admin_token',
  REQUEST_TIMEOUT_MS: 30000,
  JOB_POLL_INTERVAL_MS: 3000
};
