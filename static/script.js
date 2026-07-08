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

    // --- Authentication ---
    loginBtn.addEventListener('click', async () => {
        const password = passwordInput.value;
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
            }
        } catch (err) {
            console.error(err);
        }
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
            const card = document.createElement('div');
            card.className = 'bot-card';
            card.innerHTML = `
                <div class="bot-card-header">
                    <div class="bot-name">${bot.replace('_', ' ')} <span>(v2.0)</span></div>
                    <div class="status-indicator">
                        <div id="dot-${bot}" class="dot stopped"></div>
                        <span id="text-${bot}">Stopped</span>
                    </div>
                </div>
                <div style="display:flex; gap:10px; margin-bottom: 1rem;">
                    <button id="start-${bot}" class="success-btn" style="margin:0;">Start</button>
                    <button id="stop-${bot}" class="danger-btn" style="margin:0;" disabled>Stop</button>
                </div>
                <div>
                    <input type="text" id="presence-${bot}" class="presence-input" placeholder="Custom Status (e.g. Playing a game)">
                    <button id="set-presence-${bot}" class="presence-btn">Update Status</button>
                </div>
            `;
            botsGrid.appendChild(card);

            // Bind Bot Controls
            const startBtn = document.getElementById(`start-${bot}`);
            const stopBtn = document.getElementById(`stop-${bot}`);
            
            startBtn.addEventListener('click', () => toggleBot(bot, 'start'));
            stopBtn.addEventListener('click', () => toggleBot(bot, 'stop'));

            // Bind Presence Update
            document.getElementById(`set-presence-${bot}`).addEventListener('click', async () => {
                const presenceVal = document.getElementById(`presence-${bot}`).value;
                const btn = document.getElementById(`set-presence-${bot}`);
                btn.innerText = 'Updating...';
                try {
                    await fetch(`/api/presence/${bot}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ presence: presenceVal })
                    });
                    btn.innerText = 'Updated!';
                    setTimeout(() => btn.innerText = 'Update Status', 2000);
                } catch (e) {
                    console.error(e);
                    btn.innerText = 'Failed';
                }
            });
        });
    }

    async function toggleBot(bot, action) {
        const startBtn = document.getElementById(`start-${bot}`);
        const stopBtn = document.getElementById(`stop-${bot}`);
        
        startBtn.disabled = true;
        stopBtn.disabled = true;
        
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
                    const dot = document.getElementById(`dot-${bot}`);
                    const text = document.getElementById(`text-${bot}`);
                    const startBtn = document.getElementById(`start-${bot}`);
                    const stopBtn = document.getElementById(`stop-${bot}`);
                    
                    if (!dot) return; // UI not initialized
                    
                    if (isRunning) {
                        dot.className = 'dot running';
                        text.innerText = 'Running';
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                    } else {
                        dot.className = 'dot stopped';
                        text.innerText = 'Stopped';
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
            
            fileSelect.innerHTML = '<option value="">Select a file...</option>';
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
        saveBtn.innerText = 'Saving...';
        
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
            saveBtn.innerText = 'Save Changes';
        }
    });
    
    // Check initial auth status by trying to get status
    fetch('/api/status').then(res => {
        if (res.ok) {
            showDashboard();
        }
    });
});
