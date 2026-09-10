/**
 * DeskPilot — Frontend Dashboard Controller
 * Powers the Multi-Agent Workspace, Navigation, Task Runner, and Custom Agent Builder.
 */

function initApp() {
    let currentAgentForTask = null;
    let currentPendingApproval = null;
    let currentBuilderDraft = null;
    let currentActiveView = 'home';
    let currentCategoryFilter = 'all';
    let taskTimerInterval = null;
    let taskStartTime = null;
    let lastGeneratedDeliverable = null;
    let currentChatSessionId = null;
    let currentChatAgentId = 'personal_assistant';
    let chatSessionsList = [];
    let isChatStreaming = false;
    let chatStreamAccumulator = '';
    let cachedAgents = [];

    // Agent Color Themes matching PROJECT_BRIEF Section 6 & 7
    const COLOR_THEMES = {
        'green': {
            cardClass: 'agent-card-personal',
            badgeBg: 'bg-emerald-500/15',
            badgeBorder: 'border-emerald-500/30',
            badgeText: 'text-emerald-400',
            dotBg: 'bg-emerald-400',
            defaultIcon: 'home'
        },
        'purple': {
            cardClass: 'agent-card-finance',
            badgeBg: 'bg-purple-500/15',
            badgeBorder: 'border-purple-500/30',
            badgeText: 'text-purple-400',
            dotBg: 'bg-purple-400',
            defaultIcon: 'coins'
        },
        'red': {
            cardClass: 'agent-card-health',
            badgeBg: 'bg-rose-500/15',
            badgeBorder: 'border-rose-500/30',
            badgeText: 'text-rose-400',
            dotBg: 'bg-rose-400',
            defaultIcon: 'heart'
        },
        'blue': {
            cardClass: 'agent-card-work',
            badgeBg: 'bg-blue-500/15',
            badgeBorder: 'border-blue-500/30',
            badgeText: 'text-blue-400',
            dotBg: 'bg-blue-400',
            defaultIcon: 'briefcase'
        },
        'indigo': {
            cardClass: 'agent-card-indigo',
            badgeBg: 'bg-indigo-500/15',
            badgeBorder: 'border-indigo-500/30',
            badgeText: 'text-indigo-400',
            dotBg: 'bg-indigo-400',
            defaultIcon: 'sparkles'
        },
        'amber': {
            cardClass: 'agent-card-amber',
            badgeBg: 'bg-amber-500/15',
            badgeBorder: 'border-amber-500/30',
            badgeText: 'text-amber-400',
            dotBg: 'bg-amber-400',
            defaultIcon: 'zap'
        }
    };

    const SUGGESTIONS_MAP = {
        'personal_assistant': [
            'Organize desktop files into categorized folders',
            'Research recent advances in quantum computing & create Word report',
            'Create a clean daily schedule template'
        ],
        'finance_agent': [
            'Create a monthly family budget spreadsheet in Excel',
            'Analyze freelance project margins and profit projections',
            'Research current top 5 high-yield savings interest rates'
        ],
        'health_agent': [
            'Create a 7-day balanced meal plan with grocery checklist',
            'Draft a 30-minute posture & stretching routine for desk workers',
            'Summarize evidence-based sleep hygiene guidelines'
        ],
        'work_agent': [
            'Research 5 competitors in SaaS project management and build a Word report',
            'Create a project milestone tracking workbook in Excel',
            'Audit and summarize key takeaways from documents on Desktop'
        ]
    };

    function getAgentTheme(agent) {
        if (!agent) return COLOR_THEMES['indigo'];
        const color = agent.color || 'indigo';
        const base = COLOR_THEMES[color] || COLOR_THEMES['indigo'];
        const agentId = agent.id || agent.agent_id || '';
        const suggestions = SUGGESTIONS_MAP[agentId] || [
            `Perform automated research and compile a summary`,
            `Analyze relevant data and create an organized report`,
            `Review workspace files and report key findings`
        ];
        return {
            ...base,
            icon: agent.icon || base.defaultIcon,
            suggestions: suggestions
        };
    }

    // ── 1. Initial Load & View Navigation ─────────────────────────────────────

    async function initDashboard() {
        console.log("Initializing DeskPilot dashboard...");
        setupNavigation();
        setupEventListeners();
        setupBridgeEvents();
        try {
            await loadAgents();
            await loadRecentActivity();
            await loadSavePreferences();
            refreshLucide();
        } catch (err) {
            console.error("Dashboard initialization error:", err);
        }
    }

    function refreshLucide() {
        if (window.lucide) {
            try { window.lucide.createIcons(); } catch (e) {}
        }
    }

    function setupNavigation() {
        const links = document.querySelectorAll('.sidebar-link');
        links.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const view = link.getAttribute('data-view') || 'home';
                switchView(view);
            });
        });
    }

    function switchView(viewName) {
        currentActiveView = viewName;

        // Update sidebar links
        document.querySelectorAll('.sidebar-link').forEach(link => {
            if (link.getAttribute('data-view') === viewName) {
                link.classList.add('active');
                link.classList.remove('text-slate-400');
            } else {
                link.classList.remove('active');
                link.classList.add('text-slate-400');
            }
        });

        // Toggle view containers
        const views = ['home', 'agents', 'chat', 'tasks', 'history', 'settings'];
        views.forEach(v => {
            const el = document.getElementById(`view-${v}`);
            if (el) {
                if (v === viewName) {
                    el.classList.remove('view-hidden');
                } else {
                    el.classList.add('view-hidden');
                }
            }
        });

        // Trigger view-specific data refresh
        if (viewName === 'agents') {
            loadCatalogAgents();
        } else if (viewName === 'chat') {
            initChatView();
        } else if (viewName === 'history') {
            refreshAuditHistory();
        } else if (viewName === 'home') {
            loadAgents();
            loadRecentActivity();
        }

        refreshLucide();
    }

    // ── 2. Data Fetching & Agent Rendering ────────────────────────────────────

    async function loadAgents() {
        const grid = document.getElementById('agents-grid');
        const sidebarList = document.getElementById('sidebar-agents-list');
        const badge = document.getElementById('active-agents-badge');

        if (!grid) return;

        let agents = [];
        try {
            agents = await window.DeskPilot.getAgents();
        } catch (e) {
            console.warn("Could not fetch agents from bridge:", e);
        }

        if (!agents || agents.length === 0 || agents.error) {
            grid.innerHTML = `
                <div class="col-span-full p-8 text-center bg-[#0E1526] rounded-2xl border border-amber-500/30">
                    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-semibold mb-3">
                        Desktop Shell Bridge Disconnected
                    </div>
                    <h4 class="text-sm font-bold text-white mb-2">Connect DeskPilot Desktop Shell</h4>
                    <p class="text-xs text-slate-400 max-w-md mx-auto mb-4">
                        To query the agent registry and execute Amazon Bedrock tasks, launch DeskPilot via the desktop shell:
                    </p>
                    <code class="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-mono text-indigo-300">python main.py</code>
                </div>
            `;
            return;
        }

        cachedAgents = agents;
        if (badge) badge.textContent = agents.length;

        // Populate Sidebar
        if (sidebarList) {
            sidebarList.innerHTML = agents.map(agent => {
                const theme = getAgentTheme(agent);
                const agentId = agent.id || agent.agent_id;
                return `
                    <div class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800/60 cursor-pointer transition-colors"
                         onclick="window.DeskPilotApp.openAgentChat('${agentId}')">
                        <span class="w-2 h-2 rounded-full ${theme.dotBg}"></span>
                        <span class="truncate">${agent.name}</span>
                    </div>
                `;
            }).join('');
        }

        // Populate Home Grid (4 default or active agents)
        grid.innerHTML = agents.map(agent => renderAgentCard(agent, false)).join('');
        refreshLucide();
    }

    async function loadCatalogAgents() {
        const grid = document.getElementById('catalog-agents-grid');
        const countAll = document.getElementById('count-agents-all');
        const countCustom = document.getElementById('count-agents-custom');
        if (!grid) return;

        let agents = [];
        try {
            agents = await window.DeskPilot.getAgents();
        } catch (e) {
            console.warn("Could not fetch agents:", e);
        }

        if (countAll) countAll.textContent = agents.length;
        const customCount = agents.filter(a => a.category === 'custom').length;
        if (countCustom) countCustom.textContent = customCount;

        let filtered = agents;
        if (currentCategoryFilter === 'default') {
            filtered = agents.filter(a => a.category === 'default');
        } else if (currentCategoryFilter === 'custom') {
            filtered = agents.filter(a => a.category === 'custom');
        }

        if (filtered.length === 0) {
            grid.innerHTML = `
                <div class="col-span-full p-12 text-center bg-[#0E1526] rounded-2xl border border-slate-800">
                    <i data-lucide="bot" class="w-10 h-10 text-slate-600 mx-auto mb-3"></i>
                    <h4 class="text-sm font-semibold text-white">No Custom Agents Found</h4>
                    <p class="text-xs text-slate-400 mt-1 mb-4">You haven't created any custom agents yet.</p>
                    <button onclick="window.DeskPilotApp.openBuilderModal()" class="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white">
                        + Create Your First Custom Agent
                    </button>
                </div>
            `;
            refreshLucide();
            return;
        }

        grid.innerHTML = filtered.map(agent => renderAgentCard(agent, true)).join('');
        refreshLucide();
    }

    function renderAgentCard(agent, isCatalogView = false) {
        const theme = getAgentTheme(agent);
        const agentId = agent.id || agent.agent_id;
        const toolCount = (agent.allowed_tools || []).length;
        const isCustom = agent.category === 'custom';

        const toolPreview = (agent.allowed_tools || []).slice(0, 3).map(t => {
            const cleanName = t.replace('_tools', '').replace('_', ' ');
            return `<span class="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 border border-slate-700/60 capitalize">${cleanName}</span>`;
        }).join('');

        return `
            <div class="agent-card ${theme.cardClass} bg-[#0E1526] border border-slate-800/80 rounded-2xl p-5 flex flex-col justify-between shadow-lg">
                <div>
                    <!-- Header: Icon, Name & Status -->
                    <div class="flex items-start justify-between mb-3.5">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-xl ${theme.badgeBg} border ${theme.badgeBorder} flex items-center justify-center ${theme.badgeText}">
                                <i data-lucide="${theme.icon}" class="w-5 h-5"></i>
                            </div>
                            <div>
                                <h4 class="font-bold text-white text-sm leading-tight">${agent.name}</h4>
                                <span class="text-[10px] text-slate-400 font-semibold tracking-wider">${agent.category === 'default' ? 'BUILT-IN' : agent.category.toUpperCase()} ASSISTANT</span>
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-semibold">
                            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Active
                        </div>
                    </div>

                    <!-- Description -->
                    <p class="text-xs text-slate-300 leading-relaxed mb-4 line-clamp-2">
                        ${agent.description}
                    </p>

                    <!-- Allowed Tools Badges -->
                    <div class="flex flex-wrap gap-1 mb-4">
                        ${toolPreview}
                        ${toolCount > 3 ? `<span class="px-1.5 py-0.5 rounded bg-slate-800/60 text-[10px] text-slate-400">+${toolCount - 3}</span>` : ''}
                    </div>
                </div>

                <!-- Footer Action Buttons -->
                <div class="pt-3.5 border-t border-slate-800/80 flex items-center gap-2">
                    <button onclick="window.DeskPilotApp.openAgentChat('${agentId}')"
                            class="flex-1 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all flex items-center justify-center gap-1.5">
                        <i data-lucide="message-square" class="w-3.5 h-3.5"></i> Chat
                    </button>
                    <button onclick="window.DeskPilotApp.openTaskModal('${agentId}')"
                            class="p-2 rounded-xl text-slate-300 hover:text-white hover:bg-slate-800 border border-slate-700/60 transition-all flex items-center justify-center"
                            title="Open Quick Task Modal">
                        <i data-lucide="play" class="w-3.5 h-3.5"></i>
                    </button>
                    ${isCatalogView && isCustom ? `
                    <button onclick="window.DeskPilotApp.deleteCustomAgent('${agentId}')"
                            class="p-2 rounded-xl text-rose-400 hover:text-rose-300 hover:bg-rose-500/15 border border-rose-500/30 transition-all"
                            title="Delete Custom Agent">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async function loadRecentActivity() {
        const feed = document.getElementById('activity-feed');
        if (!feed) return;

        let activity = [];
        try {
            activity = await window.DeskPilot.getRecentActivity(5);
        } catch (e) {
            console.warn("Could not fetch activity from bridge:", e);
        }

        if (activity && activity.length > 0) {
            feed.innerHTML = activity.map(item => `
                <div class="flex items-start gap-3.5 p-3 rounded-xl bg-slate-900/50 border border-slate-800/60 text-xs">
                    <div class="w-7 h-7 rounded-lg bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 flex-shrink-0 mt-0.5">
                        <i data-lucide="check" class="w-3.5 h-3.5"></i>
                    </div>
                    <div class="flex-1">
                        <div class="flex items-center justify-between">
                            <span class="font-semibold text-slate-200 capitalize">${(item.tool || item.action || 'Tool Action').replace(/_/g, ' ')}</span>
                            <span class="text-[10px] text-slate-500">${item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : 'Recent'}</span>
                        </div>
                        <p class="text-slate-400 mt-0.5 truncate">${item.summary || `Executed by ${item.agent_id || 'DeskPilot'}`}</p>
                    </div>
                </div>
            `).join('');
            refreshLucide();
        }
    }

    async function refreshAuditHistory() {
        const tbody = document.getElementById('audit-table-body');
        if (!tbody) return;

        let records = [];
        try {
            records = await window.DeskPilot.getAuditHistory();
        } catch (e) {
            console.warn("Could not fetch audit history:", e);
        }

        if (records.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-8 text-slate-500 font-sans text-xs">
                        No audit events recorded yet. Run an agent task to view live execution logs.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = records.map(r => {
            const isGreen = r.trust_tier === 'GREEN';
            const isRed = r.trust_tier === 'RED';
            const tierBadge = isGreen
                ? `<span class="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">GREEN</span>`
                : isRed
                ? `<span class="px-2 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/30 text-[10px] font-bold">RED</span>`
                : `<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 text-[10px] font-bold">YELLOW</span>`;

            const statusBadge = r.success
                ? `<span class="text-emerald-400 font-bold">✓ Success</span>`
                : `<span class="text-rose-400 font-bold">✗ Failed</span>`;

            return `
                <tr class="hover:bg-slate-900/40 transition-colors">
                    <td class="py-2.5 px-4 text-slate-400">${r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : '—'}</td>
                    <td class="py-2.5 px-4 font-semibold text-slate-200 font-sans">${r.agent_id || 'system'}</td>
                    <td class="py-2.5 px-4 text-indigo-300">${r.tool || 'unknown'}</td>
                    <td class="py-2.5 px-4">${tierBadge}</td>
                    <td class="py-2.5 px-4">${statusBadge}</td>
                    <td class="py-2.5 px-4 text-slate-400 max-w-xs truncate" title="${r.summary || ''}">${r.summary || '—'}</td>
                </tr>
            `;
        }).join('');
    }

    // ── 3. Task Runner Modal Controller ───────────────────────────────────────

    async function openTaskModal(agentId) {
        try {
            const res = await window.DeskPilot.getAgent(agentId);
            if (!res || !res.agent) return;
            const agent = res.agent;
            currentAgentForTask = agent;
            lastGeneratedDeliverable = null;

            const modal = document.getElementById('task-modal');
            const nameEl = document.getElementById('modal-agent-name');
            const roleEl = document.getElementById('modal-agent-role');
            const inputEl = document.getElementById('task-instruction-input');
            const suggestionsEl = document.getElementById('modal-suggestions-list');
            const liveBox = document.getElementById('task-live-box');
            const logStream = document.getElementById('task-log-stream');
            const deliverableCard = document.getElementById('task-deliverable-card');
            const iconEl = document.getElementById('modal-agent-icon');

            const theme = getAgentTheme(agent);
            if (iconEl) iconEl.setAttribute('data-lucide', theme.icon);

            nameEl.textContent = agent.name;
            roleEl.textContent = `${agent.category.toUpperCase()} ASSISTANT • Amazon Bedrock`;
            inputEl.value = '';
            liveBox.classList.add('hidden');
            if (deliverableCard) deliverableCard.classList.add('hidden');
            logStream.innerHTML = '';

            // Render suggestion chips
            suggestionsEl.innerHTML = (theme.suggestions || []).map(s => `
                <button type="button" class="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border border-slate-700/50 transition-colors text-left"
                        onclick="document.getElementById('task-instruction-input').value = '${s.replace(/'/g, "\\'")}'">
                    ${s}
                </button>
            `).join('');

            modal.classList.remove('modal-hidden');
            inputEl.focus();
            refreshLucide();
        } catch (err) {
            console.error("Error opening task modal:", err);
        }
    }

    function closeTaskModal() {
        const modal = document.getElementById('task-modal');
        modal.classList.add('modal-hidden');
        currentAgentForTask = null;
        clearInterval(taskTimerInterval);
    }

    async function submitTask() {
        if (!currentAgentForTask) return;
        const inputEl = document.getElementById('task-instruction-input');
        const instruction = inputEl.value.trim();

        if (!instruction) {
            alert("Please enter task instructions.");
            return;
        }

        const liveBox = document.getElementById('task-live-box');
        const logStream = document.getElementById('task-log-stream');
        const statusText = document.getElementById('task-status-text');
        const timerEl = document.getElementById('task-elapsed-timer');
        const submitBtn = document.getElementById('btn-submit-task');
        const deliverableCard = document.getElementById('task-deliverable-card');

        liveBox.classList.remove('hidden');
        if (deliverableCard) deliverableCard.classList.add('hidden');
        logStream.innerHTML = `<div class="text-slate-400">Initiating agent with Amazon Bedrock...</div>`;
        statusText.textContent = "Agent executing...";
        submitBtn.disabled = true;
        submitBtn.classList.add('opacity-50', 'cursor-not-allowed');

        // Start elapsed timer
        taskStartTime = Date.now();
        clearInterval(taskTimerInterval);
        taskTimerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - taskStartTime) / 1000);
            timerEl.textContent = `${elapsed}s`;
        }, 1000);

        const targetId = currentAgentForTask.id || currentAgentForTask.agent_id;
        try {
            const res = await window.DeskPilot.runAgentTask(targetId, instruction);
            if (!res.success) {
                logStream.innerHTML += `<div class="text-rose-400 mt-1">Failed to launch: ${res.error}</div>`;
                statusText.textContent = "Execution halted";
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                clearInterval(taskTimerInterval);
            }
        } catch (err) {
            logStream.innerHTML += `<div class="text-rose-400 mt-1">Error: ${err.message}</div>`;
            statusText.textContent = "Error";
            submitBtn.disabled = false;
            submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            clearInterval(taskTimerInterval);
        }
    }

    // ── 4. Deliverable File Opener ────────────────────────────────────────────

    function showDeliverable(filePath) {
        lastGeneratedDeliverable = filePath;
        const card = document.getElementById('task-deliverable-card');
        const nameEl = document.getElementById('deliverable-filename');
        if (!card || !nameEl) return;

        const parts = filePath.replace(/\\/g, '/').split('/');
        const filename = parts[parts.length - 1] || 'Deliverable';
        nameEl.textContent = filename;
        nameEl.setAttribute('title', filePath);

        card.classList.remove('hidden');
        refreshLucide();
    }

    async function openLastDeliverable() {
        if (!lastGeneratedDeliverable) return;
        try {
            const res = await window.DeskPilot.openDeliverable(lastGeneratedDeliverable);
            console.log("Opened deliverable:", res);
        } catch (e) {
            console.error("Error opening deliverable:", e);
        }
    }

    // ── 5. Custom Agent Builder (Section 9) ───────────────────────────────────

    function openBuilderModal() {
        const modal = document.getElementById('builder-modal');
        const step1 = document.getElementById('builder-step-1');
        const step2 = document.getElementById('builder-step-2');
        const inputDesc = document.getElementById('builder-input-desc');

        currentBuilderDraft = null;
        step1.classList.remove('hidden');
        step2.classList.add('hidden');
        inputDesc.value = '';

        modal.classList.remove('modal-hidden');
        inputDesc.focus();
        refreshLucide();
    }

    function closeBuilderModal() {
        document.getElementById('builder-modal').classList.add('modal-hidden');
        currentBuilderDraft = null;
    }

    async function generateDraft() {
        const inputDesc = document.getElementById('builder-input-desc');
        const desc = inputDesc.value.trim();
        if (!desc) {
            alert("Please describe what you want this agent to do.");
            return;
        }

        const genBtn = document.getElementById('btn-generate-draft');
        genBtn.disabled = true;
        genBtn.innerHTML = `<span class="animate-spin mr-1">⚙</span> Drafting with Bedrock...`;

        try {
            const res = await window.DeskPilot.createAgentDraft(desc);
            if (!res || !res.success || !res.draft) {
                alert(res ? `Could not draft agent: ${res.error || 'Unknown error'}` : "Desktop Shell Bridge Disconnected: Launch DeskPilot via 'python -m backend.app' to use Amazon Bedrock Custom Agent Builder.");
                return;
            }

            currentBuilderDraft = res.draft;
            const permissions = res.permissions || [];

            // Populate Step 2 Confirmation Fields
            document.getElementById('builder-draft-name').value = res.draft.name || '';
            document.getElementById('builder-draft-desc').value = res.draft.description || '';
            document.getElementById('builder-draft-persona').value = res.draft.persona || '';
            document.getElementById('builder-draft-color').value = res.draft.color || 'indigo';

            // Populate Plain-Language Permission Chips with Toggles
            const toolsList = document.getElementById('builder-tools-list');
            toolsList.innerHTML = permissions.map(p => {
                const isGreen = p.tier === 'GREEN';
                const isRed = p.tier === 'RED';
                const tierClass = isGreen
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                    : isRed
                    ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                    : 'bg-amber-500/15 text-amber-400 border-amber-500/30';

                return `
                    <label class="permission-chip flex items-center justify-between p-3 rounded-xl bg-slate-900 border border-slate-800 text-xs">
                        <div class="flex items-start gap-3">
                            <input type="checkbox" name="builder_tool" value="${p.tool}" checked
                                   class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 border-slate-700 bg-slate-800">
                            <div>
                                <div class="flex items-center gap-2">
                                    <span class="font-bold text-white">${p.title}</span>
                                    <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded border ${tierClass}">${p.tier}</span>
                                </div>
                                <p class="text-[11px] text-slate-400 mt-0.5">${p.description}</p>
                            </div>
                        </div>
                    </label>
                `;
            }).join('');

            // Transition to Step 2
            document.getElementById('builder-step-1').classList.add('hidden');
            document.getElementById('builder-step-2').classList.remove('hidden');
            refreshLucide();

        } catch (err) {
            console.error("Error generating draft:", err);
            alert(`Draft error: ${err.message}`);
        } finally {
            genBtn.disabled = false;
            genBtn.innerHTML = `<i data-lucide="wand-2" class="w-3.5 h-3.5"></i> Draft Agent with Bedrock`;
            refreshLucide();
        }
    }

    async function confirmSaveAgent() {
        if (!currentBuilderDraft) return;

        // Gather user edits from Step 2
        const name = document.getElementById('builder-draft-name').value.trim();
        const desc = document.getElementById('builder-draft-desc').value.trim();
        const persona = document.getElementById('builder-draft-persona').value.trim();
        const color = document.getElementById('builder-draft-color').value;

        // Gather checked tools
        const checkedTools = Array.from(document.querySelectorAll('input[name="builder_tool"]:checked'))
                                  .map(cb => cb.value);

        if (!name) {
            alert("Please enter an agent name.");
            return;
        }

        if (checkedTools.length === 0) {
            alert("Please select at least one tool permission for this agent.");
            return;
        }

        currentBuilderDraft.name = name;
        currentBuilderDraft.description = desc;
        currentBuilderDraft.persona = persona;
        currentBuilderDraft.color = color;
        currentBuilderDraft.allowed_tools = checkedTools;

        const confirmBtn = document.getElementById('btn-builder-confirm');
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = `<span class="animate-spin mr-1">⚙</span> Saving Agent...`;

        try {
            const res = await window.DeskPilot.confirmCreateAgent(currentBuilderDraft);
            if (!res.success) {
                alert(`Error saving agent: ${res.error}`);
                return;
            }

            closeBuilderModal();
            await loadAgents();
            await loadCatalogAgents();
            switchView('agents');
            alert(`🎉 Custom Agent '${res.agent.name}' created and activated!`);
        } catch (err) {
            console.error("Error saving custom agent:", err);
            alert(`Save error: ${err.message}`);
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i> Confirm & Activate Agent`;
            refreshLucide();
        }
    }

    async function deleteCustomAgent(agentId) {
        if (!confirm(`Are you sure you want to delete this custom agent?`)) return;

        try {
            const res = await window.DeskPilot.deleteCustomAgent(agentId);
            if (res.success) {
                await loadAgents();
                await loadCatalogAgents();
            } else {
                alert(`Could not delete agent: ${res.error}`);
            }
        } catch (e) {
            console.error("Error deleting agent:", e);
        }
    }

    // ── 6. Human-in-the-Loop Trust Approval Dialog ────────────────────────────

    function showApprovalModal(request) {
        currentPendingApproval = request;
        const modal = document.getElementById('approval-modal');
        const descEl = document.getElementById('approval-description');
        const agentEl = document.getElementById('approval-agent-name');
        const actionEl = document.getElementById('approval-action-name');
        const tierTag = document.getElementById('approval-tier-tag');

        descEl.textContent = request.description || "Confirmation required before performing this action.";
        agentEl.textContent = request.agent_id || "DeskPilot Agent";
        actionEl.textContent = request.action || "System Action";

        if (request.tier === 'RED') {
            tierTag.textContent = "RED TIER (HIGH RISK)";
            tierTag.className = "text-[10px] font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/40 uppercase";
        } else {
            tierTag.textContent = "YELLOW TIER (CONFIRMATION)";
            tierTag.className = "text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/40 uppercase";
        }

        modal.classList.remove('modal-hidden');
        refreshLucide();
    }

    async function respondApproval(approved, approveAll = false) {
        if (!currentPendingApproval) return;
        const modal = document.getElementById('approval-modal');
        modal.classList.add('modal-hidden');

        try {
            await window.DeskPilot.respondApproval(currentPendingApproval.request_id, approved, approveAll);
        } catch (e) {
            console.error("Error responding to approval:", e);
        }
        currentPendingApproval = null;
    }

    // ── 7. Template Gallery Modal ─────────────────────────────────────────────

    async function openTemplateGallery() {
        const modal = document.getElementById('templates-modal');
        const grid = document.getElementById('templates-grid');

        let templates = [];
        try {
            templates = await window.DeskPilot.getTemplateAgents();
        } catch (e) {
            console.warn("Could not fetch template agents:", e);
        }

        grid.innerHTML = templates.map(tmpl => `
            <div class="p-4 rounded-xl bg-slate-900/80 border border-slate-800 flex flex-col justify-between">
                <div>
                    <div class="flex items-center gap-2 mb-2">
                        <span class="w-2 h-2 rounded-full bg-indigo-400"></span>
                        <h4 class="font-bold text-white text-sm">${tmpl.name}</h4>
                    </div>
                    <p class="text-xs text-slate-300 mb-3">${tmpl.description}</p>
                    <div class="text-[10px] text-slate-400 space-y-1 mb-4">
                        <div><strong>Category:</strong> ${tmpl.category}</div>
                        <div><strong>Allowed Tools:</strong> ${(tmpl.allowed_tools || []).join(', ')}</div>
                    </div>
                </div>
                <button onclick="window.DeskPilotApp.addTemplateAgent('${tmpl.id || tmpl.agent_id}')"
                        class="w-full py-2 rounded-lg text-xs font-semibold bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 transition-colors flex items-center justify-center gap-1">
                    <i data-lucide="plus" class="w-3.5 h-3.5"></i> Add to Workspace
                </button>
            </div>
        `).join('');

        modal.classList.remove('modal-hidden');
        refreshLucide();
    }

    function closeTemplateGallery() {
        document.getElementById('templates-modal').classList.add('modal-hidden');
    }

    async function addTemplateAgent(agentId) {
        const templates = await window.DeskPilot.getTemplateAgents();
        const tmpl = templates.find(t => (t.id === agentId || t.agent_id === agentId));
        if (!tmpl) return;

        const res = await window.DeskPilot.confirmCreateAgent(tmpl);
        if (res.success) {
            closeTemplateGallery();
            await loadAgents();
            await loadCatalogAgents();
            await loadRecentActivity();
            alert(`Template '${tmpl.name}' added to your active agents!`);
        } else {
            alert(`Could not add template: ${res.error}`);
        }
    }

    // ── 7.5. Conversational Chat Controller (ChatGPT / Gemini Style) ──────────

    function renderChatMarkdown(text) {
        if (!text) return '';
        // Normalize literal '\n' to actual newlines if present
        let processed = text.replace(/\\n/g, '\n');

        // Extract thinking blocks before HTML escaping
        const thinkingBlocks = [];
        processed = processed.replace(/<thinking>([\s\S]*?)<\/thinking>/gi, (match, thought) => {
            const idx = thinkingBlocks.length;
            thinkingBlocks.push(thought.trim());
            return `\n\n__THINKING_BLOCK_${idx}__\n\n`;
        });

        // HTML escaping for security
        let escaped = processed
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Restore and render thinking blocks as collapsible accordion
        escaped = escaped.replace(/__THINKING_BLOCK_(\d+)__/g, (match, idx) => {
            const thought = thinkingBlocks[parseInt(idx, 10)] || '';
            const safeThought = thought.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            return `<details class="chat-thinking-details my-2.5 rounded-xl bg-slate-900/90 border border-indigo-500/20 p-2.5 text-xs transition-all">
                <summary class="cursor-pointer font-medium text-indigo-400 hover:text-indigo-300 flex items-center gap-1.5 select-none text-[11px]">
                    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse mr-1"></span>
                    <span>Agent Reasoning & Thought Process</span>
                </summary>
                <div class="mt-2 pl-2.5 border-l-2 border-indigo-500/40 text-[11px] text-slate-300 whitespace-pre-wrap font-mono leading-relaxed bg-black/20 p-2 rounded-r-lg">
                    ${safeThought}
                </div>
            </details>`;
        });

        // Code blocks: ```lang ... ```
        escaped = escaped.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre class="my-2.5 rounded-xl bg-slate-950 border border-slate-800 p-3 overflow-x-auto"><code class="text-xs font-mono text-indigo-300">${code.trim()}</code></pre>`;
        });

        // Inline code: `code`
        escaped = escaped.replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 rounded bg-slate-800 text-[11px] font-mono text-indigo-300">$1</code>');

        // Bold: **text**
        escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-white">$1</strong>');

        // Italic: *text*
        escaped = escaped.replace(/\*([^*]+)\*/g, '<em class="italic text-slate-300">$1</em>');

        // Headings: ### Heading
        escaped = escaped.replace(/^### (.*$)/gim, '<h5 class="font-bold text-white text-sm mt-3 mb-1">$1</h5>');
        escaped = escaped.replace(/^## (.*$)/gim, '<h4 class="font-bold text-white text-base mt-3 mb-1.5">$1</h4>');
        escaped = escaped.replace(/^# (.*$)/gim, '<h3 class="font-bold text-white text-lg mt-3 mb-2">$1</h3>');

        // Markdown Tables: matches contiguous lines starting and ending with |
        escaped = escaped.replace(/(?:^|\n)((?:\|.+?\|\s*(?:\n|$))+)/g, (match, tableBlock) => {
            const rawLines = tableBlock.trim().split('\n');
            const tableRows = rawLines.map(l => l.trim()).filter(l => l.startsWith('|') && l.endsWith('|'));
            if (tableRows.length < 2) return match;

            const headerCells = tableRows[0].slice(1, -1).split('|').map(c => c.trim());
            let startDataIdx = 1;
            if (tableRows.length > 1 && /^\|[\s\-:]+(\|[\s\-:]+)+\|$/.test(tableRows[1])) {
                startDataIdx = 2;
            }

            const headerHtml = `<tr>${headerCells.map(h => `<th class="px-3.5 py-2.5 text-left font-semibold text-indigo-300 tracking-wider text-[11px]">${h}</th>`).join('')}</tr>`;

            const bodyRowsHtml = tableRows.slice(startDataIdx).map((rowStr, rIdx) => {
                const cells = rowStr.slice(1, -1).split('|').map(c => c.trim());
                const bgClass = rIdx % 2 === 0 ? 'bg-slate-900/40' : 'bg-transparent';
                const cellsHtml = cells.map(c => `<td class="px-3.5 py-2 text-slate-200 border-t border-slate-800/60">${c}</td>`).join('');
                return `<tr class="${bgClass} hover:bg-slate-800/40 transition-colors">${cellsHtml}</tr>`;
            }).join('');

            return `\n<div class="my-3 overflow-x-auto rounded-xl border border-slate-800 bg-[#0B1120] shadow-sm"><table class="w-full text-xs text-left border-collapse"><thead class="bg-slate-900/90 border-b border-slate-800">${headerHtml}</thead><tbody>${bodyRowsHtml}</tbody></table></div>\n`;
        });

        // Bullet lists: - item or * item
        escaped = escaped.replace(/^\s*[-*]\s+(.*)$/gim, '<li class="ml-4 list-disc text-slate-200 text-xs mb-1">$1</li>');

        // Numbered lists: 1. item
        escaped = escaped.replace(/^\s*(\d+)\.\s+(.*)$/gim, '<li class="ml-4 list-decimal text-slate-200 text-xs mb-1">$2</li>');

        // Lines to paragraphs
        const paragraphs = escaped.split(/\n\n+/);
        return paragraphs.map(p => {
            const trimmed = p.trim();
            if (
                trimmed.startsWith('<pre') ||
                trimmed.startsWith('<h') ||
                trimmed.startsWith('<li') ||
                trimmed.startsWith('<div') ||
                trimmed.startsWith('<details')
            ) {
                return trimmed;
            }
            return `<p class="mb-2 leading-relaxed text-slate-200 text-xs">${trimmed.replace(/\n/g, '<br>')}</p>`;
        }).join('');
    }

    async function initChatView() {
        console.log("Initializing Conversational Chat Workspace...");

        // Ensure cachedAgents are populated
        if (!cachedAgents || cachedAgents.length === 0) {
            try {
                cachedAgents = await window.DeskPilot.getAgents() || [];
            } catch (e) {
                cachedAgents = [];
            }
        }

        // Populate Agent Select Dropdown
        const select = document.getElementById('chat-agent-select');
        if (select && cachedAgents.length > 0) {
            select.innerHTML = cachedAgents.map(a => {
                const aId = a.id || a.agent_id;
                const selected = aId === currentChatAgentId ? 'selected' : '';
                return `<option value="${aId}" ${selected}>${a.name}</option>`;
            }).join('');
        }

        // Set up Chat Input Auto-Resize & Submit handlers
        const textarea = document.getElementById('chat-input-textarea');
        const sendBtn = document.getElementById('btn-send-chat');
        const newChatBtn = document.getElementById('btn-new-chat');
        const deleteChatBtn = document.getElementById('btn-delete-current-chat');
        const searchInput = document.getElementById('chat-search-input');

        if (textarea && !textarea.dataset.wired) {
            textarea.dataset.wired = "true";
            textarea.addEventListener('input', function() {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 140) + 'px';
            });
            textarea.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendChatMessage();
                }
            });
        }

        if (sendBtn && !sendBtn.dataset.wired) {
            sendBtn.dataset.wired = "true";
            sendBtn.addEventListener('click', sendChatMessage);
        }

        if (newChatBtn && !newChatBtn.dataset.wired) {
            newChatBtn.dataset.wired = "true";
            newChatBtn.addEventListener('click', () => startNewChat());
        }

        if (deleteChatBtn && !deleteChatBtn.dataset.wired) {
            deleteChatBtn.dataset.wired = "true";
            deleteChatBtn.addEventListener('click', () => deleteCurrentChat());
        }

        if (searchInput && !searchInput.dataset.wired) {
            searchInput.dataset.wired = "true";
            searchInput.addEventListener('input', filterChatSessions);
        }

        if (select && !select.dataset.wired) {
            select.dataset.wired = "true";
            select.addEventListener('change', (e) => {
                currentChatAgentId = e.target.value;
                updateChatHeader();
                startNewChat(currentChatAgentId);
            });
        }

        await loadChatSessions();
        refreshLucide();
    }

    async function loadChatSessions() {
        const listContainer = document.getElementById('chat-sessions-list');
        const countBadge = document.getElementById('chat-session-count');
        if (!listContainer) return;

        try {
            chatSessionsList = await window.DeskPilot.getChatSessions() || [];
        } catch (e) {
            chatSessionsList = [];
        }

        if (countBadge) countBadge.textContent = chatSessionsList.length;

        if (chatSessionsList.length === 0) {
            listContainer.innerHTML = `
                <div class="p-4 text-center text-slate-500 text-xs">
                    <p>No recent conversations.</p>
                    <p class="text-[10px] mt-1 text-slate-600">Click "+ New Chat" to start.</p>
                </div>
            `;
            if (!currentChatSessionId) {
                await startNewChat(currentChatAgentId);
            }
            return;
        }

        renderSessionListItems(chatSessionsList);

        if (!currentChatSessionId || !chatSessionsList.some(s => s.id === currentChatSessionId)) {
            await selectChatSession(chatSessionsList[0].id);
        } else {
            updateActiveSessionHighlight();
        }
    }

    function renderSessionListItems(sessions) {
        const listContainer = document.getElementById('chat-sessions-list');
        if (!listContainer) return;

        listContainer.innerHTML = sessions.map(s => {
            const agent = cachedAgents.find(a => (a.id === s.agent_id || a.agent_id === s.agent_id));
            const theme = getAgentTheme(agent);
            const isActive = s.id === currentChatSessionId;
            const timeSnippet = s.updated_at ? new Date(s.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

            return `
                <div class="chat-session-item group flex items-center justify-between p-2.5 rounded-xl border ${isActive ? 'active border-indigo-500/40 bg-indigo-600/15' : 'border-transparent hover:bg-slate-800/40'} text-xs"
                     onclick="window.DeskPilotApp.selectChatSession('${s.id}')">
                    <div class="flex items-center gap-2.5 overflow-hidden flex-1 mr-2">
                        <span class="w-2 h-2 rounded-full ${theme.dotBg} flex-shrink-0"></span>
                        <div class="overflow-hidden">
                            <h5 class="font-semibold text-slate-200 truncate leading-tight">${s.title || 'Conversation'}</h5>
                            <span class="text-[10px] text-slate-400 block truncate">${agent ? agent.name : 'Assistant'} • ${timeSnippet}</span>
                        </div>
                    </div>
                    <button class="delete-session-btn p-1 rounded hover:bg-slate-700/60 text-slate-400 hover:text-rose-400 transition-colors flex-shrink-0"
                            onclick="event.stopPropagation(); window.DeskPilotApp.deleteChatSession('${s.id}')"
                            title="Delete Chat">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
        }).join('');
        refreshLucide();
    }

    function filterChatSessions() {
        const query = (document.getElementById('chat-search-input')?.value || '').toLowerCase().trim();
        if (!query) {
            renderSessionListItems(chatSessionsList);
            return;
        }
        const filtered = chatSessionsList.filter(s =>
            (s.title || '').toLowerCase().includes(query) ||
            (s.last_message || '').toLowerCase().includes(query) ||
            (s.agent_id || '').toLowerCase().includes(query)
        );
        renderSessionListItems(filtered);
    }

    async function selectChatSession(sessionId) {
        currentChatSessionId = sessionId;
        updateActiveSessionHighlight();

        const messagesContainer = document.getElementById('chat-messages-container');
        if (!messagesContainer) return;

        messagesContainer.innerHTML = `
            <div class="flex items-center justify-center p-12 text-slate-500 text-xs gap-2">
                <span class="animate-spin text-indigo-400">⚙</span> Loading conversation...
            </div>
        `;

        let session = null;
        try {
            session = await window.DeskPilot.getChatSession(sessionId);
        } catch (e) {
            console.error("Failed to load chat session:", e);
        }

        if (!session) {
            messagesContainer.innerHTML = `<div class="p-8 text-center text-rose-400 text-xs">Could not load session.</div>`;
            return;
        }

        currentChatAgentId = session.agent_id || 'personal_assistant';
        const select = document.getElementById('chat-agent-select');
        if (select) select.value = currentChatAgentId;

        updateChatHeader();

        const messages = session.messages || [];
        if (messages.length === 0) {
            renderChatEmptyState(messagesContainer);
        } else {
            renderChatMessages(messagesContainer, messages);
        }

        scrollChatToBottom();
        refreshLucide();
    }

    function updateActiveSessionHighlight() {
        document.querySelectorAll('.chat-session-item').forEach(item => {
            const onclickStr = item.getAttribute('onclick') || '';
            if (onclickStr.includes(currentChatSessionId)) {
                item.classList.add('active', 'border-indigo-500/40', 'bg-indigo-600/15');
                item.classList.remove('border-transparent');
            } else {
                item.classList.remove('active', 'border-indigo-500/40', 'bg-indigo-600/15');
                item.classList.add('border-transparent');
            }
        });
    }

    function updateChatHeader() {
        const agent = cachedAgents.find(a => (a.id === currentChatAgentId || a.agent_id === currentChatAgentId));
        const theme = getAgentTheme(agent);

        const avatar = document.getElementById('chat-header-avatar');
        const desc = document.getElementById('chat-agent-description');
        const suggestionsBox = document.getElementById('chat-quick-suggestions');

        if (avatar && agent) {
            avatar.className = `w-8 h-8 rounded-lg ${theme.badgeBg} border ${theme.badgeBorder} flex items-center justify-center ${theme.badgeText}`;
            avatar.innerHTML = `<i data-lucide="${theme.icon}" class="w-4 h-4"></i>`;
        }

        if (desc && agent) {
            desc.textContent = agent.description;
        }

        if (suggestionsBox && theme.suggestions) {
            suggestionsBox.innerHTML = theme.suggestions.map(s => `
                <button class="chat-prompt-chip whitespace-nowrap px-3 py-1 rounded-full bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/60 transition-colors flex-shrink-0"
                        onclick="window.DeskPilotApp.applyChatPrompt('${s.replace(/'/g, "\\'")}')">
                    ${s}
                </button>
            `).join('');
        }
        refreshLucide();
    }

    function renderChatEmptyState(container) {
        const agent = cachedAgents.find(a => (a.id === currentChatAgentId || a.agent_id === currentChatAgentId));
        const theme = getAgentTheme(agent);
        const name = agent ? agent.name : 'Personal Assistant';
        const desc = agent ? agent.description : 'Your autonomous multi-agent assistant.';

        container.innerHTML = `
            <div class="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12">
                <div class="w-14 h-14 rounded-2xl ${theme.badgeBg} border ${theme.badgeBorder} flex items-center justify-center ${theme.badgeText} mb-4 shadow-xl">
                    <i data-lucide="${theme.icon}" class="w-7 h-7"></i>
                </div>
                <h3 class="text-lg font-bold text-white mb-1.5">How can ${name} help you today?</h3>
                <p class="text-xs text-slate-400 mb-6 leading-relaxed">${desc}</p>

                <div class="w-full grid grid-cols-1 gap-2 text-left">
                    ${(theme.suggestions || []).map(s => `
                        <div class="p-3 rounded-xl bg-[#0E1526] hover:bg-slate-800/80 border border-slate-800 hover:border-indigo-500/40 cursor-pointer transition-all flex items-center justify-between group"
                             onclick="window.DeskPilotApp.applyChatPrompt('${s.replace(/'/g, "\\'")}')">
                            <span class="text-xs text-slate-300 group-hover:text-white">${s}</span>
                            <i data-lucide="arrow-right" class="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400 transition-colors"></i>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        refreshLucide();
    }

    function renderChatMessages(container, messages) {
        container.innerHTML = messages.map(m => {
            if (m.role === 'user') {
                return `
                    <div class="flex items-start justify-end gap-3">
                        <div class="max-w-2xl chat-bubble-user p-4 text-white text-xs leading-relaxed">
                            ${m.content.replace(/\n/g, '<br>')}
                        </div>
                        <div class="w-8 h-8 rounded-lg bg-indigo-700 border border-indigo-500/40 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 shadow-md">
                            DP
                        </div>
                    </div>
                `;
            } else {
                const agent = cachedAgents.find(a => (a.id === currentChatAgentId || a.agent_id === currentChatAgentId));
                const theme = getAgentTheme(agent);
                const toolPills = (m.tool_calls || []).map(t => `
                    <span class="chat-tool-step-chip inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] text-indigo-300">
                        <i data-lucide="check" class="w-3 h-3 text-emerald-400"></i> ${t}
                    </span>
                `).join('');

                const deliverableCards = (m.deliverables || []).map(d => {
                    const filename = d.split('\\').pop().split('/').pop();
                    return `
                        <div class="mt-3 p-3 rounded-xl deliverable-card flex items-center justify-between">
                            <div class="flex items-center gap-2.5 overflow-hidden">
                                <div class="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 flex-shrink-0">
                                    <i data-lucide="file-check" class="w-4 h-4"></i>
                                </div>
                                <div class="overflow-hidden">
                                    <h5 class="text-xs font-bold text-white truncate">${filename}</h5>
                                    <span class="text-[10px] text-indigo-300/80 font-mono">Deliverable Ready</span>
                                </div>
                            </div>
                            <button onclick="window.DeskPilotApp.openDeliverablePath('${d.replace(/\\/g, '\\\\')}')"
                                    class="px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow transition-colors flex items-center gap-1">
                                <i data-lucide="external-link" class="w-3 h-3"></i> Open File
                            </button>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="flex items-start gap-3">
                        <div class="w-8 h-8 rounded-lg ${theme.badgeBg} border ${theme.badgeBorder} flex items-center justify-center ${theme.badgeText} flex-shrink-0 shadow-md">
                            <i data-lucide="${theme.icon}" class="w-4 h-4"></i>
                        </div>
                        <div class="max-w-3xl chat-bubble-assistant p-4 text-xs text-slate-200 flex-1 overflow-hidden">
                            <div class="flex items-center gap-2 mb-2">
                                <span class="font-bold text-white text-xs">${agent ? agent.name : 'DeskPilot Assistant'}</span>
                                <span class="text-[10px] text-slate-400">${m.timestamp ? new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                            </div>
                            ${toolPills ? `<div class="flex flex-wrap gap-1.5 mb-2.5">${toolPills}</div>` : ''}
                            <div class="chat-markdown leading-relaxed">
                                ${renderChatMarkdown(m.content)}
                            </div>
                            ${deliverableCards}
                        </div>
                    </div>
                `;
            }
        }).join('');
    }

    async function startNewChat(agentId = null) {
        const targetAgent = agentId || currentChatAgentId || 'personal_assistant';
        currentChatAgentId = targetAgent;

        const res = await window.DeskPilot.createChatSession(targetAgent, "New Conversation");
        if (res && res.id) {
            currentChatSessionId = res.id;
            await loadChatSessions();
            await selectChatSession(res.id);

            const textarea = document.getElementById('chat-input-textarea');
            if (textarea) textarea.focus();
        }
    }

    async function deleteCurrentChat(sessionId = null) {
        const targetId = sessionId || currentChatSessionId;
        if (!targetId) return;

        const confirmed = confirm("Are you sure you want to delete this conversation?");
        if (!confirmed) return;

        await window.DeskPilot.deleteChatSession(targetId);
        currentChatSessionId = null;
        await loadChatSessions();
    }

    async function openAgentChat(agentId) {
        currentChatAgentId = agentId;
        switchView('chat');
        await startNewChat(agentId);
    }

    async function sendChatMessage() {
        const textarea = document.getElementById('chat-input-textarea');
        const sendBtn = document.getElementById('btn-send-chat');
        if (!textarea || isChatStreaming) return;

        const text = textarea.value.trim();
        if (!text) return;

        if (!currentChatSessionId) {
            await startNewChat(currentChatAgentId);
        }

        textarea.value = '';
        textarea.style.height = 'auto';

        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        if (container.querySelector('.chat-prompt-chip') || container.querySelector('h3')) {
            container.innerHTML = '';
        }

        const userBubble = document.createElement('div');
        userBubble.className = "flex items-start justify-end gap-3";
        userBubble.innerHTML = `
            <div class="max-w-2xl chat-bubble-user p-4 text-white text-xs leading-relaxed">
                ${text.replace(/\n/g, '<br>')}
            </div>
            <div class="w-8 h-8 rounded-lg bg-indigo-700 border border-indigo-500/40 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 shadow-md">
                DP
            </div>
        `;
        container.appendChild(userBubble);

        const agent = cachedAgents.find(a => (a.id === currentChatAgentId || a.agent_id === currentChatAgentId));
        const theme = getAgentTheme(agent);

        const assistantBubble = document.createElement('div');
        assistantBubble.id = "active-streaming-bubble";
        assistantBubble.className = "flex items-start gap-3";
        assistantBubble.innerHTML = `
            <div class="w-8 h-8 rounded-lg ${theme.badgeBg} border ${theme.badgeBorder} flex items-center justify-center ${theme.badgeText} flex-shrink-0 shadow-md">
                <i data-lucide="${theme.icon}" class="w-4 h-4"></i>
            </div>
            <div class="max-w-3xl chat-bubble-assistant p-4 text-xs text-slate-200 flex-1">
                <div class="flex items-center gap-2 mb-2">
                    <span class="font-bold text-white text-xs">${agent ? agent.name : 'DeskPilot Assistant'}</span>
                    <span class="text-[10px] text-slate-400">Just now</span>
                </div>
                <div id="streaming-tool-steps" class="flex flex-wrap gap-1.5 mb-2"></div>
                <div id="streaming-content" class="chat-markdown leading-relaxed">
                    <span class="inline-flex items-center gap-1.5 text-slate-400">
                        <span class="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span> Thinking...
                    </span>
                </div>
            </div>
        `;
        container.appendChild(assistantBubble);
        scrollChatToBottom();
        refreshLucide();

        isChatStreaming = true;
        chatStreamAccumulator = '';
        if (sendBtn) sendBtn.disabled = true;

        const livePill = document.getElementById('chat-tool-live-pill');
        const liveText = document.getElementById('chat-tool-live-text');
        if (livePill && liveText) {
            livePill.classList.remove('hidden');
            liveText.textContent = "Consulting Amazon Bedrock...";
        }

        try {
            await window.DeskPilot.sendChatMessage(currentChatSessionId, text);
        } catch (e) {
            console.error("Failed to send chat message:", e);
            if (livePill) livePill.classList.add('hidden');
            const contentEl = document.getElementById('streaming-content');
            if (contentEl) contentEl.innerHTML = `<span class="text-rose-400">Failed to send message: ${e.message}</span>`;
            isChatStreaming = false;
            if (sendBtn) sendBtn.disabled = false;
        }
    }

    function scrollChatToBottom() {
        const container = document.getElementById('chat-messages-container');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    // ── 8. Bridge Event Streaming Listeners ───────────────────────────────────

    function setupBridgeEvents() {
        window.DeskPilot.on('deskpilot:step', (data) => {
            const logStream = document.getElementById('task-log-stream');
            if (logStream) {
                const entry = document.createElement('div');
                entry.className = 'text-indigo-300 text-[11px]';
                entry.textContent = `▶ [${data.tool || 'Action'}] ${data.message || ''}`;
                logStream.appendChild(entry);
                logStream.scrollTop = logStream.scrollHeight;
            }
        });

        window.DeskPilot.on('deskpilot:log', (data) => {
            const logStream = document.getElementById('task-log-stream');
            if (logStream && data.text) {
                // Check if log mentions a saved file
                const fileMatch = data.text.match(/(?:saved|created|written to):\s*([a-zA-Z]:[^\r\n]+\.(?:docx|xlsx|pdf|png|csv))/i);
                if (fileMatch && fileMatch[1]) {
                    showDeliverable(fileMatch[1].trim());
                }

                const entry = document.createElement('div');
                entry.className = 'text-slate-300 text-[11px]';
                entry.textContent = data.text;
                logStream.appendChild(entry);
                logStream.scrollTop = logStream.scrollHeight;
            }
        });

        window.DeskPilot.on('deskpilot:task_complete', (data) => {
            const logStream = document.getElementById('task-log-stream');
            const statusText = document.getElementById('task-status-text');
            const submitBtn = document.getElementById('btn-submit-task');

            clearInterval(taskTimerInterval);
            if (statusText) statusText.textContent = "Task Complete ✓";
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
            if (logStream) {
                const entry = document.createElement('div');
                entry.className = 'text-emerald-400 font-semibold mt-1';
                entry.textContent = `✓ Task finished successfully.`;
                logStream.appendChild(entry);
                logStream.scrollTop = logStream.scrollHeight;
            }

            // Check summary for deliverable path
            if (data.summary) {
                const fileMatch = data.summary.match(/([a-zA-Z]:[^\s\r\n]+\.(?:docx|xlsx|pdf|png|csv))/i);
                if (fileMatch && fileMatch[1]) {
                    showDeliverable(fileMatch[1].trim());
                }
            }

            loadRecentActivity();
        });

        window.DeskPilot.on('deskpilot:task_failed', (data) => {
            const logStream = document.getElementById('task-log-stream');
            const statusText = document.getElementById('task-status-text');
            const submitBtn = document.getElementById('btn-submit-task');

            clearInterval(taskTimerInterval);
            if (statusText) statusText.textContent = "Task Failed ✗";
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
            if (logStream) {
                const entry = document.createElement('div');
                entry.className = 'text-rose-400 font-semibold mt-1';
                entry.textContent = `✗ ${data.error || 'Execution failed'}`;
                logStream.appendChild(entry);
                logStream.scrollTop = logStream.scrollHeight;
            }
        });

        window.DeskPilot.on('deskpilot:approval_required', (request) => {
            showApprovalModal(request);
        });

        // ── Chat Streaming Event Listeners ────────────────────────────────────
        window.DeskPilot.on('deskpilot:chat_user_message', (data) => {
            if (data && data.session_id === currentChatSessionId) {
                if (data.title) {
                    const activeTitle = document.getElementById('chat-active-title');
                    if (activeTitle) activeTitle.textContent = data.title;
                }
                loadChatSessions();
            }
        });

        window.DeskPilot.on('deskpilot:chat_step', (data) => {
            if (data && data.session_id === currentChatSessionId) {
                const livePill = document.getElementById('chat-tool-live-pill');
                const liveText = document.getElementById('chat-tool-live-text');
                if (livePill && liveText) {
                    livePill.classList.remove('hidden');
                    liveText.textContent = `Tool: ${data.tool || 'Action'} (${data.status || 'running'})...`;
                }

                const toolSteps = document.getElementById('streaming-tool-steps');
                if (toolSteps) {
                    const stepChip = document.createElement('span');
                    stepChip.className = 'chat-tool-step-chip inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] text-indigo-300 animate-pulse';
                    stepChip.innerHTML = `<i data-lucide="wrench" class="w-3 h-3 text-indigo-400"></i> ${data.tool || 'Tool'} (${data.status || 'running'})`;
                    toolSteps.appendChild(stepChip);
                    refreshLucide();
                    scrollChatToBottom();
                }
            }
        });

        window.DeskPilot.on('deskpilot:chat_chunk', (data) => {
            if (data && data.session_id === currentChatSessionId) {
                const contentEl = document.getElementById('streaming-content');
                if (contentEl) {
                    if (!chatStreamAccumulator) {
                        contentEl.innerHTML = '';
                    }
                    chatStreamAccumulator += (data.chunk || '');
                    contentEl.innerHTML = renderChatMarkdown(chatStreamAccumulator);
                    scrollChatToBottom();
                }
            }
        });

        window.DeskPilot.on('deskpilot:chat_turn_complete', async (data) => {
            if (data && data.session_id === currentChatSessionId) {
                chatStreamAccumulator = '';
                isChatStreaming = false;
                const sendBtn = document.getElementById('btn-send-chat');
                if (sendBtn) sendBtn.disabled = false;

                const livePill = document.getElementById('chat-tool-live-pill');
                if (livePill) livePill.classList.add('hidden');

                await selectChatSession(currentChatSessionId);
                await loadChatSessions();
            }
        });

        window.DeskPilot.on('deskpilot:chat_turn_failed', (data) => {
            if (data && data.session_id === currentChatSessionId) {
                chatStreamAccumulator = '';
                isChatStreaming = false;
                const sendBtn = document.getElementById('btn-send-chat');
                if (sendBtn) sendBtn.disabled = false;

                const livePill = document.getElementById('chat-tool-live-pill');
                if (livePill) livePill.classList.add('hidden');

                const contentEl = document.getElementById('streaming-content');
                if (contentEl) {
                    contentEl.innerHTML = `<div class="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
                        <i data-lucide="alert-circle" class="w-4 h-4 text-rose-400 flex-shrink-0"></i>
                        <span>${data.error || 'Turn execution failed'}</span>
                    </div>`;
                    refreshLucide();
                }
            }
        });
    }

    // ── 9. Setup Event Listeners ──────────────────────────────────────────────

    function setupEventListeners() {
        // Modal Controls
        document.getElementById('btn-close-task-modal')?.addEventListener('click', closeTaskModal);
        document.getElementById('btn-cancel-task')?.addEventListener('click', closeTaskModal);
        document.getElementById('btn-submit-task')?.addEventListener('click', submitTask);
        document.getElementById('btn-open-deliverable')?.addEventListener('click', openLastDeliverable);

        // Approval Buttons
        document.getElementById('btn-confirm-approval')?.addEventListener('click', () => respondApproval(true, false));
        document.getElementById('btn-approve-all')?.addEventListener('click', () => respondApproval(true, true));
        document.getElementById('btn-deny-approval')?.addEventListener('click', () => respondApproval(false, false));

        // Template Gallery
        document.getElementById('btn-template-gallery')?.addEventListener('click', openTemplateGallery);
        document.getElementById('btn-close-templates-modal')?.addEventListener('click', closeTemplateGallery);

        // Custom Agent Builder Controls
        document.getElementById('btn-create-agent')?.addEventListener('click', openBuilderModal);
        document.getElementById('btn-close-builder-modal')?.addEventListener('click', closeBuilderModal);
        document.getElementById('btn-cancel-builder')?.addEventListener('click', closeBuilderModal);
        document.getElementById('btn-generate-draft')?.addEventListener('click', generateDraft);
        document.getElementById('btn-builder-back')?.addEventListener('click', () => {
            document.getElementById('builder-step-2').classList.add('hidden');
            document.getElementById('builder-step-1').classList.remove('hidden');
            refreshLucide();
        });
        document.getElementById('btn-builder-confirm')?.addEventListener('click', confirmSaveAgent);

        // Starter Chips in Builder
        document.querySelectorAll('.builder-starter-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const prompt = chip.getAttribute('data-prompt');
                const textarea = document.getElementById('builder-input-desc');
                if (textarea && prompt) {
                    textarea.value = prompt;
                    textarea.focus();
                }
            });
        });
    }

    // ── 7.8 Save Location Preferences Controller ──────────────────────────────
    let currentSavePreferences = { save_location: 'Desktop', always_save: true, custom_path: '' };

    async function loadSavePreferences() {
        try {
            if (window.DeskPilot && window.DeskPilot.getSavePreferences) {
                currentSavePreferences = await window.DeskPilot.getSavePreferences() || currentSavePreferences;
            }
        } catch (e) {
            console.warn("Failed to load save preferences:", e);
        }
        updateSaveLocationHeaderLabel();
    }

    function updateSaveLocationHeaderLabel() {
        const label = document.getElementById('header-save-loc-label');
        if (label) {
            label.textContent = currentSavePreferences.save_location || 'Desktop';
        }
    }

    function openSaveLocationModal() {
        const modal = document.getElementById('save-location-modal');
        if (!modal) return;

        // Sync current radio
        const radios = modal.querySelectorAll('input[name="save_dest_option"]');
        radios.forEach(r => {
            r.checked = (r.value === currentSavePreferences.save_location);
        });

        // Sync always save checkbox
        const chk = document.getElementById('chk-always-save-there');
        if (chk) {
            chk.checked = currentSavePreferences.always_save !== false;
        }

        modal.classList.remove('modal-hidden');
        refreshLucide();
    }

    function closeSaveLocationModal() {
        const modal = document.getElementById('save-location-modal');
        if (modal) modal.classList.add('modal-hidden');
    }

    async function saveLocationPreferencesSubmit() {
        const modal = document.getElementById('save-location-modal');
        if (!modal) return;

        const selectedRadio = modal.querySelector('input[name="save_dest_option"]:checked');
        const saveLocation = selectedRadio ? selectedRadio.value : 'Desktop';

        const chk = document.getElementById('chk-always-save-there');
        const alwaysSave = chk ? chk.checked : true;

        try {
            if (window.DeskPilot && window.DeskPilot.setSavePreferences) {
                currentSavePreferences = await window.DeskPilot.setSavePreferences(saveLocation, alwaysSave, '') || {
                    save_location: saveLocation,
                    always_save: alwaysSave
                };
            } else {
                currentSavePreferences = { save_location: saveLocation, always_save: alwaysSave };
            }
            updateSaveLocationHeaderLabel();
            closeSaveLocationModal();
            alert(`File destination preference saved: ${saveLocation} (${alwaysSave ? 'Always save there' : 'Ask each time'})`);
        } catch (e) {
            console.error("Failed to save preferences:", e);
            alert(`Could not save preference: ${e.message}`);
        }
    }

    // Export methods for inline HTML onclick handlers
    window.DeskPilotApp = {
        openTaskModal,
        closeTaskModal,
        openTemplateGallery,
        closeTemplateGallery,
        addTemplateAgent,
        openBuilderModal,
        closeBuilderModal,
        deleteCustomAgent,
        openSaveLocationModal,
        closeSaveLocationModal,
        saveLocationPreferencesSubmit,
        switchView,
        refreshAuditHistory,
        selectChatSession: (id) => selectChatSession(id),
        deleteChatSession: (id) => deleteCurrentChat(id),
        openAgentChat: (agentId) => openAgentChat(agentId),
        startNewChat: (agentId) => startNewChat(agentId),
        sendChatMessage: () => sendChatMessage(),
        applyChatPrompt: (prompt) => {
            const ta = document.getElementById('chat-input-textarea');
            if (ta) {
                ta.value = prompt;
                ta.focus();
            }
        },
        openDeliverablePath: async (path) => {
            if (window.DeskPilot && window.DeskPilot.openDeliverable) {
                try {
                    await window.DeskPilot.openDeliverable(path);
                } catch (e) {
                    console.error("Failed to open deliverable:", e);
                }
            }
        },
        filterAgentsCategory: (category) => {
            currentCategoryFilter = category;
            const tabs = ['all', 'default', 'custom'];
            tabs.forEach(t => {
                const btn = document.getElementById(`tab-agent-${t}`);
                if (btn) {
                    if (t === category) {
                        btn.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600/20 text-indigo-300 border border-indigo-500/30";
                    } else {
                        btn.className = "px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200";
                    }
                }
            });
            loadCatalogAgents();
        }
    };

    // Run initialization
    initDashboard();

    // Re-load when pywebview becomes ready
    window.addEventListener('pywebviewready', () => {
        console.log("pywebviewready event caught in app.js, refreshing dashboard...");
        loadAgents();
        loadRecentActivity();
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
