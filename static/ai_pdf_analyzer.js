/**
 * AI PDF Analyzer Frontend - Database-Backed Session Management
 */

let uploadedFiles = {};
let currentFile = null;
let currentFileId = null;
let sessionId = null;
let currentContext = '';

const PROVIDER_RADIO_MAP = {
    gemini: 'gemini',
    openai: 'openai',
    claude: 'claude',
    groq: 'groq',
    github: 'github',
    ollama: 'ollama',
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing AI PDF Analyzer...');
    checkDatabaseHealth();
    refreshProviderRadioAvailability();
    setTimeout(initializeSession, 500);
    window.addEventListener('resize', setupCompactSettingsMode);
});

function setupCompactSettingsMode() {
    const isCompact = window.matchMedia('(max-width: 600px)').matches;
    const sections = document.querySelectorAll('.modal-section.provider-section');
    sections.forEach((section, index) => {
        const title = section.querySelector('.section-title');
        if (!title) return;

        if (!title.dataset.compactBound) {
            title.addEventListener('click', () => {
                if (!window.matchMedia('(max-width: 600px)').matches) return;
                section.classList.toggle('compact-collapsed');
            });
            title.dataset.compactBound = '1';
        }

        if (isCompact) {
            const shouldExpand = index === 0;
            section.classList.toggle('compact-collapsed', !shouldExpand);
        } else {
            section.classList.remove('compact-collapsed');
        }
    });
}

function refreshProviderRadioAvailability() {
    fetch('/get_ai_config')
        .then(r => r.json())
        .then(config => {
            const providerStates = {
                gemini: Boolean(config?.gemini?.enabled),
                openai: Boolean(config?.openai?.enabled),
                claude: Boolean(config?.claude?.enabled),
                groq: Boolean(config?.groq?.enabled),
                github: Boolean(config?.github?.enabled),
                ollama: Boolean(config?.ollama?.enabled),
            };

            let selectedIsEnabled = false;
            let firstEnabled = null;

            Object.entries(PROVIDER_RADIO_MAP).forEach(([provider, radioValue]) => {
                const radio = document.querySelector(`input[name="provider"][value="${radioValue}"]`);
                if (!radio) return;
                const enabled = providerStates[provider];
                radio.disabled = !enabled;
                radio.closest('label')?.style.setProperty('opacity', enabled ? '1' : '0.45');
                if (enabled && !firstEnabled) firstEnabled = radio;
                if (enabled && radio.checked) selectedIsEnabled = true;
            });

            if (!selectedIsEnabled && firstEnabled) {
                firstEnabled.checked = true;
            }
        })
        .catch(err => console.warn('Failed to refresh provider availability:', err));
}

// Check database health on startup
function checkDatabaseHealth() {
    fetch('/health')
    .then(r => r.json())
    .then(data => {
        console.log('Health check:', data);
        if (!data.modules.database) {
            console.warn('Database module not available');
            showStatus('warning', 'Database module not available - some features may not work');
        } else if (!data.database_info.accessible) {
            console.error('Database not accessible:', data.database_info.error);
            showStatus('error', `Database Error: ${data.database_info.error}`);
        } else {
            console.log('Database is healthy');
        }
    })
    .catch(err => console.warn('Health check failed:', err));
}

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
    // Keep same session but clear chat history
    if (!sessionId) {
        // If no session exists, create one
        const createBtn = event?.target || document.querySelector('button[onclick="createNewSession()"]');
        if (createBtn) createBtn.disabled = true;
        
        fetch('/create_session', {
            method: 'POST'
        })
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
            return r.json();
        })
        .then(data => {
            if (data.success) {
                sessionId = data.session_id;
                localStorage.setItem('pdfAnalyzerSessionId', sessionId);
                updateSessionDisplay();
                showStatus('success', `Session created: ${sessionId.substring(0, 8)}...`);
            } else {
                throw new Error(data.error || 'Failed to create session');
            }
        })
        .catch(err => {
            console.error('Session creation error:', err);
            showStatus('error', `Session Error: ${err.message}`);
            alert(`Failed to create session:\n${err.message}\n\nPlease check:\n1. Server is running\n2. Database is accessible`);
        })
        .finally(() => {
            if (createBtn) createBtn.disabled = false;
        });
    } else {
        // Clear chat history for existing session (keep PDFs)
        const createBtn = event?.target || document.querySelector('button[onclick="createNewSession()"]');
        if (createBtn) createBtn.disabled = true;
        
        fetch(`/clear_chat/${sessionId}`, {
            method: 'POST'
        })
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
            return r.json();
        })
        .then(data => {
            if (data.success) {
                document.getElementById('chatMessages').innerHTML = '';
                document.getElementById('emptyPlaceholder').style.display = 'flex';
                document.getElementById('chatContainer').style.display = 'none';
                showStatus('success', 'Chat cleared - PDFs retained');
            } else {
                throw new Error(data.error || 'Failed to clear chat');
            }
        })
        .catch(err => {
            console.error('Clear chat error:', err);
            showStatus('error', `Clear Error: ${err.message}`);
        })
        .finally(() => {
            if (createBtn) createBtn.disabled = false;
        });
    }
}

function loadSessionInfo() {
    console.log(`Loading session info for: ${sessionId}`);
    fetch(`/get_session_info/${sessionId}`)
    .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
        return r.json();
    })
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
            console.log(`Session loaded: ${data.pdfs.length} PDFs`);
        } else {
            throw new Error(data.error || 'Invalid session');
        }
    })
    .catch(err => {
        console.error('Session load failed:', err);
        console.log('Creating new session...');
        localStorage.removeItem('pdfAnalyzerSessionId');
        sessionId = null;
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
        if (file.type === 'application/pdf' || file.type.startsWith('image/')) {
            uploadFile(file);
        } else {
            showStatus('error', 'Please upload PDF or image files only');
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

// Track selected files for multi-PDF analysis
let selectedFiles = new Set();

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
        const isSelected = selectedFiles.has(fileId);
        
        item.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <input type="checkbox" id="chk_${fileId}" ${isSelected ? 'checked' : ''} 
                    onchange="toggleFileSelection('${fileId}')" style="cursor: pointer;">
                <div style="flex: 1; min-width: 0;">
                    <div class="file-name">${file.name}</div>
                    <div class="file-size">${formatBytes(file.size)}</div>
                </div>
            </div>
            <button class="remove-btn" onclick="removeFile('${fileId}')">&times;</button>
        `;
        item.onclick = (e) => {
            if (e.target.type !== 'checkbox') {
                selectFile(fileId, file.name);
            }
        };
        list.appendChild(item);
    }

    if (Object.keys(uploadedFiles).length > 0) {
        document.getElementById('analyzeBtn').disabled = false;
    }
}

function toggleFileSelection(fileId) {
    if (selectedFiles.has(fileId)) {
        selectedFiles.delete(fileId);
    } else {
        selectedFiles.add(fileId);
    }
    selectFile(fileId, uploadedFiles[fileId].name);
}

function selectFile(fileId, name) {
    currentFileId = fileId;
    currentFile = fileId;
    currentContext = '';
    refreshFileList();
    document.getElementById('chatTitle').textContent = `📄 ${name}`;
    document.getElementById('emptyPlaceholder').style.display = 'flex';
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('chatMessages').innerHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">⚙️</div>
            <p>Click "Analyze PDF" to start</p>
        </div>
    `;
}

function renderSummaryInChat(summaryText) {
    const container = document.getElementById('chatMessages');
    if (!container || !summaryText) return;

    const existing = document.getElementById('summaryMessage');
    if (existing) existing.remove();

    const message = document.createElement('div');
    message.id = 'summaryMessage';
    message.className = 'message summary';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.innerHTML = `
        <div class="summary-title">Document Summary</div>
        <div class="summary-content">${marked(summaryText)}</div>
    `;

    message.appendChild(bubble);
    container.prepend(message);
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
    // If multiple files selected, analyze them together
    const filesToAnalyze = selectedFiles.size > 0 ? Array.from(selectedFiles) : (currentFileId ? [currentFileId] : []);
    
    if (filesToAnalyze.length === 0) {
        showStatus('error', 'Please select at least one file');
        return;
    }

    if (!sessionId) {
        showStatus('error', 'No active session');
        return;
    }

    const provider = document.querySelector('input[name="provider"]:checked').value;
    document.getElementById('analyzeBtn').disabled = true;
    const numFiles = filesToAnalyze.length;
    document.getElementById('analyzeBtn').textContent = numFiles > 1 ? `Analyzing ${numFiles} PDFs...` : 'Analyzing...';

    // Analyze the primary file (last selected or current)
    const primaryFileId = filesToAnalyze[filesToAnalyze.length - 1];

    fetch('/analyze_pdf', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            file_id: primaryFileId,
            session_id: sessionId,
            provider: provider,
            additional_files: filesToAnalyze.slice(0, -1) // For future multi-PDF support
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            currentContext = data.summary;
            document.getElementById('emptyPlaceholder').style.display = 'none';
            document.getElementById('chatContainer').style.display = 'flex';
            document.getElementById('chatMessages').innerHTML = '';
            renderSummaryInChat(data.summary);
            document.getElementById('messageInput').disabled = false;
            document.getElementById('sendBtn').disabled = false;
            
            // Generate dynamic title from file names and summary
            const summary = data.summary || '';
            const subjectMatch = summary.match(/[^.!?]*[.!?]/);
            const subject = subjectMatch ? subjectMatch[0].substring(0, 70).trim() : 'Analysis';
            const chatTitle = numFiles > 1 
                ? `📄 ${numFiles} Files: ${subject}` 
                : `📄 ${subject}`;
            document.getElementById('chatTitle').textContent = chatTitle.substring(0, 120);
            
            const fileInfo = numFiles > 1 ? `${numFiles} PDFs analyzed` : `${data.pages || '?'} pages, ${formatBytes(data.file_size)}`;
            showStatus('success', `Analysis complete (${fileInfo})`);
            
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
            renderSummaryInChat(currentContext);
            
            data.history.forEach(msg => {
                if (msg.role !== 'system') {  // Skip system messages
                    addMessage(msg.role, msg.content);
                }
            });
        } else {
            renderSummaryInChat(currentContext);
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
function testOllama() {
    const host = document.getElementById('ollamaHost').value.trim();
    const btn = document.getElementById('ollamaTestBtn');
    const result = document.getElementById('ollamaTestResult');

    if (!host) {
        result.innerHTML = '<span style="color:#721c24">Please enter a host URL</span>';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Testing...';
    result.innerHTML = '';

    fetch('/test_ollama', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ host: host })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const modelList = data.models && data.models.length
                ? `Available models: ${data.models.join(', ')}`
                : 'Connected (no models found - pull a model first)';
            result.innerHTML = `<span style="color:#155724">✓ ${data.message}<br>${modelList}</span>`;
            
            // Reload available models in the dropdown
            loadAvailableModels();
        } else {
            result.innerHTML = `<span style="color:#721c24">✗ ${data.error}</span>`;
        }
        btn.disabled = false;
        btn.textContent = 'Refresh Models & Test';
    })
    .catch(err => {
        result.innerHTML = `<span style="color:#721c24">✗ ${err.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Refresh Models & Test';
    });
}

function openSettings() {
    fetch('/get_ai_config')
        .then(r => r.json())
        .then(data => {
            document.getElementById('geminiKey').value = data.gemini.api_key || '';
            document.getElementById('geminiEnabled').checked = data.gemini.enabled || false;

            document.getElementById('openaiKey').value = data.openai.api_key || '';
            document.getElementById('openaiModel').value = data.openai.model || 'gpt-4-turbo';
            document.getElementById('openaiEnabled').checked = data.openai.enabled || false;

            document.getElementById('claudeKey').value = data.claude?.api_key || '';
            document.getElementById('claudeModel').value = data.claude?.model || 'claude-3-5-sonnet-latest';
            document.getElementById('claudeEnabled').checked = data.claude?.enabled || false;

            document.getElementById('groqKey').value = data.groq?.api_key || '';
            document.getElementById('groqModel').value = data.groq?.model || 'llama-3.3-70b-versatile';
            document.getElementById('groqEnabled').checked = data.groq?.enabled || false;

            document.getElementById('githubKey').value = data.github?.api_key || '';
            document.getElementById('githubModel').value = data.github?.model || 'gpt-4o-mini';
            document.getElementById('githubBaseUrl').value = data.github?.base_url || 'https://models.inference.ai.azure.com';
            document.getElementById('githubEnabled').checked = data.github?.enabled || false;

            document.getElementById('ollamaHost').value = data.ollama.host || 'http://localhost:11434';
            // Store the user preference but don't set it yet - we'll load models first
            window.userSelectedModel = data.ollama.model || '';
            document.getElementById('ollamaEnabled').checked = data.ollama.enabled || false;

            document.getElementById('settingsModal').classList.add('active');
            setupCompactSettingsMode();
            
            // Load available models
            loadAvailableModels();
        });
}

function closeSettings() {
    document.getElementById('settingsModal').classList.remove('active');
}

function loadAvailableModels() {
    fetch('/get_ollama_models')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('ollamaModel');
                const options = select.querySelectorAll('option');
                
                // Keep only the first option (auto-select)
                while (select.options.length > 1) {
                    select.remove(1);
                }
                
                // Add available models
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.name;
                    const ramInfo = model.fits_in_memory ? '✓' : '⚠️ Limited RAM';
                    option.textContent = `${model.name} (est. ${model.estimated_ram_gb.toFixed(1)}GB) ${ramInfo}`;
                    select.appendChild(option);
                });
                
                // Set current model if user has selected one
                if (window.userSelectedModel) {
                    select.value = window.userSelectedModel;
                } else {
                    select.value = ''; // Auto-select
                }
                
                // Update display info
                document.getElementById('availableRam').textContent = data.available_ram_gb.toFixed(1);
                document.getElementById('currentModel').textContent = data.current_model || 'Auto-selecting...';
                
            } else {
                console.error('Failed to load models:', data.error);
            }
        })
        .catch(err => {
            console.error('Error loading models:', err);
            document.getElementById('ollamaTestResult').innerHTML = `<span style="color:#d32f2f">Error loading models: ${err.message}</span>`;
        });
}

function onModelSelectionChange() {
    const selected = document.getElementById('ollamaModel').value;
    window.userSelectedModel = selected;
    
    if (selected === '') {
        console.log('Auto-selection enabled');
    } else {
        console.log('Manual model selected:', selected);
    }
}

function saveSettings() {
    const config = {
        gemini: {
            api_key: document.getElementById('geminiKey').value,
            enabled: document.getElementById('geminiEnabled').checked,
            model: 'gemini-pro'
        },
        openai: {
            api_key: document.getElementById('openaiKey').value,
            model: document.getElementById('openaiModel').value,
            enabled: document.getElementById('openaiEnabled').checked
        },
        claude: {
            api_key: document.getElementById('claudeKey').value,
            model: document.getElementById('claudeModel').value,
            enabled: document.getElementById('claudeEnabled').checked
        },
        groq: {
            api_key: document.getElementById('groqKey').value,
            model: document.getElementById('groqModel').value,
            enabled: document.getElementById('groqEnabled').checked
        },
        github: {
            api_key: document.getElementById('githubKey').value,
            model: document.getElementById('githubModel').value,
            base_url: document.getElementById('githubBaseUrl').value,
            enabled: document.getElementById('githubEnabled').checked
        },
        ollama: {
            host: document.getElementById('ollamaHost').value,
            model: document.getElementById('ollamaModel').value, // Use current dropdown value
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
            refreshProviderRadioAvailability();
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
