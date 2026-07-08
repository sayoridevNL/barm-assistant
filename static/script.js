document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const loginScreen = document.getElementById('login-screen');
    const dashboardScreen = document.getElementById('dashboard-screen');
    const passwordInput = document.getElementById('password-input');
    const loginBtn = document.getElementById('login-btn');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    
    const botsGrid = document.getElementById('bots-grid');
    
    const fileSelect = document.getElementById('file-select');
    const saveBtn = document.getElementById('save-btn');
    const saveMsg = document.getElementById('save-msg');

    // CodeMirror instance
    const editor = CodeMirror.fromTextArea(document.getElementById('code-editor'), {
        mode: 'python',
        theme: 'dracula',
        lineNumbers: true,
        indentUnit: 4,
        matchBrackets: true
    });

    let statusInterval;
    const BOT_NAMES = [
        "music_bot", "moderation_bot", "community_bot", 
        "gambling_bot", "umamusume_bot", "general_bot"
    ];

    // Icons mapping for visual flair
    const BOT_ICONS = {
        "music_bot": "fa-music",
        "moderation_bot": "fa-shield-halved",
        "community_bot": "fa-users",
        "gambling_bot": "fa-dice",
        "umamusume_bot": "fa-horse",
        "general_bot": "fa-robot"
    };

    // --- Authentication ---
    loginBtn.addEventListener('click', async () => {
        const password = passwordInput.value;
        const btnText = loginBtn.querySelector('span');
        btnText.innerText = 'Authenticating...';
        
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });
            const data = await res.json();
            
            if (data.success) {
                showDashboard();
            } else {
                loginError.classList.remove('hidden');
                setTimeout(() => loginError.classList.add('hidden'), 3000);
            }
        } catch (err) {
            console.error(err);
        } finally {
            btnText.innerText = 'Authenticate';
        }
    });

    passwordInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loginBtn.click();
    });

    logoutBtn.addEventListener('click', async () => {
        await fetch('/api/logout', { method: 'POST' });
        showLogin();
    });

    // --- Dashboard logic ---
    function showDashboard() {
        loginScreen.classList.add('hidden');
        dashboardScreen.classList.remove('hidden');
        loginError.classList.add('hidden');
        passwordInput.value = '';
        
        initBotCards();
        fetchStatus();
        fetchPresences();
        fetchFiles();
        
        // Poll status every 5 seconds
        statusInterval = setInterval(fetchStatus, 5000);
    }

    function showLogin() {
        dashboardScreen.classList.add('hidden');
        loginScreen.classList.remove('hidden');
        clearInterval(statusInterval);
    }

    // --- Bot Cards UI ---
    function initBotCards() {
        botsGrid.innerHTML = '';
        BOT_NAMES.forEach(bot => {
            const icon = BOT_ICONS[bot] || "fa-robot";
            const displayName = bot.replace('_', ' ');
            
            const card = document.createElement('div');
            card.className = 'bot-card';
            card.innerHTML = `
                <div class="bot-card-header">
                    <div class="bot-info">
                        <div class="bot-name"><i class="fa-solid ${icon}"></i> ${displayName}</div>
                        <div style="margin-top: 0.25rem;"><span class="bot-version">v2.0 Architecture</span></div>
                    </div>
                    <div id="badge-${bot}" class="status-badge loading">
                        <i class="fa-solid fa-spinner fa-spin"></i> Loading...
                    </div>
                </div>
                
                <div class="card-actions">
                    <button id="start-${bot}" class="success-btn">
                        <i class="fa-solid fa-play"></i> Start
                    </button>
                    <button id="stop-${bot}" class="danger-btn" disabled>
                        <i class="fa-solid fa-stop"></i> Stop
                    </button>
                </div>
                
                <div class="presence-section">
                    <div class="presence-label">
                        <i class="fa-regular fa-message"></i> Custom Status
                    </div>
                    <div class="presence-input-wrapper">
                        <input type="text" id="presence-${bot}" class="presence-input" placeholder="e.g. Playing a game...">
                        <button id="set-presence-${bot}" class="presence-btn" title="Update Status">
                            <i class="fa-solid fa-rotate-right"></i>
                        </button>
                    </div>
                </div>
            `;
            botsGrid.appendChild(card);

            // Bind Bot Controls
            const startBtn = document.getElementById(`start-${bot}`);
            const stopBtn = document.getElementById(`stop-${bot}`);
            
            startBtn.addEventListener('click', () => toggleBot(bot, 'start'));
            stopBtn.addEventListener('click', () => toggleBot(bot, 'stop'));

            // Bind Presence Update
            const presenceBtn = document.getElementById(`set-presence-${bot}`);
            const presenceInput = document.getElementById(`presence-${bot}`);
            
            const updatePresence = async () => {
                const presenceVal = presenceInput.value;
                const originalIcon = presenceBtn.innerHTML;
                presenceBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                
                try {
                    await fetch(`/api/presence/${bot}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ presence: presenceVal })
                    });
                    presenceBtn.innerHTML = '<i class="fa-solid fa-check" style="color: var(--success-hover);"></i>';
                    setTimeout(() => presenceBtn.innerHTML = originalIcon, 2000);
                } catch (e) {
                    console.error(e);
                    presenceBtn.innerHTML = '<i class="fa-solid fa-xmark" style="color: var(--danger-hover);"></i>';
                    setTimeout(() => presenceBtn.innerHTML = originalIcon, 2000);
                }
            };
            
            presenceBtn.addEventListener('click', updatePresence);
            presenceInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') updatePresence();
            });
        });
    }

    async function toggleBot(bot, action) {
        const startBtn = document.getElementById(`start-${bot}`);
        const stopBtn = document.getElementById(`stop-${bot}`);
        const badge = document.getElementById(`badge-${bot}`);
        
        startBtn.disabled = true;
        stopBtn.disabled = true;
        badge.className = 'status-badge loading';
        badge.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing...';
        
        try {
            const res = await fetch(`/api/${action}/${bot}`, { method: 'POST' });
            const data = await res.json();
            if (!data.success) {
                alert(data.message);
            }
            fetchStatus();
        } catch (err) {
            console.error(err);
        }
    }

    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (res.status === 401) { showLogin(); return; }
            
            const data = await res.json();
            if (data.bots) {
                BOT_NAMES.forEach(bot => {
                    const isRunning = data.bots[bot];
                    const badge = document.getElementById(`badge-${bot}`);
                    const startBtn = document.getElementById(`start-${bot}`);
                    const stopBtn = document.getElementById(`stop-${bot}`);
                    
                    if (!badge) return; // UI not initialized
                    
                    if (isRunning) {
                        badge.className = 'status-badge running';
                        badge.innerHTML = '<i class="fa-solid fa-circle-check"></i> Online';
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                    } else {
                        badge.className = 'status-badge stopped';
                        badge.innerHTML = '<i class="fa-regular fa-circle-xmark"></i> Offline';
                        startBtn.disabled = false;
                        stopBtn.disabled = true;
                    }
                });
            }
        } catch (err) {
            console.error(err);
        }
    }
    
    async function fetchPresences() {
        try {
            const res = await fetch('/api/presence');
            if (res.status === 401) return;
            const data = await res.json();
            if (data.presences) {
                BOT_NAMES.forEach(bot => {
                    const input = document.getElementById(`presence-${bot}`);
                    if (input && data.presences[bot]) {
                        input.value = data.presences[bot];
                    }
                });
            }
        } catch(e) {
            console.error(e);
        }
    }

    // --- Code Editor ---
    async function fetchFiles() {
        try {
            const res = await fetch('/api/files');
            if (res.status === 401) return;
            const data = await res.json();
            
            fileSelect.innerHTML = '<option value="">Select a file to edit...</option>';
            data.files.forEach(file => {
                const opt = document.createElement('option');
                opt.value = file;
                opt.innerText = file;
                fileSelect.appendChild(opt);
            });
        } catch (err) {
            console.error(err);
        }
    }

    fileSelect.addEventListener('change', async (e) => {
        const filename = e.target.value;
        if (!filename) {
            editor.setValue('');
            saveBtn.disabled = true;
            return;
        }
        
        try {
            const res = await fetch(`/api/files/${filename}`);
            if (res.status === 401) return;
            const data = await res.json();
            
            if (data.content !== undefined) {
                editor.setValue(data.content);
                saveBtn.disabled = false;
            }
        } catch (err) {
            console.error(err);
        }
    });

    saveBtn.addEventListener('click', async () => {
        const filename = fileSelect.value;
        const content = editor.getValue();
        if (!filename) return;
        
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
        
        try {
            const res = await fetch(`/api/files/${filename}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content })
            });
            
            if (res.ok) {
                saveMsg.classList.remove('hidden');
                setTimeout(() => saveMsg.classList.add('hidden'), 3000);
            } else {
                alert('Failed to save file');
            }
        } catch (err) {
            console.error(err);
            alert('Failed to save file');
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Changes';
        }
    });
    
    // Check initial auth status by trying to get status
    fetch('/api/status').then(res => {
        if (res.ok) {
            showDashboard();
        }
    });
});
