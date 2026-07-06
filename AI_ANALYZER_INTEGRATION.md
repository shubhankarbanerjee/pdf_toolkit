# AI PDF Analyzer - Web Integration

## Overview
The AI PDF Analyzer provides a modern web interface for analyzing PDF documents using multiple AI providers (OpenAI, Google Gemini, Ollama).

## Architecture

### Backend Components

#### 1. **Flask Routes** (`app.py`)
- `/ai_analyzer` - Main analyzer page
- `/upload_pdf` - File upload endpoint
- `/analyze_pdf` - PDF analysis with AI summary
- `/chat_pdf` - Chat with PDF content context
- `/get_ai_config` - Retrieve AI configuration
- `/save_ai_config` - Save/update AI settings

#### 2. **AI Analyzer Module** (`ai_pdf_analyzer.py`)
Three main classes:

**AIConfigManager**
- Loads/saves AI configuration from `ai_pdf_config.json`
- Manages API keys and provider settings
- Supports providers: Gemini, OpenAI, Ollama

**PDFTextExtractor**
- Extracts text from PDF files (up to 50 pages by default)
- Uses PyMuPDF (fitz) with PyPDF2 fallback
- Handles corrupted or encrypted PDFs gracefully

**AIPDFAnalyzer**
- Main analysis engine with provider abstraction
- `analyze_pdf()`: Generates document summary
- `chat_with_context()`: Conversational Q&A with document context
- Automatic provider fallback if primary unavailable

### Frontend Components

#### 1. **HTML Template** (`templates/ai_pdf_analyzer.html`)
Two-panel responsive layout:
- **Left Panel**: File upload area + file list
- **Right Panel**: 
  - Summary section (document overview)
  - Chat interface (Q&A)
  - Provider selection (radio buttons)

Features:
- Drag-and-drop file upload
- File size display
- Quick file removal
- Responsive mobile design

#### 2. **JavaScript** (`static/ai_pdf_analyzer.js`)
Client-side logic:
- File upload handling (drag-drop + click)
- PDF analysis with progress feedback
- Chat message management
- Configuration modal
- Auto-expanding textarea for messages
- Real-time status messages

## Configuration

### API Configuration File: `ai_pdf_config.json`
Located in the pdf_toolkit root directory:

```json
{
  "gemini": {
    "api_key": "your-gemini-key",
    "enabled": true,
    "model": "gemini-pro"
  },
  "openai": {
    "api_key": "your-openai-key",
    "enabled": false,
    "model": "gpt-4-turbo"
  },
  "ollama": {
    "host": "http://localhost:11434",
    "enabled": false,
    "model": "llama2"
  }
}
```

### Configuration in Web UI
Users can configure API keys via the Settings button in the header:
1. Click "Settings" → Configuration modal opens
2. Enter API keys for desired providers
3. Check "Enable" checkbox for active providers
4. Click "Save Settings" → Configuration persists

## Workflow

### Upload & Analysis
1. User navigates to `/ai_analyzer`
2. Uploads PDF via drag-drop or file picker
3. File appears in left panel with size info
4. User clicks "Analyze PDF"
5. Backend extracts text and sends to selected AI provider
6. Summary appears in right panel
7. User can ask questions about the PDF

### Chat Flow
1. Summary displays in highlighted section
2. User types question in textarea
3. Frontend sends message + file context to `/chat_pdf`
4. Backend retrieves full PDF text (cached per file)
5. AI provider generates response based on content
6. Chat messages appear in chronological order

## Supported File Types
- **PDF** (.pdf) - Primary format
- **Images** (.jpg, .jpeg, .png, .gif, .bmp, .webp)
- **Text** (.txt) - Plain text documents

## Error Handling

### Client-Side
- File type validation before upload
- API connectivity errors with user-friendly messages
- Missing API key detection in Settings
- Automatic textarea size adjustment

### Server-Side
- File existence verification before analysis
- API provider availability check
- Graceful fallback if primary provider unavailable
- Exception catching with descriptive error messages
- File cleanup via `/api/cleanup` endpoint

## Provider Priorities

### Fallback Chain
1. **User-Selected Provider** - If enabled and configured
2. **First Available** - If primary unavailable
3. **Error State** - If no providers available

### Provider Details

#### Gemini
- Free tier: 60 requests/min
- Model: gemini-pro
- Setup: Get key from [Google AI Studio](https://makersuite.google.com/app/apikey)

#### OpenAI
- Paid tier required
- Model: gpt-4-turbo
- Setup: Get key from [OpenAI Platform](https://platform.openai.com/api-keys)

#### Ollama
- Local inference, free
- Default: llama2 model
- Setup: Install Ollama, run `ollama serve`

## Performance Considerations

### Text Extraction
- Limits to 50 pages by default for performance
- Handles large PDFs gracefully
- Caching not implemented (each analysis re-extracts)

### Chat Context
- Full PDF text sent with each message
- Consider token limits for large documents
- Ollama has lower context windows than GPT-4/Gemini

### Concurrent Uploads
- No session management (all files in global dict)
- Browser local storage could enhance persistence
- Server-side file tracking via `ai_uploaded_files` dict

## Future Enhancements

1. **Session Management**
   - User-specific file storage
   - Persistent chat history
   - Cross-device synchronization

2. **Performance**
   - Server-side PDF text caching
   - Chunked document processing
   - Streaming responses for long summaries

3. **Features**
   - Document comparison (multiple PDFs)
   - Custom system prompts
   - Export chat history
   - PDF annotation with AI insights

4. **UI/UX**
   - Dark theme support
   - Real-time provider status indicator
   - Upload progress bar for large files
   - Typing indicator during analysis

## Deployment

### Prerequisites
- Python 3.8+
- Flask
- ai_pdf_analyzer.py with dependencies:
  - google.generativeai
  - openai
  - PyMuPDF (fitz)
  - PyPDF2
  - requests

### Installation
```bash
pip install flask google-generativeai openai PyMuPDF PyPDF2 requests
```

### Running
```bash
python app.py
# Navigate to http://localhost:5000/ai_analyzer
```

### Environment
- Static files: `/static/`
- Templates: `/templates/`
- Uploads: `/uploads/` (cleaned via `/api/cleanup`)
- Config: `ai_pdf_config.json` in root

## Testing Checklist

- [ ] File upload with drag-drop
- [ ] File upload with click picker
- [ ] Analyze PDF with Gemini
- [ ] Analyze PDF with OpenAI
- [ ] Analyze PDF with Ollama
- [ ] Chat with AI about PDF content
- [ ] Provider fallback when one unavailable
- [ ] Settings modal opens/closes
- [ ] API keys persist after save
- [ ] File removal from list
- [ ] Error handling for invalid files
- [ ] Error handling for missing API keys
- [ ] UI responsive on mobile

## Known Limitations

1. **No Session Persistence** - Files lost on app restart
2. **No Authentication** - Any user can access
3. **Limited Text Extraction** - 50 page default limit
4. **No Rate Limiting** - Vulnerable to abuse
5. **Simple Error Messages** - May not help debugging
6. **No Caching** - Each chat re-extracts PDF text

## Integration with Trading Monitor

The AI PDF Analyzer follows the same patterns as the FyersTrading app:
- Configuration via JSON files (ai_pdf_config.json)
- Multi-provider AI support (Gemini, OpenAI, Ollama)
- Provider fallback chain
- Error handling with user feedback
- Web-based GUI (Flask for pdf_toolkit vs PySide6 for trading)
