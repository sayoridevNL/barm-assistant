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

    // --- Authentication & Initialization ---
    if (typeof USER_ID !== 'undefined' && USER_ID) {
        // User is logged in via Discord
        showDashboard();
    } else {
        showLogin();
    }

    // --- Dashboard logic ---
    function showDashboard() {
        loginScreen.classList.add('hidden');
        dashboardScreen.classList.remove('hidden');
        
        // Populate User Info
        document.getElementById('profile-img').src = AVATAR_URL;
        document.getElementById('profile-name').innerText = USERNAME || 'User';
        
        // Hide admin tabs if not admin
        if (!IS_ADMIN) {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
        }
        
        // Tab Switching Logic
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                btn.classList.add('active');
                document.getElementById(btn.dataset.target).classList.add('active');
            });
        });
        
        fetchUserStats();
        fetchLeaderboards();
        
        if (IS_ADMIN) {
            initBotCards();
            fetchStatus();
            fetchPresences();
            fetchFiles();
            // Poll status every 5 seconds
            statusInterval = setInterval(fetchStatus, 5000);
        }
    }

    function showLogin() {
        dashboardScreen.classList.add('hidden');
        loginScreen.classList.remove('hidden');
        if (typeof statusInterval !== 'undefined') clearInterval(statusInterval);
    }
    
    async function fetchUserStats() {
        try {
            const res = await fetch('/api/user/stats');
            const data = await res.json();
            if (data.stats) {
                document.getElementById('stat-sayories').innerText = data.stats.sayories.toLocaleString();
                document.getElementById('stat-quotes').innerText = data.stats.quotes.toLocaleString();
                document.getElementById('stat-umas').innerText = data.stats.umamusume.toLocaleString();
                
                // Render Uma Trainees
                const umasGrid = document.getElementById('umas-grid');
                umasGrid.innerHTML = '';
                if (data.stats.umas_list && data.stats.umas_list.length > 0) {
                    data.stats.umas_list.forEach(uma => {
                        const imgUrl = uma.image ? (uma.image.includes('?') ? uma.image + '&_cb=' + Date.now() : uma.image + '?_cb=' + Date.now()) : '';
                        
                        const rarityColors = {
                            "Legendary": "#FFD700",
                            "SSR": "#FF69B4",
                            "SR": "#B983FF",
                            "R": "#4CAF50"
                        };
                        const rarityColor = rarityColors[uma.rarity] || "#aaa";
                        
                        const card = document.createElement('div');
                        card.className = 'glass-panel';
                        card.style.borderTop = `4px solid ${rarityColor}`;
                        card.style.overflow = 'hidden';
                        
                        let imgHtml = imgUrl ? `<div style="height: 150px; overflow: hidden; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.3);"><img src="${imgUrl}" style="max-height: 100%; object-fit: contain;"></div>` : '';
                        
                        card.innerHTML = `
                            ${imgHtml}
                            <div style="padding: 1rem;">
                                <h3 style="margin: 0 0 0.5rem 0; font-size: 1.2rem;">${uma.name}</h3>
                                <span style="background: ${rarityColor}40; color: ${rarityColor}; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">${uma.rarity}</span>
                                <div style="margin-top: 1rem; display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.9rem;">
                                    <div>⚡ SPD: ${uma.speed}</div>
                                    <div>❤️ STA: ${uma.stamina}</div>
                                    <div>💪 POW: ${uma.power}</div>
                                    <div>🏆 ${uma.wins}W / ${uma.races}R</div>
                                </div>
                            </div>
                        `;
                        umasGrid.appendChild(card);
                    });
                } else {
                    umasGrid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #aaa; padding: 2rem;">You have no Umamusume! Go use the /lootbox command in Discord to get some!</div>';
                }
            }
        } catch (e) {
            console.error('Failed to fetch user stats:', e);
        }
    }

    async function fetchLeaderboards() {
        try {
            const res = await fetch('/api/leaderboards');
            const data = await res.json();
            
            const renderBoard = (items, elementId, unit) => {
                const list = document.getElementById(elementId);
                list.innerHTML = '';
                if (!items || items.length === 0) {
                    list.innerHTML = '<li style="text-align:center; color:#aaa; padding: 1rem;">No data available</li>';
                    return;
                }
                
                items.forEach((item, index) => {
                    const li = document.createElement('li');
                    li.style.padding = '0.75rem';
                    li.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                    li.style.display = 'flex';
                    li.style.justifyContent = 'space-between';
                    li.style.alignItems = 'center';
                    
                    let rankHtml = `<span style="font-weight: bold; width: 20px; display: inline-block; color: #aaa;">${index+1}</span>`;
                    if (index === 0) rankHtml = `<span style="font-weight: bold; width: 20px; display: inline-block; color: #FFD700;"><i class="fa-solid fa-crown"></i></span>`;
                    if (index === 1) rankHtml = `<span style="font-weight: bold; width: 20px; display: inline-block; color: #C0C0C0;">2</span>`;
                    if (index === 2) rankHtml = `<span style="font-weight: bold; width: 20px; display: inline-block; color: #CD7F32;">3</span>`;
                    
                    li.innerHTML = `
                        <div style="display: flex; align-items: center; gap: 1rem;">
                            ${rankHtml}
                            <span style="font-weight: 500;">${item.username}</span>
                        </div>
                        <div style="font-weight: bold;">
                            ${item.score.toLocaleString()} <span style="font-size: 0.8rem; font-weight: normal; color: #aaa;">${unit}</span>
                        </div>
                    `;
                    list.appendChild(li);
                });
            };
            
            renderBoard(data.sayories, 'lb-sayories', '🪙');
            renderBoard(data.quotes, 'lb-quotes', '⭐');
            
        } catch (e) {
            console.error('Failed to fetch leaderboards:', e);
        }
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
