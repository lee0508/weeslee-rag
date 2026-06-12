(function () {
  'use strict';

  class AdminConsole {
    constructor(selector) {
      this.el = document.querySelector(selector || '#consoleBody');
    }

    timeText() {
      return new Date().toLocaleTimeString('ko-KR', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    }

    log(level, message) {
      if (!this.el) return;

      const normalized = String(level || 'INFO').toUpperCase();
      const row = document.createElement('div');
      row.className = 'wr-console-row';
      row.innerHTML = `
        <span class="wr-log-time">${this.timeText()}</span>
        <span class="wr-log-${normalized.toLowerCase()}">${normalized}</span>
        <span>${message}</span>
      `;
      this.el.appendChild(row);
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

  window.WeesleeAdminConsole = AdminConsole;
  window.adminConsole = window.adminConsole || null;
})();
