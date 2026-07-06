/**
 * AI PDF Analyzer Frontend - Database-Backed Session Management
 */

let uploadedFiles = {};
let currentFile = null;
let currentFileId = null;
let sessionId = null;
let currentContext = '';

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeSession();
});

// Session Management
function initializeSession() {
    sessionId = localStorage.getItem('pdfAnalyzerSessionId');
    
    if (!sessionId) {
        createNewSession();
    } else {
        loadSessionInfo();
    }
}

function createNewSession() {
    fetch('/create_session', {
        method: 'POST'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            sessionId = data.session_id;
            localStorage.setItem('pdfAnalyzerSessionId', sessionId);
            updateSessionDisplay();
            showStatus('success', 'New session created');
            refreshFileList();
        } else {
            showStatus('error', data.error || 'Failed to create session');
        }
    })
    .catch(err => showStatus('error', err.message));
}

function loadSessionInfo() {
    fetch(`/get_session_info/${sessionId}`)
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            uploadedFiles = {};
            data.pdfs.forEach(pdf => {
                uploadedFiles[pdf.file_id] = {
                    name: pdf.filename,
                    size: pdf.size,
                    file_id: pdf.file_id,
                    pages: pdf.pages
                };
            });
            refreshFileList();
            updateSessionDisplay();
        } else {
            createNewSession();
        }
    })
    .catch(err => {
        console.error('Failed to load session:', err);
        createNewSession();
    });
}

function updateSessionDisplay() {
    const header = document.querySelector('.header');
    if (header && !document.getElementById('sessionDisplay')) {
        const div = document.createElement('div');
        div.id = 'sessionDisplay';
        div.style.cssText = 'padding: 10px; background: #f0f4ff; border-bottom: 1px solid #ddd; font-size: 12px; color: #666; text-align: right;';
        header.appendChild(div);
    }
    
    const sessionDisplay = document.getElementById('sessionDisplay');
    if (sessionDisplay && sessionId) {
        sessionDisplay.innerHTML = `Session: <code>${sessionId.substring(0, 8)}...</code> | <a href="#" onclick="createNewSession(); return false;" style="color: #667eea;">New Session</a>`;
    }
}

// File upload handlers
function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById('uploadArea').classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById('uploadArea').classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById('uploadArea').classList.remove('dragover');
    const files = e.dataTransfer.files;
    handleFiles(files);
}

document.getElementById('uploadArea').addEventListener('click', function() {
    document.getElementById('fileInput').click();
});

function handleFileSelect(e) {
    handleFiles(e.target.files);
}

function handleFiles(files) {
    for (let file of files) {
        if (file.type === 'application/pdf' || file.type.startsWith('image/') || file.type === 'text/plain') {
            uploadFile(file);
        } else {
            showStatus('error', 'Please upload PDF, images, or text files only');
        }
    }
}

function uploadFile(file) {
    if (!sessionId) {
        showStatus('error', 'No active session');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);

    showStatus('info', `Uploading ${file.name}...`);

    fetch('/upload_pdf', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            uploadedFiles[data.file_id] = {
                name: data.original_name,
                size: data.size,
                file_id: data.file_id
            };
            refreshFileList();
            showStatus('success', `${file.name} uploaded successfully (${formatBytes(data.size)})`);
            document.getElementById('fileInput').value = '';
        } else {
            showStatus('error', data.error || 'Upload failed');
        }
    })
    .catch(err => showStatus('error', err.message));
}

function refreshFileList() {
    const list = document.getElementById('fileList');
    if (Object.keys(uploadedFiles).length === 0) {
        list.innerHTML = '<div style="color: #999; text-align: center; padding: 20px; font-size: 12px;">No files uploaded yet</div>';
        return;
    }

    list.innerHTML = '';
    for (let [fileId, file] of Object.entries(uploadedFiles)) {
        const item = document.createElement('div');
        item.className = 'file-item' + (fileId === currentFileId ? ' active' : '');
        item.innerHTML = `
            <div class="file-name">${file.name}</div>
            <div class="file-size">${formatBytes(file.size)}</div>
            <button class="remove-btn" onclick="removeFile('${fileId}')">&times;</button>
        `;
        item.onclick = () => selectFile(fileId, file.name);
        list.appendChild(item);
    }

    if (Object.keys(uploadedFiles).length > 0) {
        document.getElementById('analyzeBtn').disabled = false;
    }
}

function selectFile(fileId, name) {
    currentFileId = fileId;
    currentFile = fileId;
    currentContext = '';
    refreshFileList();
    document.getElementById('chatTitle').textContent = `📄 ${name}`;
    document.getElementById('summarySection').style.display = 'none';
    document.getElementById('emptyPlaceholder').style.display = 'flex';
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('chatMessages').innerHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">⚙️</div>
            <p>Click "Analyze PDF" to start</p>
        </div>
    `;
}

function removeFile(fileId) {
    if (!confirm('Delete this file? This action cannot be undone.')) {
        return;
    }

    fetch(`/delete_pdf/${fileId}`, {
        method: 'DELETE'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            delete uploadedFiles[fileId];
            if (currentFileId === fileId) {
                currentFileId = null;
                currentFile = null;
                currentContext = '';
            }
            refreshFileList();
            showStatus('success', 'File deleted');
        } else {
            showStatus('error', data.error || 'Failed to delete file');
        }
    })
    .catch(err => showStatus('error', err.message));
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

// Analysis
function analyzePDF() {
    if (!currentFileId) {
        showStatus('error', 'Please select a file first');
        return;
    }

    if (!sessionId) {
        showStatus('error', 'No active session');
        return;
    }

    const provider = document.querySelector('input[name="provider"]:checked').value;
    document.getElementById('analyzeBtn').disabled = true;
    document.getElementById('analyzeBtn').textContent = 'Analyzing...';

    fetch('/analyze_pdf', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            file_id: currentFileId,
            session_id: sessionId,
            provider: provider
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            currentContext = data.summary;
            document.getElementById('summaryContent').innerHTML = marked(data.summary);
            document.getElementById('summarySection').style.display = 'block';
            document.getElementById('emptyPlaceholder').style.display = 'none';
            document.getElementById('chatContainer').style.display = 'flex';
            document.getElementById('chatMessages').innerHTML = '';
            document.getElementById('messageInput').disabled = false;
            document.getElementById('sendBtn').disabled = false;
            showStatus('success', `Analysis complete (${data.pages || '?'} pages, ${formatBytes(data.file_size)})`);
            
            // Load chat history
            loadChatHistory();
        } else {
            showStatus('error', data.error || 'Analysis failed');
        }
        document.getElementById('analyzeBtn').disabled = false;
        document.getElementById('analyzeBtn').textContent = 'Analyze PDF';
    })
    .catch(err => {
        showStatus('error', err.message);
        document.getElementById('analyzeBtn').disabled = false;
        document.getElementById('analyzeBtn').textContent = 'Analyze PDF';
    });
}

// Chat
function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();

    if (!message || !currentFileId) {
        return;
    }

    if (!sessionId) {
        showStatus('error', 'No active session');
        return;
    }

    const provider = document.querySelector('input[name="provider"]:checked').value;

    // Add user message to chat
    addMessage('user', message);
    input.value = '';
    input.style.height = 'auto';
    document.getElementById('sendBtn').disabled = true;

    fetch('/chat_pdf', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            file_id: currentFileId,
            session_id: sessionId,
            message: message,
            provider: provider
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            addMessage('ai', data.response);
        } else {
            addMessage('ai', `Error: ${data.error}`);
        }
        document.getElementById('sendBtn').disabled = false;
    })
    .catch(err => {
        addMessage('ai', `Error: ${err.message}`);
        document.getElementById('sendBtn').disabled = false;
    });
}

function addMessage(role, text) {
    const container = document.getElementById('chatMessages');
    
    // Remove empty state if present
    if (container.querySelector('.empty-state')) {
        container.innerHTML = '';
    }

    const message = document.createElement('div');
    message.className = `message ${role}`;
    
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;
    
    message.appendChild(bubble);
    container.appendChild(message);
    container.scrollTop = container.scrollHeight;
}

function loadChatHistory() {
    if (!currentFileId) return;

    fetch(`/get_chat_history/${currentFileId}?session_id=${sessionId}&limit=50`)
    .then(r => r.json())
    .then(data => {
        if (data.success && data.history && data.history.length > 0) {
            const container = document.getElementById('chatMessages');
            container.innerHTML = '';
            
            data.history.forEach(msg => {
                if (msg.role !== 'system') {  // Skip system messages
                    addMessage(msg.role, msg.content);
                }
            });
        }
    })
    .catch(err => console.error('Failed to load chat history:', err));
}

// Input auto-expand
document.getElementById('messageInput').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

document.getElementById('messageInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// Settings
function openSettings() {
    fetch('/get_ai_config')
        .then(r => r.json())
        .then(data => {
            document.getElementById('geminiKey').value = data.gemini.api_key || '';
            document.getElementById('geminiEnabled').checked = data.gemini.enabled || false;

            document.getElementById('openaiKey').value = data.openai.api_key || '';
            document.getElementById('openaiModel').value = data.openai.model || 'gpt-4-turbo';
            document.getElementById('openaiEnabled').checked = data.openai.enabled || false;

            document.getElementById('ollamaHost').value = data.ollama.host || 'http://localhost:11434';
            document.getElementById('ollamaModel').value = data.ollama.model || 'llama2';
            document.getElementById('ollamaEnabled').checked = data.ollama.enabled || false;

            document.getElementById('settingsModal').classList.add('active');
        });
}

function closeSettings() {
    document.getElementById('settingsModal').classList.remove('active');
}

function saveSettings() {
    const config = {
        gemini: {
            api_key: document.getElementById('geminiKey').value,
            enabled: document.getElementById('geminiEnabled').checked
        },
        openai: {
            api_key: document.getElementById('openaiKey').value,
            model: document.getElementById('openaiModel').value,
            enabled: document.getElementById('openaiEnabled').checked
        },
        ollama: {
            host: document.getElementById('ollamaHost').value,
            model: document.getElementById('ollamaModel').value,
            enabled: document.getElementById('ollamaEnabled').checked
        }
    };

    fetch('/save_ai_config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showStatus('success', 'Settings saved successfully');
            closeSettings();
        } else {
            showStatus('error', data.error || 'Failed to save settings');
        }
    })
    .catch(err => showStatus('error', err.message));
}

function showStatus(type, message) {
    const status = document.createElement('div');
    status.className = `status-message status-${type}`;
    status.textContent = message;

    const container = document.body;
    container.insertBefore(status, container.firstChild);

    setTimeout(() => status.remove(), 4000);
}

// Close modal when clicking outside
document.getElementById('settingsModal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeSettings();
    }
});

// Simple markdown rendering for summaries
const marked = (text) => {
    return text
        .replace(/^### (.*?)$/gim, '<h3>$1</h3>')
        .replace(/^## (.*?)$/gim, '<h2>$1</h2>')
        .replace(/^# (.*?)$/gim, '<h1>$1</h1>')
        .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/gim, '<em>$1</em>')
        .replace(/\n\n/gim, '</p><p>')
        .replace(/^/gim, '<p>') + '</p>';
};
