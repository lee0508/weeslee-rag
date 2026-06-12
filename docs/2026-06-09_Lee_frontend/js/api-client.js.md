3. ApiClient 공통 모듈 작성

frontend/js/api-client.js
역할:

GET / POST / PUT / DELETE 공통 처리
Authorization Bearer token 처리
timeout 처리
JSON 파싱
401 / 404 / 500 / timeout / network 오류 구분

예시 구조:
class ApiClient {
    constructor() {
        this.baseUrl = window.WEESLEE_RAG_CONFIG?.API_BASE_URL || '/api';
        this.tokenKey = window.WEESLEE_RAG_CONFIG?.ADMIN_TOKEN_KEY || 'admin_token';
        this.timeoutMs = window.WEESLEE_RAG_CONFIG?.REQUEST_TIMEOUT_MS || 30000;
    }

    getToken() {
        return localStorage.getItem(this.tokenKey);
    }

    async request(method, endpoint, body = null) {
        const token = this.getToken();

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            signal: controller.signal
        };

        if (body) {
            options.body = JSON.stringify(body);
        }

        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, options);
            clearTimeout(timeoutId);

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                throw {
                    type: 'http',
                    status: response.status,
                    message: data?.message || response.statusText,
                    data
                };
            }

            return data;
        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw {
                    type: 'timeout',
                    message: 'API 요청 시간이 초과되었습니다.'
                };
            }

            if (error.type === 'http') {
                throw error;
            }

            throw {
                type: 'network',
                message: '서버에 연결할 수 없습니다.',
                originalError: error
            };
        }
    }

    get(endpoint) {
        return this.request('GET', endpoint);
    }

    post(endpoint, body = {}) {
        return this.request('POST', endpoint, body);
    }

    put(endpoint, body = {}) {
        return this.request('PUT', endpoint, body);
    }

    delete(endpoint) {
        return this.request('DELETE', endpoint);
    }
}

window.apiClient = new ApiClient();

