
let currentSessionId = null;
let eventSource = null;
let allLogs = [];

function startDownload() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) {
        alert('Por favor, insira uma URL válida');
        return;
    }

    // Update UI
    setLoading(true);
    clearLogs();
    hideMessages();

    // Start download
    fetch('/start-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url })
    })
    .then(async response => {
        const data = await response.json().catch(() => ({}));

        if (response.status === 401) {
            window.location.href = '/login';
            throw new Error(data.error || 'Sessão expirada. Faça login novamente.');
        }

        if (!response.ok) {
            throw new Error(data.error || 'Erro ao iniciar o download');
        }

        return data;
    })
    .then(data => {
        currentSessionId = data.session_id;
        connectSSE(currentSessionId);
    })
    .catch(error => {
        const errorMsg = 'Erro de conexão: ' + error.message;
        showError(errorMsg);
        addLog('' + errorMsg);
        setLoading(false);
    });
}

function connectSSE(sessionId) {
    eventSource = new EventSource('/stream/' + sessionId);

    eventSource.onmessage = function(event) {
        addLog(event.data);
    };

    eventSource.addEventListener('done', function(event) {
        eventSource.close();

        if (event.data === 'complete') {
            // Trigger download
            triggerDownload(sessionId);
            showSuccess(sessionId);
            setLoading(false);
        } else {
            showError('Download falhou. Verifique os logs para mais detalhes.');
            addLog('Download falhou');
            setLoading(false);
        }
    });

    eventSource.onerror = function() {
        eventSource.close();
        showError('Conexão com o servidor foi perdida.');
        addLog('Erro de conexão SSE');
        setLoading(false);
    };
}

function triggerDownload(sessionId) {
    const link = document.createElement('a');
    link.href = '/download-file/' + sessionId;
    link.click();

    // Update manual download link
    document.getElementById('downloadLink').href = '/download-file/' + sessionId;
}

function showSuccess(sessionId) {
    hideMessages();
    const successMsg = document.getElementById('successMessage');
    successMsg.classList.add('active');
    document.getElementById('downloadLink').href = '/download-file/' + sessionId;
}

function showError(message) {
    hideMessages();
    const errorMsg = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    errorText.textContent = message;
    errorMsg.classList.add('active');
}

function hideMessages() {
    document.getElementById('successMessage').classList.remove('active');
    document.getElementById('errorMessage').classList.remove('active');
}

function setLoading(loading) {
    const btn = document.getElementById('downloadBtn');
    const btnText = document.getElementById('btnText');
    const spinner = document.getElementById('spinner');
    const input = document.getElementById('urlInput');
    const logContainer = document.getElementById('logContainer');

    btn.disabled = loading;
    input.disabled = loading;
    spinner.style.display = loading ? 'block' : 'none';
    btnText.textContent = loading ? 'Processando...' : 'Baixar Réplica';

    if (loading) {
        logContainer.classList.add('active');
    }
}

function addLog(message) {
    // Store in array for copy function
    allLogs.push(message);

    const logContent = document.getElementById('logContent');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = message;
    logContent.appendChild(entry);
    logContent.scrollTop = logContent.scrollHeight;
}

function clearLogs() {
    document.getElementById('logContent').innerHTML = '';
    allLogs = [];
}

function copyLogs() {
    const logsText = allLogs.join('\n');

    navigator.clipboard.writeText(logsText).then(() => {
        const btn = document.getElementById('copyLogsBtn');
        const originalText = btn.textContent;
        btn.textContent = '- Copiado!';
        btn.classList.add('copied');

        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('copied');
        }, 2000);
    }).catch(err => {
        alert('Erro ao copiar logs: ' + err);
    });
}

// Handle Enter key
document.getElementById('urlInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter' && !document.getElementById('downloadBtn').disabled) {
        startDownload();
    }
});
