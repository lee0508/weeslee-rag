4. AdminConsole 모듈 작성
frontend/js/admin-console.js
역할:

API 요청 시작 로그
응답 성공 로그
실패 원인 로그
Job 진행률 로그
INFO / SUCCESS / WARN / ERROR 구분

예시:
class AdminConsole {
    constructor(selector = '#apiConsole') {
        this.el = document.querySelector(selector);
    }

    log(level, message) {
        if (!this.el) return;

        const time = new Date().toLocaleTimeString('ko-KR', {
            hour12: false
        });

        const line = document.createElement('div');
        line.className = `console-line console-${level.toLowerCase()}`;
        line.textContent = `[${time}] ${level.padEnd(7)} ${message}`;

        this.el.appendChild(line);
        this.el.scrollTop = this.el.scrollHeight;
    }

    info(message) {
        this.log('INFO', message);
    }

    success(message) {
        this.log('SUCCESS', message);
    }

    warn(message) {
        this.log('WARN', message);
    }

    error(message) {
        this.log('ERROR', message);
    }

    clear() {
        if (this.el) {
            this.el.innerHTML = '';
        }
    }
}

window.adminConsole = new AdminConsole();
