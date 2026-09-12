/**
 * DeskPilot — JavaScript Bridge Client
 * Wraps window.pywebview.api calls and provides a unified event bus for backend streaming events.
 */

class DeskPilotBridgeClient {
    constructor() {
        this.ready = false;
        this.mode = 'unknown'; // 'pywebview', 'http', or 'offline'
        this.apiBase = 'http://127.0.0.1:5000/api';
        this.eventSource = null;
        this._readyCallbacks = [];
        this._initBridge();
    }

    async _initBridge() {
        if (window.pywebview && window.pywebview.api) {
            this.mode = 'pywebview';
            this.ready = true;
            this._flushReady();
            return;
        }

        window.addEventListener('pywebviewready', () => {
            this.mode = 'pywebview';
            this.ready = true;
            this._flushReady();
        });

        // Check for pywebview for up to 250ms
        for (let i = 0; i < 5; i++) {
            if (window.pywebview && window.pywebview.api) {
                this.mode = 'pywebview';
                this.ready = true;
                this._flushReady();
                return;
            }
            await new Promise(r => setTimeout(r, 50));
        }

        // Check if local Python API server is running at http://127.0.0.1:5000
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 1200);
            const resp = await fetch(`${this.apiBase}/status`, { signal: controller.signal });
            clearTimeout(timeoutId);
            if (resp.ok) {
                this.mode = 'http';
                this._initSSE();
                this.ready = true;
                this._flushReady();
                console.log("DeskPilot connected to local Python backend at", this.apiBase);
                return;
            }
        } catch (e) {
            // Local server offline
        }

        // If neither pywebview nor HTTP server found, mark offline
        this.mode = 'offline';
        this.ready = true;
        this._flushReady();
        console.warn("DeskPilot Python Backend not reachable. Run 'python main.py' or 'python main.py --web'.");
    }

    _initSSE() {
        if (this.eventSource) return;
        try {
            this.eventSource = new EventSource(`${this.apiBase}/events`);
            this.eventSource.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (data && data.event) {
                        window.dispatchEvent(new CustomEvent(data.event, { detail: data.detail }));
                    }
                } catch (err) {}
            };
            this.eventSource.onerror = () => {
                console.warn("SSE connection interrupted, retrying...");
            };
        } catch (err) {
            console.error("Failed to initialize SSE:", err);
        }
    }

    _flushReady() {
        while (this._readyCallbacks.length > 0) {
            const cb = this._readyCallbacks.shift();
            try { cb(); } catch (e) { console.error("Bridge ready callback error:", e); }
        }
    }

    onReady(callback) {
        if (this.ready) {
            callback();
        } else {
            this._readyCallbacks.push(callback);
        }
    }

    async _call(method, ...args) {
        if (!this.ready) {
            await new Promise(resolve => this.onReady(resolve));
        }

        if (this.mode === 'pywebview') {
            try {
                return await window.pywebview.api[method](...args);
            } catch (err) {
                console.error(`Bridge call to ${method} failed:`, err);
                throw err;
            }
        }

        if (this.mode === 'http') {
            return await this._httpCall(method, ...args);
        }

        return this._offlineCall(method, ...args);
    }

    async _httpCall(method, ...args) {
        const base = this.apiBase;
        try {
            switch (method) {
                case 'get_agents':
                    return await (await fetch(`${base}/agents`)).json();
                case 'get_agent':
                    return await (await fetch(`${base}/agent/${encodeURIComponent(args[0])}`)).json();
                case 'get_template_agents':
                    return await (await fetch(`${base}/templates`)).json();
                case 'run_agent_task':
                    return await (await fetch(`${base}/task/run`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ agent_id: args[0], instruction: args[1] })
                    })).json();
                case 'stop_agent_task':
                    return await (await fetch(`${base}/task/stop`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: args[0] })
                    })).json();
                case 'get_tasks':
                    return await (await fetch(`${base}/tasks`)).json();
                case 'respond_to_approval':
                    return await (await fetch(`${base}/approval`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ request_id: args[0], approved: args[1], approve_all: args[2] || false })
                    })).json();
                case 'create_agent_draft':
                    return await (await fetch(`${base}/draft`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ description: args[0] })
                    })).json();
                case 'confirm_create_agent':
                    return await (await fetch(`${base}/agent/create`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ draft: args[0] })
                    })).json();
                case 'delete_custom_agent':
                    return await (await fetch(`${base}/agent/${encodeURIComponent(args[0])}`, {
                        method: 'DELETE'
                    })).json();
                case 'get_recent_activity':
                    return await (await fetch(`${base}/activity?limit=${args[0] || 10}`)).json();
                case 'get_audit_history':
                    return await (await fetch(`${base}/audit?agent_id=${encodeURIComponent(args[0] || '')}`)).json();
                case 'get_system_status':
                    return await (await fetch(`${base}/status`)).json();
                case 'open_deliverable':
                    return await (await fetch(`${base}/open_file`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_path: args[0] })
                    })).json();
                case 'open_file_location':
                    return await (await fetch(`${base}/open_folder`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_path: args[0] })
                    })).json();
                case 'check_winget_installed':
                    return await (await fetch(`${base}/winget/status`)).json();
                case 'get_winget_allowlist':
                    return await (await fetch(`${base}/winget/allowlist`)).json();
                case 'get_available_tools_metadata':
                    return await (await fetch(`${base}/tools_metadata`)).json();
                case 'get_chat_sessions':
                    return await (await fetch(`${base}/chat/sessions`)).json();
                case 'get_chat_session':
                    return await (await fetch(`${base}/chat/session/${encodeURIComponent(args[0])}`)).json();
                case 'create_chat_session':
                    return await (await fetch(`${base}/chat/session`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ agent_id: args[0], title: args[1] || null })
                    })).json();
                case 'delete_chat_session':
                    const delRes = await (await fetch(`${base}/chat/session/${encodeURIComponent(args[0])}`, {
                        method: 'DELETE'
                    })).json();
                    return delRes.success;
                case 'send_chat_message':
                    return await (await fetch(`${base}/chat/message`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: args[0], message: args[1] })
                    })).json();
                case 'get_save_preferences':
                    return await (await fetch(`${base}/settings/save-preferences`)).json();
                case 'set_save_preferences':
                    return await (await fetch(`${base}/settings/save-preferences`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ save_location: args[0], always_save: args[1], custom_path: args[2] || '' })
                    })).json();
                default:
                    console.warn(`Unhandled HTTP API method: ${method}`);
                    return null;
            }
        } catch (err) {
            console.error(`HTTP API call ${method} failed:`, err);
            this.mode = 'offline';
            return this._offlineCall(method, ...args);
        }
    }

    _offlineCall(method, ...args) {
        const DEFAULT_AGENTS = [
            { id: 'personal_assistant', name: 'Personal Assistant', description: 'Autonomous file management, system organization, web research, and daily workflow automation.', category: 'default', icon: 'home', color: 'green', status: 'active', allowed_tools: ['search_web', 'list_files', 'create_folder', 'move_file', 'search_and_read'] },
            { id: 'finance_agent', name: 'Finance Agent', description: 'Financial analysis, expense tracking, currency conversion, and portfolio audits.', category: 'default', icon: 'coins', color: 'purple', status: 'active', allowed_tools: ['search_web', 'search_and_read', 'create_excel_workbook'] },
            { id: 'work_agent', name: 'Work Agent', description: 'Executive brief generation, office reports, spreadsheet creation, and productivity automation.', category: 'default', icon: 'briefcase', color: 'blue', status: 'active', allowed_tools: ['search_web', 'read_webpage', 'create_word_report', 'create_excel_workbook'] },
            { id: 'health_agent', name: 'Health Agent', description: 'Wellness planning, symptom search, meal tracking, and health metrics analysis.', category: 'default', icon: 'heart', color: 'red', status: 'active', allowed_tools: ['search_web', 'read_webpage'] }
        ];

        if (method === 'get_agents') return DEFAULT_AGENTS;
        if (method === 'get_agent') return DEFAULT_AGENTS.find(a => a.id === args[0]) || null;
        if (method === 'get_template_agents') return [];
        if (method === 'get_system_status') return { app_name: 'DeskPilot', version: '2.0.0', status: 'offline' };
        if (method === 'get_chat_sessions') {
            try {
                const stored = localStorage.getItem('deskpilot_browser_chats');
                if (stored) return JSON.parse(stored);
            } catch (e) {}
            return [];
        }
        if (method === 'get_chat_session') {
            try {
                const stored = JSON.parse(localStorage.getItem('deskpilot_browser_chats') || '[]');
                return stored.find(s => s.id === args[0]) || null;
            } catch (e) { return null; }
        }
        if (method === 'create_chat_session') {
            const newSession = {
                id: 'chat_' + Math.random().toString(36).substring(2, 10),
                agent_id: args[0] || 'personal_assistant',
                title: args[1] || 'New Conversation',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: []
            };
            try {
                const stored = JSON.parse(localStorage.getItem('deskpilot_browser_chats') || '[]');
                stored.unshift(newSession);
                localStorage.setItem('deskpilot_browser_chats', JSON.stringify(stored));
            } catch (e) {}
            return newSession;
        }
        if (method === 'delete_chat_session') {
            try {
                let stored = JSON.parse(localStorage.getItem('deskpilot_browser_chats') || '[]');
                stored = stored.filter(s => s.id !== args[0]);
                localStorage.setItem('deskpilot_browser_chats', JSON.stringify(stored));
                return true;
            } catch (e) { return false; }
        }
        if (method === 'send_chat_message') {
            const sessionId = args[0];
            const text = args[1];

            // Inform the user clearly that Python backend is needed for real execution
            const offlineReply = `⚠️ **DeskPilot Python Backend Disconnected**\n\nReal desktop actions (such as generating actual **Excel spreadsheets (.xlsx)**, Word reports (.docx), web research, and file system operations) require the Python backend.\n\nTo enable live Amazon Bedrock and file creation, please run this in your terminal:\n\`\`\`bash\npython main.py        # Native Desktop App\n# OR\npython main.py --web  # Web Browser Mode (port 5000)\n\`\`\`\nOnce the command is running, refresh this page to execute real tools!`;

            setTimeout(() => {
                window.dispatchEvent(new CustomEvent('deskpilot:chat_chunk', {
                    detail: { session_id: sessionId, chunk: offlineReply }
                }));
                window.dispatchEvent(new CustomEvent('deskpilot:chat_turn_complete', {
                    detail: {
                        session_id: sessionId,
                        message: { role: 'assistant', content: offlineReply, tool_calls: [], deliverables: [] }
                    }
                }));
            }, 300);

            return { success: true, session_id: sessionId, status: 'processing' };
        }
        return null;
    }

    // ── API Methods (Section 11) ──────────────────────────────────────────────

    async getAgents() {
        return await this._call('get_agents') || [];
    }

    async getAgent(agentId) {
        return await this._call('get_agent', agentId);
    }

    async getTemplateAgents() {
        return await this._call('get_template_agents') || [];
    }

    async runAgentTask(agentId, instruction) {
        return await this._call('run_agent_task', agentId, instruction);
    }

    async stopAgentTask(taskId) {
        return await this._call('stop_agent_task', taskId);
    }

    async getTasks() {
        return await this._call('get_tasks') || [];
    }

    async respondApproval(requestId, approved, approveAll = false) {
        return await this._call('respond_to_approval', requestId, approved, approveAll);
    }

    async createAgentDraft(description) {
        return await this._call('create_agent_draft', description);
    }

    async confirmCreateAgent(draft) {
        return await this._call('confirm_create_agent', draft);
    }

    async deleteCustomAgent(agentId) {
        return await this._call('delete_custom_agent', agentId);
    }

    async getRecentActivity(limit = 10) {
        return await this._call('get_recent_activity', limit) || [];
    }

    async getAuditHistory(agentId = null) {
        return await this._call('get_audit_history', agentId) || [];
    }

    async getSystemStatus() {
        return await this._call('get_system_status') || {};
    }

    async openDeliverable(filePath) {
        return await this._call('open_deliverable', filePath);
    }

    async openFileLocation(filePath) {
        return await this._call('open_file_location', filePath);
    }

    async checkWingetInstalled() {
        return await this._call('check_winget_installed') || { available: false, path: '', message: 'Unknown' };
    }

    async getWingetAllowlist() {
        return await this._call('get_winget_allowlist') || [];
    }

    async getAvailableToolsMetadata() {
        return await this._call('get_available_tools_metadata') || [];
    }

    // ── Chat Sessions (ChatGPT/Gemini Style) ───────────────────────────────────

    async getChatSessions() {
        return await this._call('get_chat_sessions') || [];
    }

    async getChatSession(sessionId) {
        return await this._call('get_chat_session', sessionId);
    }

    async createChatSession(agentId, title = null) {
        return await this._call('create_chat_session', agentId, title);
    }

    async deleteChatSession(sessionId) {
        return await this._call('delete_chat_session', sessionId);
    }

    async sendChatMessage(sessionId, message) {
        return await this._call('send_chat_message', sessionId, message);
    }

    async getSavePreferences() {
        return await this._call('get_save_preferences') || { save_location: 'Desktop', always_save: true };
    }

    async setSavePreferences(saveLocation, alwaysSave = true, customPath = '') {
        return await this._call('set_save_preferences', saveLocation, alwaysSave, customPath);
    }

    // ── Event Bus ─────────────────────────────────────────────────────────────

    on(eventName, callback) {
        window.addEventListener(eventName, (e) => {
            callback(e.detail);
        });
    }
}

// Global instance available to frontend scripts
window.DeskPilot = new DeskPilotBridgeClient();
