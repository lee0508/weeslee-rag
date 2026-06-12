(function () {
  'use strict';

  class ApiClient {
    constructor(config) {
      this.config = config || window.WEESLEE_RAG_CONFIG || {};
      this.baseUrl = String(this.config.API_BASE_URL || window.__API_BASE__ || '/weeslee-rag/api').replace(/\/+$/, '');
      this.tokenKey = this.config.ADMIN_TOKEN_KEY || 'admin_token';
      this.timeoutMs = Number(this.config.REQUEST_TIMEOUT_MS || 30000);
    }

    getToken() {
      return window.localStorage.getItem(this.tokenKey);
    }

    hasToken() {
      return !!this.getToken();
    }

    url(endpoint) {
      const value = String(endpoint || '');
      if (/^https?:\/\//i.test(value)) return value;
      if (!value) return this.baseUrl;
      if (value.startsWith('/api/')) return `${this.baseUrl}${value.slice(4)}`;
      return `${this.baseUrl}${value.startsWith('/') ? value : `/${value}`}`;
    }

    async request(method, endpoint, body) {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), this.timeoutMs);
      const token = this.getToken();
      const headers = { 'Content-Type': 'application/json' };

      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const options = {
        method,
        headers,
        signal: controller.signal
      };

      if (body !== undefined && body !== null) {
        options.body = JSON.stringify(body);
      }

      try {
        const response = await window.fetch(this.url(endpoint), options);
        window.clearTimeout(timeoutId);

        const text = await response.text();
        let data = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (parseError) {
            data = { raw: text };
          }
        }

        if (!response.ok) {
          throw {
            type: 'http',
            status: response.status,
            statusText: response.statusText,
            message: data?.detail || data?.message || response.statusText || `HTTP ${response.status}`,
            data
          };
        }

        return {
          ok: true,
          status: response.status,
          data
        };
      } catch (error) {
        window.clearTimeout(timeoutId);

        if (error.name === 'AbortError') {
          throw {
            type: 'timeout',
            status: 0,
            message: 'API 요청 시간이 초과되었습니다.'
          };
        }

        if (error.type === 'http') {
          throw error;
        }

        throw {
          type: 'network',
          status: 0,
          message: '서버에 연결할 수 없습니다.',
          originalError: error
        };
      }
    }

    get(endpoint) {
      return this.request('GET', endpoint);
    }

    post(endpoint, body) {
      return this.request('POST', endpoint, body || {});
    }

    put(endpoint, body) {
      return this.request('PUT', endpoint, body || {});
    }

    delete(endpoint) {
      return this.request('DELETE', endpoint);
    }
  }

  window.WeesleeApiClient = ApiClient;
  window.apiClient = window.apiClient || new ApiClient();
})();
