document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const loginScreen = document.getElementById('login-screen');
    const dashboardScreen = document.getElementById('dashboard-screen');
    const passwordInput = document.getElementById('password-input');
    const loginBtn = document.getElementById('login-btn');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    
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
        
        // Initial fetches
        fetchStatus();
        fetchFiles();
        
        // Poll status every 5 seconds
        statusInterval = setInterval(fetchStatus, 5000);
    }

    function showLogin() {
        dashboardScreen.classList.add('hidden');
        loginScreen.classList.remove('hidden');
        clearInterval(statusInterval);
    }

    // --- Bot Control ---
    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (res.status === 401) { showLogin(); return; }
            
            const data = await res.json();
            updateStatusUI(data.running);
        } catch (err) {
            console.error(err);
        }
    }

    function updateStatusUI(isRunning) {
        if (isRunning) {
            statusDot.className = 'dot running';
            statusText.innerText = 'Status: Running';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else {
            statusDot.className = 'dot stopped';
            statusText.innerText = 'Status: Stopped';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
    }

    startBtn.addEventListener('click', async () => {
        startBtn.disabled = true;
        try {
            const res = await fetch('/api/start', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                updateStatusUI(true);
            } else {
                alert(data.message);
                startBtn.disabled = false;
            }
        } catch (err) {
            console.error(err);
            startBtn.disabled = false;
        }
    });

    stopBtn.addEventListener('click', async () => {
        stopBtn.disabled = true;
        try {
            const res = await fetch('/api/stop', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                updateStatusUI(false);
            } else {
                alert(data.message);
                stopBtn.disabled = false;
            }
        } catch (err) {
            console.error(err);
            stopBtn.disabled = false;
        }
    });

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
