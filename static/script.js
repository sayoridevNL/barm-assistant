document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const loginScreen = document.getElementById('login-screen');
    const dashboardScreen = document.getElementById('dashboard-screen');
    
    // Toast Host Setup
    if (!document.getElementById('toast-host')) {
        const toastHost = document.createElement('div');
        toastHost.id = 'toast-host';
        toastHost.setAttribute('aria-live', 'polite');
        document.body.appendChild(toastHost);
    }

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
        "gambling_bot", "umamusume_bot", "general_bot", "kinect_bot"
    ];

    const BOT_ICONS = {
        "music_bot": "fa-music",
        "moderation_bot": "fa-shield-halved",
        "community_bot": "fa-users",
        "gambling_bot": "fa-dice",
        "umamusume_bot": "fa-horse",
        "general_bot": "fa-robot",
        "kinect_bot": "fa-link"
    };

    // --- Toast Utility ---
    window.showToast = function(message, type = 'success') {
        const host = document.getElementById('toast-host');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<i class="fa-solid ${type === 'success' ? 'fa-check-circle' : 'fa-triangle-exclamation'}"></i> ${message}`;
        host.appendChild(toast);
        
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    };

    // --- Skeleton & Empty State Utilities ---
    function renderSkeletons(containerId, type, count = 3) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        for(let i=0; i<count; i++) {
            const div = document.createElement('div');
            div.className = `skeleton skeleton-${type}`;
            container.appendChild(div);
        }
    }

    function renderEmptyState(containerId, icon, message) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = `<div class="empty-state"><i class="fa-solid ${icon}"></i><div>${message}</div></div>`;
    }

    // --- Authentication & Initialization ---
    if (typeof USER_ID !== 'undefined' && USER_ID) {
        showDashboard();
    } else {
        showLogin();
    }

    function showDashboard() {
        loginScreen.classList.add('hidden');
        dashboardScreen.classList.remove('hidden');
        
        document.getElementById('profile-img').src = AVATAR_URL;
        const displayName = USERNAME || 'User';
        document.getElementById('profile-name').innerText = displayName;
        const welcomeName = document.getElementById('welcome-name');
        if (welcomeName) welcomeName.innerText = displayName;
        
        if (!IS_ADMIN) {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
        }
        
        // Tab Switching Logic with ARIA
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.tab-btn').forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-selected', 'false');
                });
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');
                document.getElementById(btn.dataset.target).classList.add('active');
            });
        });
        
        // Initial Skeletons
        renderSkeletons('umas-grid', 'card', 3);
        renderSkeletons('lb-sayories', 'row', 5);
        renderSkeletons('lb-quotes', 'row', 5);
        renderSkeletons('quotes-history-container', 'row', 3);
        
        fetchUserStats();
        fetchLeaderboards();
        fetchQuotes();
        
        if (IS_ADMIN) {
            initBotCards();
            fetchStatus();
            fetchPresences();
            fetchFiles();
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
                
                const freeHaruElem = document.getElementById('stat-free-haru');
                if (freeHaruElem) freeHaruElem.innerText = (data.stats.free_haru_coins || 0).toLocaleString();
                const paidHaruElem = document.getElementById('stat-paid-haru');
                if (paidHaruElem) paidHaruElem.innerText = (data.stats.paid_haru_coins || 0).toLocaleString();
                
                const umasGrid = document.getElementById('umas-grid');
                umasGrid.innerHTML = '';
                if (data.stats.umas_list && data.stats.umas_list.length > 0) {
                    data.stats.umas_list.forEach(uma => {
                        const imgUrl = uma.image ? (uma.image.includes('?') ? uma.image + '&_cb=' + Date.now() : uma.image + '?_cb=' + Date.now()) : '';
                        const rarityClass = uma.rarity || ""; // Legendary, SSR, SR, R
                        
                        const card = document.createElement('div');
                        card.className = `uma-card rarity-${rarityClass}`;
                        
                        let imgHtml = imgUrl ? `<div class="uma-img-wrapper"><img src="${imgUrl}" alt="${uma.name}"></div>` : '';
                        
                        card.innerHTML = `
                            ${imgHtml}
                            <div class="uma-card-header">
                                <h3>${uma.name}</h3>
                                <span class="rarity-badge">${uma.rarity}</span>
                            </div>
                            <div class="uma-stats">
                                <div>⚡ SPD: ${uma.speed}</div>
                                <div>❤️ STA: ${uma.stamina}</div>
                                <div>💪 POW: ${uma.power}</div>
                                <div>🏆 ${uma.wins}W / ${uma.races}R</div>
                            </div>
                        `;
                        umasGrid.appendChild(card);
                    });
                } else {
                    renderEmptyState('umas-grid', 'fa-horse', 'No trainees yet — try <code>/pull_trainee</code> to recruit one!');
                }
            }

            // Support Cards
            if (data.stats.support_cards_list) {
                const supportGrid = document.getElementById('support-grid');
                if (supportGrid) {
                    supportGrid.innerHTML = '';
                    if (data.stats.support_cards_list.length > 0) {
                        data.stats.support_cards_list.forEach(card => {
                            const imgUrl = card.image ? (card.image.includes('?') ? card.image + '&_cb=' + Date.now() : card.image + '?_cb=' + Date.now()) : '';
                            const rarityClass = card.rarity || "R";
                            
                            const cardEl = document.createElement('div');
                            cardEl.className = `uma-card rarity-${rarityClass}`;
                            
                            let imgHtml = imgUrl ? `<div class="uma-img-wrapper"><img src="${imgUrl}" alt="${card.name}"></div>` : '';
                            
                            let typeEmoji = '🏃';
                            if (card.type === 'Speed') typeEmoji = '👟';
                            if (card.type === 'Stamina') typeEmoji = '❤️';
                            if (card.type === 'Power') typeEmoji = '💪';
                            if (card.type === 'Guts') typeEmoji = '🔥';
                            if (card.type === 'Wit') typeEmoji = '🧠';
                            if (card.type === 'Friend') typeEmoji = '🤝';
                            if (card.type === 'Group') typeEmoji = '👥';

                            cardEl.innerHTML = `
                                ${imgHtml}
                                <div class="uma-card-header">
                                    <h3>${card.name}</h3>
                                    <span class="rarity-badge">${card.rarity}</span>
                                </div>
                                <div class="uma-stats" style="grid-template-columns: 1fr;">
                                    <div><i class="fa-solid fa-tag"></i> Type: ${typeEmoji} ${card.type}</div>
                                    <div><i class="fa-solid fa-chart-bar"></i> Bonus: <strong>${card.bonus}</strong></div>
                                    <div style="margin-top: 0.5rem; font-size: 0.8rem; font-style: italic;">"${card.flavor}"</div>
                                </div>
                            `;
                            supportGrid.appendChild(cardEl);
                        });
                    } else {
                        renderEmptyState('support-grid', 'fa-clone', 'No support cards yet — try <code>/pull_support</code> to recruit one!');
                    }
                }
            }

            // --- Umamusume Training Center Setup ---
            if (data.stats.umas_list && data.stats.support_cards_list) {
                const umaSelect = document.getElementById('train-uma-select');
                const supportSelect = document.getElementById('train-support-select');
                
                if (umaSelect && supportSelect) {
                    umaSelect.innerHTML = '';
                    supportSelect.innerHTML = '';
                    
                    let trainingUma = null;
                    data.stats.umas_list.forEach(uma => {
                        const opt = document.createElement('option');
                        opt.value = uma.id;
                        opt.textContent = `${uma.name} [${uma.rarity}] (⭐${uma.stars || 1})`;
                        umaSelect.appendChild(opt);
                        
                        if (uma.training_end) {
                            trainingUma = uma;
                        }
                    });
                    
                    data.stats.support_cards_list.forEach(card => {
                        const opt = document.createElement('option');
                        opt.value = card.id;
                        opt.textContent = `${card.name} [${card.type}] (Lv. ${card.level || 1})`;
                        supportSelect.appendChild(opt);
                    });
                    
                    const setupContainer = document.getElementById('training-setup-container');
                    const activeContainer = document.getElementById('training-active-container');
                    
                    if (trainingUma) {
                        setupContainer.style.display = 'none';
                        activeContainer.style.display = 'block';
                        window.currentTrainingUmaId = trainingUma.id;
                        startTrainingCountdown(trainingUma.training_end);
                    } else {
                        setupContainer.style.display = 'block';
                        activeContainer.style.display = 'none';
                        if (window.trainingInterval) clearInterval(window.trainingInterval);
                    }
                }
            }

        } catch (e) {
            console.error('Failed to fetch user stats:', e);
            renderEmptyState('umas-grid', 'fa-triangle-exclamation', 'Failed to load trainees.');
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
                    renderEmptyState(elementId, 'fa-trophy', 'No data available yet. Start playing to top the charts!');
                    return;
                }
                
                items.forEach((item, index) => {
                    const li = document.createElement('li');
                    li.className = `leaderboard-row rank-${index + 1}`;
                    
                    let rankHtml = `<span class="leaderboard-rank">${index+1}</span>`;
                    if (index === 0) rankHtml = `<span class="leaderboard-rank"><i class="fa-solid fa-crown"></i></span>`;
                    
                    li.innerHTML = `
                        <div style="display: flex; align-items: center; gap: 1rem;">
                            ${rankHtml}
                            <span style="font-weight: 500;">${item.username}</span>
                        </div>
                        <div class="leaderboard-score">
                            ${item.score.toLocaleString()} <span style="font-size: 0.8rem; font-weight: normal; color: var(--text-secondary);">${unit}</span>
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

    async function fetchQuotes() {
        try {
            const res = await fetch('/api/quotes');
            const data = await res.json();
            const container = document.getElementById('quotes-history-container');
            container.innerHTML = '';
            if (data.quotes && data.quotes.length > 0) {
                data.quotes.forEach(quote => {
                    const el = document.createElement('div');
                    el.className = 'quote-item';
                    const d = new Date(quote.timestamp * 1000);
                    el.innerHTML = `
                        <div class="quote-text">"${quote.text}"</div>
                        <div class="quote-meta">Quoted by <span class="quoter">${quote.quoter}</span> • ${d.toLocaleDateString()}</div>
                    `;
                    container.appendChild(el);
                });
            } else {
                renderEmptyState('quotes-history-container', 'fa-comment-dots', 'No quotes found. Tell your friends to reply to your messages with "quote"!');
            }
        } catch(e) {
            console.error('Failed to fetch quotes:', e);
        }
    }

    const themeToggle = document.getElementById('theme-toggle-btn');
    const themeColorMeta = document.querySelector('meta[name="theme-color"]');

    function setTheme(theme, persist = true) {
        const isLight = theme === 'light';
        document.body.classList.toggle('light-theme', isLight);
        document.body.classList.toggle('dark-theme', !isLight);

        if (themeToggle) {
            const icon = themeToggle.querySelector('i');
            icon.classList.toggle('fa-sun', isLight);
            icon.classList.toggle('fa-moon', !isLight);
            themeToggle.setAttribute('aria-pressed', String(isLight));
            themeToggle.title = isLight ? 'Switch to dark mode' : 'Switch to light mode';
        }
        if (themeColorMeta) themeColorMeta.content = isLight ? '#fff8f5' : '#17132a';

        if (persist) {
            try { localStorage.setItem('barm-theme', theme); } catch (error) { /* Storage can be unavailable. */ }
        }
    }

    try {
        const savedTheme = localStorage.getItem('barm-theme');
        if (savedTheme === 'light' || savedTheme === 'dark') setTheme(savedTheme, false);
    } catch (error) { /* Use the default dark theme when storage is unavailable. */ }

    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const icon = themeToggle.querySelector('i');
            icon.style.transition = 'transform 0.15s ease';
            icon.style.transform = 'rotate(180deg) scale(0)';

            setTimeout(() => {
                setTheme(document.body.classList.contains('dark-theme') ? 'light' : 'dark');
                icon.style.transform = 'rotate(0deg) scale(1)';
            }, 150);
        });
    }

    // --- Bot Cards UI ---
    function initBotCards() {
        const botsGrid = document.getElementById('bots-grid');
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
                        <span class="bot-version">v2.0 Architecture</span>
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
                        <button id="set-presence-${bot}" class="presence-btn" title="Update Status" aria-label="Update Status">
                            <i class="fa-solid fa-rotate-right"></i>
                        </button>
                    </div>
                </div>
            `;
            botsGrid.appendChild(card);

            const startBtn = document.getElementById(`start-${bot}`);
            const stopBtn = document.getElementById(`stop-${bot}`);
            
            startBtn.addEventListener('click', () => toggleBot(bot, 'start'));
            stopBtn.addEventListener('click', () => toggleBot(bot, 'stop'));

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
        
            // --- Umamusume Training Center Setup ---
            if (data.stats.umas_list && data.stats.support_cards_list) {
                const umaSelect = document.getElementById('train-uma-select');
                const supportSelect = document.getElementById('train-support-select');
                
                if (umaSelect && supportSelect) {
                    umaSelect.innerHTML = '';
                    supportSelect.innerHTML = '';
                    
                    let trainingUma = null;
                    data.stats.umas_list.forEach(uma => {
                        const opt = document.createElement('option');
                        opt.value = uma.id;
                        opt.textContent = `${uma.name} [${uma.rarity}] (⭐${uma.stars || 1})`;
                        umaSelect.appendChild(opt);
                        
                        if (uma.training_end) {
                            trainingUma = uma;
                        }
                    });
                    
                    data.stats.support_cards_list.forEach(card => {
                        const opt = document.createElement('option');
                        opt.value = card.id;
                        opt.textContent = `${card.name} [${card.type}] (Lv. ${card.level || 1})`;
                        supportSelect.appendChild(opt);
                    });
                    
                    const setupContainer = document.getElementById('training-setup-container');
                    const activeContainer = document.getElementById('training-active-container');
                    
                    if (trainingUma) {
                        setupContainer.style.display = 'none';
                        activeContainer.style.display = 'block';
                        window.currentTrainingUmaId = trainingUma.id;
                        startTrainingCountdown(trainingUma.training_end);
                    } else {
                        setupContainer.style.display = 'block';
                        activeContainer.style.display = 'none';
                        if (window.trainingInterval) clearInterval(window.trainingInterval);
                    }
                }
            }

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
                showToast(data.message, 'error');
            }
            fetchStatus();
        } catch (err) {
            console.error(err);
            showToast('Failed to toggle bot.', 'error');
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
                    
                    if (!badge) return; 
                    
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
        const fileSelect = document.getElementById('file-select');
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

    document.getElementById('file-select').addEventListener('change', async (e) => {
        const filename = e.target.value;
        const saveBtn = document.getElementById('save-btn');
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

    document.getElementById('save-btn').addEventListener('click', async () => {
        const filename = document.getElementById('file-select').value;
        const content = editor.getValue();
        const saveBtn = document.getElementById('save-btn');
        
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
                showToast('File saved successfully!', 'success');
            } else {
                showToast('Failed to save file.', 'error');
            }
        } catch (err) {
            console.error(err);
            showToast('Network error saving file.', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Changes';
        }
    });
    
    // Initial Auth Check
    fetch('/api/status').then(res => {
        if (res.ok) showDashboard();
    });
});

window.publishBroadcast = async function() {
    const title = document.getElementById('bc-title').value;
    const desc = document.getElementById('bc-desc').value;
    const color = document.getElementById('bc-color').value;
    const image = document.getElementById('bc-image').value;
    const footer = document.getElementById('bc-footer').value;
    const btn = document.getElementById('bc-submit-btn');

    if (!title && !desc) {
        showToast('Title or description is required!', 'error');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Publishing...';

    try {
        const res = await fetch('/api/admin/publish_embed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, desc, color, image, footer })
        });
        const data = await res.json();
        
        if (res.ok) {
            showToast(data.message, 'success');
            document.getElementById('bc-title').value = '';
            document.getElementById('bc-desc').value = '';
            document.getElementById('bc-color').value = '';
            document.getElementById('bc-image').value = '';
            document.getElementById('bc-footer').value = '';
        } else {
            showToast(data.error || 'Failed to publish', 'error');
        }
    } catch (e) {
        showToast('Network Error', 'error');
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Publish to All Servers';
};


// --- Suggestions ---
document.getElementById('suggestion-input')?.addEventListener('input', function(e) {
    document.getElementById('suggestion-chars').innerText = `${e.target.value.length} / 1000`;
});

async function submitSuggestion() {
    const input = document.getElementById('suggestion-input');
    const btn = document.getElementById('btn-submit-suggestion');
    const text = input.value.trim();
    
    if (!text) {
        showToast('Please enter a suggestion first!', 'error');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Submitting...';
    
    try {
        const res = await fetch('/api/suggest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ suggestion: text })
        });
        
        const data = await res.json();
        
        if (res.ok) {
            showToast('Suggestion submitted successfully!', 'success');
            input.value = '';
            document.getElementById('suggestion-chars').innerText = '0 / 1000';
            
            // Start local cooldown timer visual
            let timeLeft = 3600;
            const timer = setInterval(() => {
                timeLeft--;
                if (timeLeft <= 0) {
                    clearInterval(timer);
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit Suggestion';
                } else {
                    const m = Math.floor(timeLeft / 60);
                    btn.innerHTML = `<i class="fa-solid fa-clock"></i> Cooldown (${m}m)`;
                }
            }, 1000);
        } else {
            showToast(data.error || 'Failed to submit suggestion', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit Suggestion';
        }
    } catch (err) {
        showToast('Network error submitting suggestion.', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit Suggestion';
    }
}

// --- TOTO BATTLE SYSTEM ---
let currentTotoPicks = {};

async function loadTotoBattle() {
    try {
        const res = await fetch('/api/toto/battle');
        const data = await res.json();
        const tab = document.getElementById('btn-toto-tab');
        const container = document.getElementById('toto-matches-container');
        const status = document.getElementById('toto-status');
        const submitBtn = document.getElementById('btn-submit-toto');

        if (!data.eligible) return;
        tab.style.display = 'inline-block';
        
        if (data.active) {
            if (data.resolved) {
                status.innerText = 'This battle has already concluded! Check Discord for results.';
                container.innerHTML = '';
                submitBtn.style.display = 'none';
                return;
            }
            
            status.innerText = 'Select your predictions below:';
            // Keep choices made in this browser while the cards are re-rendered.
            // Previously every click reloaded the saved server state and discarded
            // the choice before the user could lock it in.
            currentTotoPicks = { ...(data.my_picks || {}), ...currentTotoPicks };
            
            let html = '';
            for (let m of data.match_data) {
                const pick = currentTotoPicks[m.id];
                html += `
                <div style="display: flex; flex-direction: column; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px;">
                    <div style="font-weight: 600; margin-bottom: 0.5rem; text-align: center;">${m.name}</div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem;">
                        <button class="btn ${pick === '1' ? 'btn-primary' : 'glass-panel'}" onclick="selectToto('${m.id}', '1')">1 (Home)</button>
                        <button class="btn ${pick === 'X' ? 'btn-primary' : 'glass-panel'}" onclick="selectToto('${m.id}', 'X')">X (Draw)</button>
                        <button class="btn ${pick === '2' ? 'btn-primary' : 'glass-panel'}" onclick="selectToto('${m.id}', '2')">2 (Away)</button>
                    </div>
                </div>`;
            }
            container.innerHTML = html;
            submitBtn.style.display = 'inline-block';
        } else {
            status.innerText = data.message || 'There is no Prediction Battle for you today. A battle is created automatically on Eredivisie, Keuken Kampioen Divisie, or KNVB Beker match days.';
            container.innerHTML = '';
            submitBtn.style.display = 'none';
        }
    } catch (err) {
        console.error(err);
    }
}

function selectToto(matchId, choice) {
    currentTotoPicks[matchId] = choice;
    loadTotoBattle(); // re-render to update button styles
}

async function submitTotoPredictions() {
    const btn = document.getElementById('btn-submit-toto');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Locking in...';
    
    try {
        const res = await fetch('/api/toto/predict', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ picks: currentTotoPicks })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Predictions locked in successfully!', 'success');
            currentTotoPicks = data.picks || currentTotoPicks;
        } else {
            showToast(data.error || 'Failed to submit.', 'error');
        }
    } catch (err) {
        showToast('Network error submitting predictions.', 'error');
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-check"></i> Lock In Predictions';
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadTotoBattle, 1500);
});


    // --- Training Center Functions ---
    window.startTrainingCountdown = function(endTime) {
        if (window.trainingInterval) clearInterval(window.trainingInterval);
        
        const countdownEl = document.getElementById('training-countdown');
        const finishBtn = document.getElementById('btn-finish-training');
        
        window.trainingInterval = setInterval(() => {
            const now = Math.floor(Date.now() / 1000);
            const remaining = endTime - now;
            
            if (remaining <= 0) {
                clearInterval(window.trainingInterval);
                countdownEl.textContent = "00:00:00";
                countdownEl.style.color = "var(--stat-green)";
                finishBtn.style.display = "inline-block";
                return;
            }
            
            const hours = Math.floor(remaining / 3600);
            const minutes = Math.floor((remaining % 3600) / 60);
            const seconds = remaining % 60;
            
            countdownEl.textContent = 
                `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            countdownEl.style.color = "var(--pink)";
            finishBtn.style.display = "none";
        }, 1000);
    };
    
    window.startTraining = async function() {
        const umaSelect = document.getElementById('train-uma-select');
        const supportSelect = document.getElementById('train-support-select');
        
        const umaId = umaSelect.value;
        const selectedSupports = Array.from(supportSelect.selectedOptions).map(opt => opt.value);
        
        if (!umaId) return alert("Select an Uma to train!");
        if (selectedSupports.length > 4) return alert("You can only select up to 4 Support Cards!");
        
        const btn = document.getElementById('btn-start-training');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Starting...';
        btn.disabled = true;
        
        try {
            const res = await fetch('/api/uma/train', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uma_id: umaId, supports: selectedSupports })
            });
            const data = await res.json();
            
            if (data.error) {
                alert("Error: " + data.error);
            } else {
                fetchUserStats();
            }
        } catch (e) {
            console.error("Error starting training:", e);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    };
    
    window.finishTraining = async function() {
        if (!window.currentTrainingUmaId) return;
        
        const btn = document.getElementById('btn-finish-training');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Finishing...';
        btn.disabled = true;
        
        try {
            const res = await fetch('/api/uma/finish_train', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uma_id: window.currentTrainingUmaId })
            });
            const data = await res.json();
            
            if (data.error) {
                alert("Error: " + data.error);
            } else {
                alert(`Training Complete! ${data.uma.name} gained new stats!`);
                window.currentTrainingUmaId = null;
                fetchUserStats();
            }
        } catch (e) {
            console.error("Error finishing training:", e);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    };

// TC logic
let tcRarities = [
    { id: 1, name: 'C', color: 'gray', chance: 45.0 },
    { id: 2, name: 'UC', color: 'green', chance: 30.0 },
    { id: 3, name: 'R', color: 'cyan', chance: 15.0 },
    { id: 4, name: 'SR', color: 'magenta', chance: 6.0 },
    { id: 5, name: 'SSR', color: 'gold', chance: 3.0 },
    { id: 6, name: 'SSL', color: 'orange', chance: 0.9 },
    { id: 7, name: 'USL', color: 'white', chance: 0.1 }
];
let tcCards = [];
let totalDropChance = 0;

function renderTcRarities() {
    const list = document.getElementById('tc-rarity-list');
    if(!list) return;
    list.innerHTML = '';
    tcRarities.forEach((r, i) => {
        const li = document.createElement('li');
        li.draggable = true;
        li.innerHTML = `<span>${r.name} (${r.chance || 0}%)</span> <i class="fa-solid fa-grip-lines"></i>`;
        li.ondragstart = (e) => e.dataTransfer.setData('text/plain', i);
        li.ondragover = (e) => e.preventDefault();
        li.ondrop = (e) => {
            e.preventDefault();
            const from = parseInt(e.dataTransfer.getData('text/plain'));
            const to = i;
            const item = tcRarities.splice(from, 1)[0];
            tcRarities.splice(to, 0, item);
            renderTcRarities();
            updateTcRaritySelect();
        };
        list.appendChild(li);
    });
}

window.addRarity = function() {
    const name = prompt("Rarity Name:");
    if(name) {
        const chance = parseFloat(prompt("Drop Chance % (e.g. 50):")) || 0;
        tcRarities.push({ id: Date.now(), name, chance, color: 'white' });
        
        fetch('/api/cards/rarities', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(tcRarities)
        }).then(r => {
            if(r.ok) {
                renderTcRarities();
                updateTcRaritySelect();
                showToast('Rarity saved!', 'success');
            }
        });
    }
}

function updateTcRaritySelect(targetId) {
    const sel = document.getElementById(targetId || 'tcm-rarity');
    if(!sel) return;
    const previous = sel.value;
    sel.innerHTML = '';
    tcRarities.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.name;
        opt.textContent = r.name;
        sel.appendChild(opt);
    });
    if ([...sel.options].some(o => o.value === previous)) sel.value = previous;
}

// Persists the current tcTemplatesCache array to the server (used for create,
// edit, and delete alike, since the backend replaces the whole template list).
// Surfaces any per-card image-ingest warnings the backend reports, since a
// silently-kept dead Discord CDN link is exactly what causes broken /buy_card
// pulls later.
function persistTcTemplates(successMessage) {
    return fetch('/api/cards/templates', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(tcTemplatesCache)
    }).then(res => res.json().catch(() => ({})).then(data => ({ ok: res.ok, data }))
    ).then(({ ok, data }) => {
        if (!ok) {
            showToast(data.error || 'Failed to save', 'error');
            return false;
        }
        if (data.warnings && data.warnings.length) {
            data.warnings.forEach(w => showToast(w, 'error'));
        } else {
            showToast(successMessage, 'success');
        }
        fetchTcData();
        return true;
    }).catch(e => {
        console.error(e);
        showToast('Error saving card(s)', 'error');
        return false;
    });
}

// ── Trading Card modals (create/edit + delete confirm) ─────────────────────
// Cards now get their artwork from a direct upload to /api/cards/upload-image
// (stored permanently in the card_images Mongo collection) instead of a
// pasted external link, so there's nothing left to expire or 404.
let tcModalMode = null;      // 'create' | 'edit'
let tcModalEditId = null;
let tcModalUploadedUrl = null;
let tcModalUploadedImageId = null;
let tcModalUploading = false;
let tcDeleteId = null;

// Cropper state for the artwork preview inside the create/edit modal.
const TC_CROP_W = 250;
const TC_CROP_H = 350;
let userZoom = 1.0;
let userOffsetX = 0;
let userOffsetY = 0;
let imgNatW = 0;
let imgNatH = 0;

// Positions the preview image with a single transform: scale it to "cover"
// the 250x350 frame (so the whole picture is visible the instant it loads,
// before any zoom is applied), then layer the zoom slider and drag offset
// on top. The offset is clamped every time so dragging can never pull the
// image away from an edge and leave an empty gap in the frame.
function updateCropper() {
    const preview = document.getElementById('tcm-preview');
    if (!preview || !imgNatW || !imgNatH) return;

    const coverScale = Math.max(TC_CROP_W / imgNatW, TC_CROP_H / imgNatH);
    const scale = coverScale * userZoom;
    const dispW = imgNatW * scale;
    const dispH = imgNatH * scale;

    const maxOffsetX = Math.max(0, (dispW - TC_CROP_W) / 2);
    const maxOffsetY = Math.max(0, (dispH - TC_CROP_H) / 2);
    userOffsetX = Math.min(maxOffsetX, Math.max(-maxOffsetX, userOffsetX));
    userOffsetY = Math.min(maxOffsetY, Math.max(-maxOffsetY, userOffsetY));

    const translateX = (TC_CROP_W - dispW) / 2 + userOffsetX;
    const translateY = (TC_CROP_H - dispH) / 2 + userOffsetY;

    preview.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    preview.classList.add('tc-ready');
}

function resetTcModalFields() {
    document.getElementById('tcm-title').value = '';
    document.getElementById('tcm-type').selectedIndex = 0;
    const preview = document.getElementById('tcm-preview');
    preview.classList.add('hidden');
    preview.classList.remove('tc-ready');
    preview.style.transform = '';
    preview.src = '';
    document.getElementById('tcm-dropzone-placeholder').classList.remove('hidden');
    document.getElementById('tcm-upload-status').classList.add('hidden');
    document.getElementById('tcm-file').value = '';
    document.getElementById('tcm-cropper-controls').classList.add('hidden');
    tcModalUploadedUrl = null;
    tcModalUploadedImageId = null;
    userZoom = 1.0;
    userOffsetX = 0;
    userOffsetY = 0;
    imgNatW = 0;
    imgNatH = 0;
    document.getElementById('tcm-zoom').value = 1.0;
}

window.openTcCardModal = function(mode, id) {
    tcModalMode = mode;
    tcModalEditId = mode === 'edit' ? id : null;
    resetTcModalFields();
    updateTcRaritySelect('tcm-rarity');

    const heading = document.getElementById('tcm-heading');
    const subheading = document.getElementById('tcm-subheading');
    const saveBtn = document.getElementById('tcm-save-btn');

    if (mode === 'edit') {
        const card = tcTemplatesCache.find(c => String(c.id) === String(id));
        if (!card) return showToast('Card not found', 'error');

        heading.innerHTML = '<i class="fa-solid fa-pen"></i> Edit Card';
        subheading.textContent = 'Update the details, or upload a new image to replace the artwork.';
        saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Changes';

        document.getElementById('tcm-title').value = card.title || card.name || '';
        const typeSel = document.getElementById('tcm-type');
        if ([...typeSel.options].some(o => o.value === card.type)) typeSel.value = card.type;

        if (card.img) {
            userZoom = Math.min(4, Math.max(1, card.zoom || 1.0));
            userOffsetX = card.offsetX || 0;
            userOffsetY = card.offsetY || 0;
            document.getElementById('tcm-zoom').value = userZoom;
            
            const preview = document.getElementById('tcm-preview');
            preview.onload = () => {
                imgNatW = preview.naturalWidth;
                imgNatH = preview.naturalHeight;
                updateCropper();
            };
            preview.src = card.img;
            preview.classList.remove('hidden');
            document.getElementById('tcm-dropzone-placeholder').classList.add('hidden');
            document.getElementById('tcm-cropper-controls').classList.remove('hidden');
            tcModalUploadedUrl = card.img;
            tcModalUploadedImageId = card.image_id || null;
        }
    } else {
        heading.innerHTML = '<i class="fa-solid fa-square-plus"></i> Create New Card';
        subheading.textContent = "Upload artwork and set the card's details.";
        saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Card';
    }

    // Rarity select needs the right value picked after being (re)populated.
    const raritySel = document.getElementById('tcm-rarity');
    if (mode === 'edit') {
        const card = tcTemplatesCache.find(c => String(c.id) === String(id));
        if (card && [...raritySel.options].some(o => o.value === card.rarity)) raritySel.value = card.rarity;
    }

    document.getElementById('tc-card-modal').classList.remove('hidden');
}

window.closeTcCardModal = function() {
    document.getElementById('tc-card-modal').classList.add('hidden');
    tcModalMode = null;
    tcModalEditId = null;
}

function setTcUploadStatus(html, isError) {
    const status = document.getElementById('tcm-upload-status');
    status.innerHTML = html;
    status.classList.toggle('error', !!isError);
    status.classList.remove('hidden');
}

function uploadTcImage(file) {
    if (!file) return;
    if (!file.type.startsWith('image/')) return showToast('Please choose an image file', 'error');
    if (file.size > 8 * 1024 * 1024) return showToast('Image must be under 8MB', 'error');

    tcModalUploading = true;
    setTcUploadStatus('<i class="fa-solid fa-spinner fa-spin"></i> Uploading...', false);

    const formData = new FormData();
    formData.append('image', file);

    fetch('/api/cards/upload-image', { method: 'POST', body: formData })
        .then(res => res.json().catch(() => ({})).then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            tcModalUploading = false;
            if (!ok) {
                setTcUploadStatus(`<i class="fa-solid fa-triangle-exclamation"></i> ${data.error || 'Upload failed'}`, true);
                return;
            }
            document.getElementById('tcm-upload-status').classList.add('hidden');
            tcModalUploadedUrl = data.url;
            tcModalUploadedImageId = data.image_id;
            
            userZoom = 1.0;
            userOffsetX = 0;
            userOffsetY = 0;
            document.getElementById('tcm-zoom').value = 1.0;
            
            const preview = document.getElementById('tcm-preview');
            preview.onload = () => {
                imgNatW = preview.naturalWidth;
                imgNatH = preview.naturalHeight;
                updateCropper();
            };
            preview.src = data.url;
            preview.classList.remove('hidden');
            document.getElementById('tcm-dropzone-placeholder').classList.add('hidden');
            document.getElementById('tcm-cropper-controls').classList.remove('hidden');
        })
        .catch(e => {
            tcModalUploading = false;
            console.error(e);
            setTcUploadStatus('<i class="fa-solid fa-triangle-exclamation"></i> Upload failed', true);
        });
}

window.submitTcCardModal = function() {
    const title = document.getElementById('tcm-title').value.trim();
    const type = document.getElementById('tcm-type').value;
    const rarity = document.getElementById('tcm-rarity').value;

    if (!title) return showToast('A card title is required', 'error');
    if (tcModalUploading) return showToast('Still uploading the image, hang on...', 'error');
    if (!tcModalUploadedUrl) return showToast('Please upload an image for the card', 'error');

    if (tcModalMode === 'edit') {
        const card = tcTemplatesCache.find(c => String(c.id) === String(tcModalEditId));
        if (!card) return showToast('Card not found', 'error');
        card.title = title;
        card.type = type;
        card.rarity = rarity;
        card.img = tcModalUploadedUrl;
        card.zoom = userZoom;
        card.offsetX = userOffsetX;
        card.offsetY = userOffsetY;
        if (tcModalUploadedImageId) card.image_id = tcModalUploadedImageId; else delete card.image_id;
    } else {
        tcTemplatesCache.push({
            id: Date.now(),
            title, type, rarity,
            img: tcModalUploadedUrl,
            zoom: userZoom,
            offsetX: userOffsetX,
            offsetY: userOffsetY,
            image_id: tcModalUploadedImageId || undefined,
        });
    }

    persistTcTemplates(tcModalMode === 'edit' ? 'Card updated!' : 'Card saved!').then(ok => {
        if (ok) closeTcCardModal();
    });
}

// Admin: remove a card template entirely, via confirm modal instead of a
// native confirm() popup.
window.openTcDeleteModal = function(id) {
    const card = tcTemplatesCache.find(c => String(c.id) === String(id));
    if (!card) return;
    tcDeleteId = id;
    document.getElementById('tcm-delete-name').textContent = `"${card.title || card.name || 'this card'}"`;
    document.getElementById('tc-delete-modal').classList.remove('hidden');
}

window.closeTcDeleteModal = function() {
    document.getElementById('tc-delete-modal').classList.add('hidden');
    tcDeleteId = null;
}

window.confirmTcDelete = function() {
    if (tcDeleteId === null) return;
    tcTemplatesCache = tcTemplatesCache.filter(c => String(c.id) !== String(tcDeleteId));
    persistTcTemplates('Card deleted.');
    closeTcDeleteModal();
}

function setupTcModalListeners() {
    const dropzone = document.getElementById('tcm-dropzone');
    const fileInput = document.getElementById('tcm-file');
    if (!dropzone || !fileInput) return;

    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) uploadTcImage(fileInput.files[0]);
    });

    ['dragenter', 'dragover'].forEach(evt => {
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
    });
    ['dragleave', 'drop'].forEach(evt => {
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
    });
    dropzone.addEventListener('drop', (e) => {
        const file = e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) uploadTcImage(file);
    });

    // Pointer events cover mouse, touch and pen with one code path, so
    // dragging the artwork to reposition it works the same on mobile as
    // on desktop. Position updates are batched into a single
    // requestAnimationFrame per tick so drags stay smooth even on quick
    // swipes.
    let isDragging = false;
    let dragPointerId = null;
    let startX = 0, startY = 0;
    let startOffsetX = 0, startOffsetY = 0;
    let dragFrameQueued = false;

    dropzone.addEventListener('pointerdown', (e) => {
        if (!tcModalUploadedUrl) return;
        isDragging = true;
        dragPointerId = e.pointerId;
        startX = e.clientX;
        startY = e.clientY;
        startOffsetX = userOffsetX;
        startOffsetY = userOffsetY;
        dropzone.classList.add('tc-dragging');
        dropzone.setPointerCapture(e.pointerId);
        e.preventDefault();
    });

    dropzone.addEventListener('pointermove', (e) => {
        if (!isDragging || e.pointerId !== dragPointerId) return;
        userOffsetX = startOffsetX + (e.clientX - startX);
        userOffsetY = startOffsetY + (e.clientY - startY);
        if (!dragFrameQueued) {
            dragFrameQueued = true;
            requestAnimationFrame(() => {
                updateCropper();
                dragFrameQueued = false;
            });
        }
    });

    function endDrag(e) {
        if (dragPointerId !== null && e && e.pointerId !== dragPointerId) return;
        isDragging = false;
        dragPointerId = null;
        dropzone.classList.remove('tc-dragging');
    }
    dropzone.addEventListener('pointerup', endDrag);
    dropzone.addEventListener('pointercancel', endDrag);

    // Scroll/trackpad zoom, so people don't have to reach for the slider
    // to fine-tune framing while their hand is already on the image.
    dropzone.addEventListener('wheel', (e) => {
        if (!tcModalUploadedUrl) return;
        e.preventDefault();
        const zoomSlider = document.getElementById('tcm-zoom');
        const step = e.deltaY < 0 ? 0.05 : -0.05;
        userZoom = Math.min(4, Math.max(1, userZoom + step));
        if (zoomSlider) zoomSlider.value = userZoom;
        updateCropper();
    }, { passive: false });

    const zoomSlider = document.getElementById('tcm-zoom');
    if (zoomSlider) {
        zoomSlider.addEventListener('input', (e) => {
            userZoom = parseFloat(e.target.value);
            updateCropper();
        });
    }

    const resetPositionBtn = document.getElementById('tcm-reset-position');
    if (resetPositionBtn) {
        resetPositionBtn.addEventListener('click', () => {
            userZoom = 1.0;
            userOffsetX = 0;
            userOffsetY = 0;
            if (zoomSlider) zoomSlider.value = 1.0;
            updateCropper();
        });
    }

    // Close either modal by clicking its overlay backdrop, or with Escape.
    document.getElementById('tc-card-modal').addEventListener('click', (e) => {
        if (e.target.id === 'tc-card-modal') closeTcCardModal();
    });
    document.getElementById('tc-delete-modal').addEventListener('click', (e) => {
        if (e.target.id === 'tc-delete-modal') closeTcDeleteModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (!document.getElementById('tc-card-modal').classList.contains('hidden')) closeTcCardModal();
        if (!document.getElementById('tc-delete-modal').classList.contains('hidden')) closeTcDeleteModal();
    });
}


let tcInventoryCache = [];
let tcTemplatesCache = [];

function fetchTcData() {
    Promise.all([
        fetch('/api/cards/inventory').then(r => r.ok ? r.json() : {cards: []}),
        fetch('/api/cards/templates').then(r => r.ok ? r.json() : [])
    ]).then(([inv, templates]) => {
        tcInventoryCache = inv.cards || [];
        tcTemplatesCache = Array.isArray(templates) ? templates : (templates.templates || []);
        renderTcCarousel();
    }).catch(e => console.error("Error fetching gacha data:", e));
}

function renderTcCarousel() {
    const carousel = document.getElementById('tc-carousel');
    if(!carousel) return;
    carousel.innerHTML = '';
    
    if(tcTemplatesCache.length === 0) {
        carousel.innerHTML = '<div style="grid-column: 1/-1; color:#aaa; padding:2rem;">No cards exist yet. Admins must create cards!</div>';
        return;
    }
    
    const ownedCounts = {};
    tcInventoryCache.forEach(c => {
        ownedCounts[c.template_id] = (ownedCounts[c.template_id] || 0) + 1;
    });
    
    tcTemplatesCache.forEach(t => {
        const count = ownedCounts[t.id] || 0;
        const owned = count > 0;
        const c = document.createElement('div');
        c.className = `tc-card ${owned ? 'discovered' : 'undiscovered'}`;

        let titleHtml = '';
        if(owned) {
            titleHtml = `<div style="position:absolute; bottom:5px; width:100%; text-align:center; color:white; font-size:0.8rem; font-weight:bold; text-shadow:1px 1px 2px black;">${t.title || t.name || 'Unknown'} (x${count})</div>`;
        }

        // A card whose image is still a raw external (e.g. Discord CDN) link
        // means permanent ingestion never succeeded — that link can expire
        // and 404 out, which is exactly what breaks /buy_card. Flag it.
        const isBroken = !!(t.img && /^https?:\/\//i.test(t.img) && !t.image_id);

        const rarityColor = (tcRarities.find(r => r.name === t.rarity) || {}).color;
        const rarityStyle = rarityColor ? ` style="background:${rarityColor}; color:#111;"` : '';

        let adminHtml = '';
        if (typeof IS_ADMIN !== 'undefined' && IS_ADMIN) {
            adminHtml = `
                <div class="tc-card-admin-actions">
                    <button class="tc-admin-btn edit" title="Edit card" onclick="event.stopPropagation(); openTcCardModal('edit', '${t.id}')"><i class="fa-solid fa-pen"></i></button>
                    <button class="tc-admin-btn delete" title="Delete card" onclick="event.stopPropagation(); openTcDeleteModal('${t.id}')"><i class="fa-solid fa-trash"></i></button>
                </div>
            `;
        }

        c.innerHTML = `
            <img class="tc-image" src="${t.img || 'https://via.placeholder.com/200x280'}" />
            <div class="tc-rarity badge"${rarityStyle}>${t.rarity || ''}</div>
            <div class="tc-type badge badge-dark">${t.type || ''}</div>
            ${isBroken ? '<div class="tc-card-broken"><i class="fa-solid fa-triangle-exclamation"></i> Image link broken — edit to fix</div>' : ''}
            ${titleHtml}
            ${adminHtml}
        `;
        carousel.appendChild(c);
    });
}

window.pullCardGacha = function(count = 1) {
    if(count > 1 && !confirm(`Pull ${count} cards for ${count * 100} Sayories?`)) return;
    
    fetch('/api/cards/pull', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({count})
    }).then(res => res.json()).then(data => {
        if(data.error) {
            return showToast(data.error, 'error');
        }
        
        const overlay = document.getElementById('gacha-overlay');
        const env = document.getElementById('gacha-envelope');
        const reveal = document.getElementById('gacha-card-reveal');
        
        // Show bulk pull animation
        overlay.classList.remove('hidden');
        env.className = ''; 
        setTimeout(() => {
            env.classList.add('glow-SSR');
            setTimeout(() => {
                env.classList.add('burst');
                setTimeout(() => {
                    let html = '<div style="display:flex; flex-wrap:wrap; gap:10px; justify-content:center; max-width:80vw; max-height:80vh; overflow-y:auto;">';
                    data.templates.forEach(t => {
                        html += `<div class="tc-card discovered" style="width: 150px; height: 210px; transform: scale(1);"><img class="tc-image" src="${t.img || 'https://via.placeholder.com/200x280'}" /><div class="tc-overlay"></div></div>`;
                    });
                    html += '</div><button class="btn-primary" onclick="closeGachaReveal()" style="margin-top:20px; position:absolute; bottom:20px;">Collect Cards</button>';
                    reveal.innerHTML = html;
                    reveal.classList.remove('hidden');
                    
                    // Update global sayories UI if it exists
                    document.getElementById('eco-sayories') && (document.getElementById('eco-sayories').innerText = data.new_balance);
                }, 500);
            }, 1500);
        }, 1000);
    });
}

window.closeGachaReveal = function() {
    document.getElementById('gacha-overlay').classList.add('hidden');
    document.getElementById('gacha-card-reveal').classList.add('hidden');
    document.getElementById('gacha-card-reveal').innerHTML = '';
    fetchTcData();
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        renderTcRarities();
        updateTcRaritySelect();
        fetchTcData();
        setupTcModalListeners();
    }, 500);
});