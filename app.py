"""
PDF Toolkit - Web-based PDF Processing Application
A platform-independent GUI that works on Android, iPhone, Windows, and macOS.
"""

import os
import io
import sys
import uuid
import copy
import tempfile
import traceback
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

# Import PDF processing modules
from pdf_processor import (
    merge_pdfs,
    split_pdf_by_size,
    ocr_pdf_to_pdf,
    split_odd_even_pdfs,
    compress_pdf,
    pdf_page_count,
    pdf_to_images,
    arrange_photos_on_a4_row,
    extract_best_text_from_pdf
)

# Import PDF Differ
try:
    from pdf_diff import PDFDiffer
    HAS_PDF_DIFF = True
except ImportError as e:
    print(f"[WARNING] PDF Diff not available: {e}")
    HAS_PDF_DIFF = False

# Import AI PDF Analyzer
try:
    from ai_pdf_analyzer import AIPDFAnalyzer, AIConfigManager, PDFTextExtractor
    HAS_AI_ANALYZER = True
except ImportError as e:
    print(f"[WARNING] AI PDF Analyzer not available: {e}")
    HAS_AI_ANALYZER = False

# Import Database Manager
try:
    from db_manager import DatabaseManager
    HAS_DB = True
except ImportError as e:
    print(f"[WARNING] Database Manager not available: {e}")
    HAS_DB = False

# Import PDF metadata and advanced text extraction
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    print(f"[WARNING] PyPDF2 not available for metadata handling")
    HAS_PYPDF2 = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    print(f"[WARNING] PyMuPDF not available for annotation form handling")
    HAS_FITZ = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    print(f"[WARNING] pdfplumber not available for advanced text extraction")
    HAS_PDFPLUMBER = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Initialize AI Analyzer
ai_analyzer = None
if HAS_AI_ANALYZER:
    ai_analyzer = AIPDFAnalyzer()

# Initialize Database Manager
db_manager = None
if HAS_DB:
    try:
        db_manager = DatabaseManager()
        print(f"[OK] Database initialized: {db_manager.db_path}")
    except Exception as e:
        print(f"[ERROR] Database initialization failed: {e}")
        HAS_DB = False

# Track uploaded files for AI analysis (legacy, can be deprecated)
ai_uploaded_files = {}

# Allowed extensions
ALLOWED_PDF_EXTENSIONS = {'pdf'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PDF_EXTENSIONS


def allowed_image_file(filename):
    """Check if file extension is an allowed image type."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _resolve_analysis_files(primary_file_id, session_id, additional_file_ids=None):
    """Resolve and validate primary + additional files for AI analysis."""
    if additional_file_ids is None:
        additional_file_ids = []

    ordered_ids = [primary_file_id] + [fid for fid in additional_file_ids if fid and fid != primary_file_id]
    seen = set()
    resolved = []

    supported_exts = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.txt')

    for fid in ordered_ids:
        if not fid or fid in seen:
            continue
        seen.add(fid)

        pdf_info = db_manager.get_pdf(fid)
        if not pdf_info:
            raise ValueError(f"File not found: {fid}")
        if pdf_info.get('session_id') != session_id:
            raise PermissionError(f"File does not belong to session: {fid}")

        source_name = (pdf_info.get('original_name') or str(pdf_info.get('file_path', ''))).lower()
        if not source_name.endswith(supported_exts):
            raise ValueError('Unsupported file type for AI analyzer. Please upload PDF, image, or TXT files only.')

        resolved.append(pdf_info)

    return resolved


def _extract_context_for_file(pdf_info, requested_lang=None):
    """Extract text context for a single file using cache when available."""
    file_id = pdf_info.get('file_id')
    file_path = pdf_info.get('file_path')
    source_name = (pdf_info.get('original_name') or str(file_path)).lower()
    txt_mode = source_name.endswith('.txt')

    text_content = db_manager.get_cached_text(file_id)
    if text_content:
        return text_content

    if txt_mode:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text_content = f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1', errors='ignore') as f:
                text_content = f.read()
        if text_content:
            db_manager.cache_pdf_text(file_id, text_content, pages=1)
        return text_content or ''

    # Keep AI analyzer extraction aligned with OCR Download Text route.
    best = extract_best_text_from_pdf(file_path, lang=requested_lang, dpi=300)
    text_content = best.get('text', '') or ''
    if text_content:
        db_manager.cache_pdf_text(file_id, text_content, pages=PDFTextExtractor._get_page_count(file_path))
        return text_content

    # Fallback to analyzer extractor when shared OCR pipeline returns empty text.
    return PDFTextExtractor.extract_text(
        file_path,
        max_pages=None,
        db_manager=db_manager,
        file_id=file_id,
        use_ocr=True,
        languages=requested_lang,
    )


def _build_combined_context(file_records, requested_lang=None):
    """Build merged context and PDF path list for multi-file AI analysis."""
    sections = []
    pdf_paths = []

    for record in file_records:
        text = _extract_context_for_file(record, requested_lang=requested_lang)
        if not text or not text.strip():
            continue

        original_name = record.get('original_name') or record.get('filename') or record.get('file_id')
        sections.append(f"\n===== DOCUMENT: {original_name} =====\n{text}")

        source_name = (record.get('original_name') or str(record.get('file_path', ''))).lower()
        if source_name.endswith('.pdf'):
            pdf_paths.append(record.get('file_path'))

    return '\n\n'.join(sections), pdf_paths


SESSION_AI_CONFIG_KEY = 'ai_config_session'
_AI_KEY_PROVIDERS = {'gemini', 'openai', 'claude', 'groq', 'github'}


def _build_effective_ai_config():
    """Build per-browser AI config from defaults + session overrides."""
    base_config = ai_analyzer.config_manager.get_config() if ai_analyzer else {}
    effective = copy.deepcopy(base_config)

    # Do not inherit shared API keys across browser sessions.
    for provider in _AI_KEY_PROVIDERS:
        if provider in effective and isinstance(effective[provider], dict):
            effective[provider]['api_key'] = ''
            effective[provider]['enabled'] = False

    session_cfg = session.get(SESSION_AI_CONFIG_KEY, {})
    if not isinstance(session_cfg, dict):
        session_cfg = {}

    for provider, values in session_cfg.items():
        if provider not in effective or not isinstance(values, dict):
            continue
        if not isinstance(effective[provider], dict):
            effective[provider] = {}
        effective[provider].update(values)

    return effective


def _create_session_ai_analyzer():
    """Create an analyzer instance bound to the current browser session config."""
    if not HAS_AI_ANALYZER:
        return None

    runtime_analyzer = AIPDFAnalyzer()
    runtime_analyzer.config = _build_effective_ai_config()
    runtime_analyzer._init_providers()
    return runtime_analyzer


def _provider_available(analyzer, provider):
    """Return True when selected provider is configured for current session."""
    return {
        'gemini': analyzer.gemini_initialized,
        'openai': analyzer.openai_initialized,
        'claude': analyzer.claude_initialized,
        'groq': analyzer.groq_initialized,
        'github': analyzer.github_initialized,
        'ollama': analyzer.ollama_available,
    }.get(provider, False)


def _sanitize_session_ai_config(config):
    """Sanitize incoming AI config payload before storing in browser session."""
    if not isinstance(config, dict):
        return {}

    base = ai_analyzer.config_manager.get_config() if ai_analyzer else {}
    allowed = {
        'gemini': {'api_key', 'enabled', 'model'},
        'openai': {'api_key', 'enabled', 'model'},
        'claude': {'api_key', 'enabled', 'model'},
        'groq': {'api_key', 'enabled', 'model'},
        'github': {'api_key', 'enabled', 'model', 'base_url'},
        'ollama': {'enabled', 'model', 'host'},
    }

    sanitized = {}
    for provider, fields in allowed.items():
        incoming = config.get(provider, {}) if isinstance(config.get(provider), dict) else {}
        provider_cfg = {}

        # Keep base defaults for display-friendly fields.
        base_provider = base.get(provider, {}) if isinstance(base.get(provider), dict) else {}
        for k, v in base_provider.items():
            if k in fields and k != 'api_key':
                provider_cfg[k] = v

        for key in fields:
            if key not in incoming:
                continue
            value = incoming.get(key)
            if key == 'enabled':
                provider_cfg[key] = bool(value)
            elif key == 'api_key':
                provider_cfg[key] = str(value or '').strip()
            else:
                provider_cfg[key] = str(value or '').strip()

        if provider in _AI_KEY_PROVIDERS:
            key_val = provider_cfg.get('api_key', '')
            if provider_cfg.get('enabled') and not key_val:
                provider_cfg['enabled'] = False

        sanitized[provider] = provider_cfg

    return sanitized


def _parse_form_mapping_text(mapping_text):
    """Parse Field:Value mappings from ';|;' or newline-delimited input."""
    if not mapping_text or not str(mapping_text).strip():
        raise ValueError('No field mappings provided')

    raw = str(mapping_text).strip().replace('\r\n', '\n').replace('\r', '\n')
    chunks = raw.split(';|;') if ';|;' in raw else raw.split('\n')
    entries = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]

    mappings = {}
    for entry in entries:
        if ':' not in entry:
            raise ValueError(f'Invalid entry "{entry}". Use "Field : Value" format.')

        field_name, value = entry.split(':', 1)
        field_name = field_name.strip()
        value = value.strip()

        if not field_name:
            raise ValueError(f'Field name is missing for value "{value}"')
        if value == '':
            raise ValueError(f'Value is not defined for field "{field_name}"')

        mappings[field_name] = value

    if not mappings:
        raise ValueError('No valid field mappings found')

    return mappings


def _field_is_read_only(field_dict):
    """Return True when PDF field dictionary marks the field as read-only."""
    try:
        ff = int(field_dict.get('/Ff', 0) or 0)
        return bool(ff & 1)
    except Exception:
        return False


def _collect_editable_pdf_form_fields(reader):
    """Collect editable form fields from AcroForm + page widget annotations."""
    collected = {}

    def _add_field(name, value):
        key = str(name).strip()
        if not key:
            return
        val = '' if value is None else str(value)
        if key not in collected or (not collected[key] and val):
            collected[key] = val

    # Standard AcroForm fields
    fields = reader.get_fields() or {}
    for name, details in fields.items():
        field_dict = details if isinstance(details, dict) else {}
        if _field_is_read_only(field_dict):
            continue
        _add_field(name, field_dict.get('/V', ''))

    # Editable widget annotations present on pages (can be missing from get_fields)
    for page in reader.pages:
        annots = page.get('/Annots') or []
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object()
                if str(annot.get('/Subtype', '')) != '/Widget':
                    continue
                if _field_is_read_only(annot):
                    continue

                name = annot.get('/T')
                if not name:
                    continue
                _add_field(name, annot.get('/V', ''))
            except Exception:
                continue

    return [{'name': k, 'value': v, 'source': 'form'} for k, v in collected.items()]


def _collect_editable_annotation_fields(pdf_bytes):
    """Collect editable annotation content as pseudo form fields."""
    if not HAS_FITZ:
        return []

    fields = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception:
        return []

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            annots = list(page.annots() or [])
            for annot_index, annot in enumerate(annots, start=1):
                try:
                    info = annot.info or {}
                    content = (info.get('content') or '').strip()
                    if content == '':
                        continue

                    fields.append({
                        'name': f'Annotation|Page {page_index + 1}|#{annot_index}',
                        'value': content,
                        'source': 'annotation',
                        'page_index': page_index,
                        'annotation_index': annot_index,
                    })
                except Exception:
                    continue
    finally:
        doc.close()

    return fields


def _apply_annotation_updates(pdf_bytes, mapping_by_name):
    """Apply updated annotation content using names from _collect_editable_annotation_fields."""
    if not HAS_FITZ:
        return pdf_bytes

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            annots = list(page.annots() or [])
            for annot_index, annot in enumerate(annots, start=1):
                key = f'Annotation|Page {page_index + 1}|#{annot_index}'
                if key not in mapping_by_name:
                    continue

                try:
                    annot.set_info(content=str(mapping_by_name[key]))
                    annot.update()
                except Exception:
                    continue

        output = doc.tobytes()
    finally:
        doc.close()

    return output


def _bind_or_validate_browser_session(session_id):
    """Bind analyzer session ID to current browser session, or validate existing binding."""
    if not session_id:
        return False, 'Session ID required'

    bound_session_id = session.get('pdf_analyzer_session_id')
    if not bound_session_id:
        session['pdf_analyzer_session_id'] = session_id
        session.modified = True
        return True, None

    if bound_session_id != session_id:
        return False, 'Session ID does not match this browser session. Please start a new session.'

    return True, None


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/api/merge', methods=['POST'])
def api_merge():
    """Merge two PDF files."""
    try:
        if 'file1' not in request.files or 'file2' not in request.files:
            return jsonify({'error': 'Two PDF files are required'}), 400
        
        file1 = request.files['file1']
        file2 = request.files['file2']
        
        if not (allowed_file(file1.filename) and allowed_file(file2.filename)):
            return jsonify({'error': 'Both files must be PDFs'}), 400
        
        # Generate unique IDs for files
        unique_id = str(uuid.uuid4())
        file1_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_1_{secure_filename(file1.filename)}")
        file2_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_2_{secure_filename(file2.filename)}")
        
        file1.save(file1_path)
        file2.save(file2_path)
        
        # Merge PDFs
        output_filename, output_path = merge_pdfs(file1_path, file2_path)
        
        if output_path:
            return jsonify({
                'success': True,
                'filename': output_filename,
                'download_url': f'/api/download/{os.path.basename(output_path)}'
            })
        else:
            return jsonify({'error': 'Failed to merge PDFs'}), 500
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/split', methods=['POST'])
def api_split():
    """Split a PDF file by size."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        max_size = request.form.get('max_size', '200')
        max_size = int(max_size)
        
        # Save uploaded file
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)
        
        # Split PDF
        output_files = split_pdf_by_size(file_path, max_size)
        
        if output_files:
            download_urls = [f'/api/download/{os.path.basename(f)}' for f in output_files]
            return jsonify({
                'success': True,
                'files': [
                    {'filename': os.path.basename(f), 'download_url': url}
                    for f, url in zip(output_files, download_urls)
                ]
            })
        else:
            return jsonify({'error': 'Failed to split PDF'}), 500
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/ocr', methods=['POST'])
def api_ocr():
    """Perform OCR on a PDF file."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        dpi = request.form.get('dpi', '150')
        lang = request.form.get('lang', 'eng+hin')
        max_workers = request.form.get('workers', '4')
        
        dpi = int(dpi)
        max_workers = int(max_workers)
        
        # Save uploaded file
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)
        
        # Perform OCR
        output_filename, output_path = ocr_pdf_to_pdf(file_path, dpi, lang, max_workers)
        
        if output_path:
            return jsonify({
                'success': True,
                'filename': output_filename,
                'download_url': f'/api/download/{os.path.basename(output_path)}'
            })
        else:
            return jsonify({'error': 'Failed to perform OCR'}), 500
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/split_odd_even', methods=['POST'])
def api_split_odd_even():
    """Split a PDF into odd and even pages."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Save uploaded file
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)
        
        # Split odd/even
        odd_path, even_path = split_odd_even_pdfs(file_path)
        
        if odd_path or even_path:
            result = {'success': True, 'files': []}
            if odd_path:
                result['files'].append({
                    'filename': os.path.basename(odd_path),
                    'download_url': f'/api/download/{os.path.basename(odd_path)}'
                })
            if even_path:
                result['files'].append({
                    'filename': os.path.basename(even_path),
                    'download_url': f'/api/download/{os.path.basename(even_path)}'
                })
            return jsonify(result)
        else:
            return jsonify({'error': 'Failed to split PDF'}), 500
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/compress', methods=['POST'])
def api_compress():
    """Compress a PDF file with OCR."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        dpi = request.form.get('dpi', '100')
        lang = request.form.get('lang', 'eng+hin')
        
        dpi = int(dpi)
        
        # Save uploaded file
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)
        
        # Compress with OCR
        output_filename, output_path = compress_pdf(file_path, dpi, lang)
        
        if output_path:
            return jsonify({
                'success': True,
                'filename': output_filename,
                'download_url': f'/api/download/{os.path.basename(output_path)}'
            })
        else:
            return jsonify({'error': 'Failed to compress PDF'}), 500
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf_page_count', methods=['POST'])
def api_pdf_page_count():
    """Return the page count for an uploaded PDF."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400

        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400

        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)

        pages = pdf_page_count(file_path)
        return jsonify({'success': True, 'pages': pages})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf_to_images', methods=['POST'])
def api_pdf_to_images():
    """Convert selected PDF pages to A4 image files."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400

        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400

        from_page = int(request.form.get('from_page', '1'))
        to_page = request.form.get('to_page')
        if to_page is not None and to_page != '':
            to_page = int(to_page)
        output_format = request.form.get('format', 'png')
        dpi = int(request.form.get('dpi', '600'))

        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)

        output_files = pdf_to_images(
            file_path,
            output_format=output_format,
            from_page=from_page,
            to_page=to_page,
            dpi=dpi,
            output_dir=app.config['OUTPUT_FOLDER']
        )

        if output_files:
            return jsonify({
                'success': True,
                'files': [
                    {'filename': os.path.basename(f), 'download_url': f'/api/download/{os.path.basename(f)}'}
                    for f in output_files
                ]
            })
        else:
            return jsonify({'error': 'Failed to convert PDF to images'}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/photo_sheet', methods=['POST'])
def api_photo_sheet():
    """Create a passport-photo sheet on an A4 PDF page."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'An image file is required'}), 400

        file = request.files['file']
        if not allowed_image_file(file.filename):
            return jsonify({'error': 'File must be an image (PNG, JPG, JPEG, WEBP, BMP, GIF)'}), 400

        copies = int(request.form.get('copies', '6'))
        photo_width_mm = float(request.form.get('photo_width_mm', '35'))
        photo_height_mm = float(request.form.get('photo_height_mm', '45'))
        margin_mm = float(request.form.get('margin_mm', '5'))
        gap_mm = float(request.form.get('gap_mm', '5'))
        top_margin_mm = float(request.form.get('top_margin_mm', '5'))
        dpi = int(request.form.get('dpi', '300'))

        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)

        output_filename, output_path = arrange_photos_on_a4_row(
            file_path,
            copies=copies,
            photo_width_mm=photo_width_mm,
            photo_height_mm=photo_height_mm,
            margin_mm=margin_mm,
            gap_mm=gap_mm,
            top_margin_mm=top_margin_mm,
            dpi=dpi,
            output_dir=app.config['OUTPUT_FOLDER']
        )

        if output_path:
            return jsonify({
                'success': True,
                'filename': output_filename,
                'download_url': f'/api/download/{os.path.basename(output_path)}'
            })
        else:
            return jsonify({'error': 'Failed to create photo sheet'}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/download/<filename>')
def download_file(filename):
    """Download a processed file."""
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], secure_filename(filename))
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    """Clean up old files (optional maintenance endpoint)."""
    import time
    try:
        max_age = int(request.form.get('max_age', '3600'))  # Default 1 hour
        current_time = time.time()
        cleaned = 0
        
        for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > max_age:
                    os.remove(file_path)
                    cleaned += 1
        
        return jsonify({'success': True, 'cleaned_files': cleaned})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# AI PDF ANALYZER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/ai_analyzer')
def ai_analyzer_page():
    """Render AI PDF Analyzer page."""
    return render_template('ai_pdf_analyzer.html')


# ═══════════════════════════════════════════════════════════════════════════════
# PDF DIFF ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/diff')
def diff_page():
    """Render PDF Diff page."""
    return render_template('pdf_diff.html')


@app.route('/api/diff', methods=['POST'])
def api_diff():
    """Compare two PDF files and return structured diff result."""
    if not HAS_PDF_DIFF:
        return jsonify({'success': False, 'error': 'PDF Diff module not available'}), 400

    try:
        if 'file1' not in request.files or 'file2' not in request.files:
            return jsonify({'success': False, 'error': 'Two PDF files are required'}), 400

        file1 = request.files['file1']
        file2 = request.files['file2']

        if not file1.filename or not file2.filename:
            return jsonify({'success': False, 'error': 'Both files must be selected'}), 400

        allowed = {'pdf', 'txt'}
        for f in (file1, file2):
            ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
            if ext not in allowed:
                return jsonify({'success': False, 'error': f'Only PDF and TXT files are supported (got .{ext})'}), 400

        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        path1 = os.path.join(app.config['UPLOAD_FOLDER'], f"{uid1}_{secure_filename(file1.filename)}")
        path2 = os.path.join(app.config['UPLOAD_FOLDER'], f"{uid2}_{secure_filename(file2.filename)}")

        file1.save(path1)
        file2.save(path2)

        try:
            result = PDFDiffer.diff(path1, path2)
            result['file1_name'] = file1.filename
            result['file2_name'] = file2.filename
            return jsonify(result)
        finally:
            for p in (path1, path2):
                try:
                    os.remove(p)
                except Exception:
                    pass

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION MANAGEMENT ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/create_session', methods=['POST'])
def create_session_route():
    """Create a new AI analyzer session."""
    if not HAS_DB:
        return jsonify({'success': False, 'error': 'Database not available'}), 400
    
    try:
        session_id = str(uuid.uuid4())
        db_manager.create_session(session_id)
        session['pdf_analyzer_session_id'] = session_id
        session.modified = True
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/clear_chat/<session_id>', methods=['POST'])
def clear_chat(session_id):
    """Clear chat history for a session (keep PDFs intact)."""
    if not HAS_DB:
        return jsonify({'success': False, 'error': 'Database not available'}), 400
    
    try:
        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': err}), 403

        db_manager.delete_chat_history(session_id)
        return jsonify({'success': True, 'message': 'Chat history cleared'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/clear_pdfs/<session_id>', methods=['POST'])
def clear_pdfs(session_id):
    """Delete all PDFs and related chat records for a browser-bound analyzer session."""
    if not HAS_DB:
        return jsonify({'success': False, 'error': 'Database not available'}), 400

    try:
        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': err}), 403

        pdfs = db_manager.get_session_pdfs(session_id)
        deleted = 0
        for pdf in pdfs:
            file_id = pdf.get('file_id')
            if not file_id:
                continue
            db_manager.delete_pdf(file_id)
            deleted += 1

        return jsonify({'success': True, 'deleted_pdfs': deleted})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Check application and database health."""
    health = {
        'status': 'ok',
        'modules': {
            'ai_analyzer': HAS_AI_ANALYZER,
            'database': HAS_DB,
            'pdf_diff': HAS_PDF_DIFF
        },
        'database_info': {}
    }
    
    if HAS_DB:
        try:
            if db_manager:
                health['database_info']['path'] = db_manager.db_path
                health['database_info']['exists'] = os.path.exists(db_manager.db_path)
                # Try to get database info
                session = db_manager.get_session('test-health-check')
                health['database_info']['accessible'] = True
                health['database_info']['test_query'] = 'passed'
            else:
                health['database_info']['accessible'] = False
                health['database_info']['error'] = 'db_manager is None'
        except Exception as e:
            health['database_info']['accessible'] = False
            health['database_info']['error'] = str(e)
            health['status'] = 'warning'
    
    return jsonify(health), 200 if health['status'] == 'ok' else 500


@app.route('/get_session_info/<session_id>', methods=['GET'])
def get_session_info(session_id):
    """Get session information and stats."""
    if not HAS_DB:
        return jsonify({'error': 'Database not available'}), 400
    
    try:
        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'error': err}), 403

        session_info = db_manager.get_session(session_id)
        if not session_info:
            return jsonify({'error': 'Session not found'}), 404
        
        pdfs = db_manager.get_session_pdfs(session_id)
        db_manager.update_session_access(session_id)
        
        return jsonify({
            'success': True,
            'session': dict(session_info),
            'pdfs': [
                {
                    'file_id': p['file_id'],
                    'filename': p['original_name'],
                    'size': p['file_size'],
                    'uploaded': p['upload_time'],
                    'pages': p['pages']
                }
                for p in pdfs
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/cleanup_old_sessions', methods=['POST'])
def cleanup_old_sessions():
    """Clean up sessions older than 24 hours."""
    if not HAS_DB:
        return jsonify({'success': False, 'error': 'Database not available'}), 400
    
    try:
        hours = request.form.get('hours', '24', type=int)
        db_manager.cleanup_old_sessions(hours=hours)
        stats = db_manager.get_database_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PDF UPLOAD & MANAGEMENT ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    """Upload PDF/image for AI analysis with database storage."""
    if not HAS_AI_ANALYZER or not HAS_DB:
        return jsonify({'success': False, 'error': 'AI analyzer or database not available'}), 400
    
    try:
        session_id = request.form.get('session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID required'}), 400

        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': err}), 403
        
        # Verify session exists
        if not db_manager.get_session(session_id):
            return jsonify({'success': False, 'error': 'Invalid session'}), 400
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Accept PDF, image, and text files
        allowed_types = {'pdf', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'txt'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_types:
            return jsonify({'success': False, 'error': f'File type .{file_ext} not supported. Upload PDF, image, or TXT files only.'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4())
        unique_filename = f"{file_id}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        # Calculate file hash
        file_hash = PDFTextExtractor.get_file_hash(file_path)
        file_size = os.path.getsize(file_path)
        
        # Store in database
        db_manager.add_pdf(
            file_id=file_id,
            session_id=session_id,
            filename=unique_filename,
            original_name=filename,
            file_size=file_size,
            file_path=file_path,
            file_hash=file_hash
        )
        
        # Keep legacy tracking
        ai_uploaded_files[unique_filename] = {
            'original_name': filename,
            'path': file_path,
            'size': file_size,
            'type': file.content_type,
            'file_id': file_id,
            'session_id': session_id
        }
        
        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': unique_filename,
            'original_name': filename,
            'size': file_size
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/delete_pdf/<file_id>', methods=['DELETE'])
def delete_pdf(file_id):
    """Delete a PDF from session and database."""
    if not HAS_DB:
        return jsonify({'success': False, 'error': 'Database not available'}), 400
    
    try:
        pdf_info = db_manager.get_pdf(file_id)
        if not pdf_info:
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        db_manager.delete_pdf(file_id)
        
        return jsonify({'success': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PDF ANALYSIS ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/analyze_pdf', methods=['POST'])
def analyze_pdf():
    """Analyze PDF and generate summary with database caching."""
    if not HAS_AI_ANALYZER or not HAS_DB:
        return jsonify({'success': False, 'error': 'AI analyzer or database not available'}), 400
    
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        session_id = data.get('session_id')
        provider = data.get('provider', 'gemini')
        additional_files = data.get('additional_files') or []
        requested_lang = (data.get('lang') or 'auto').strip()
        if requested_lang.lower() in {'', 'auto', 'detect'}:
            requested_lang = None
        
        if not file_id or not session_id:
            return jsonify({'success': False, 'error': 'File ID and Session ID required'}), 400

        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': err}), 403
        
        try:
            file_records = _resolve_analysis_files(file_id, session_id, additional_files)
        except PermissionError as pe:
            return jsonify({'success': False, 'error': str(pe)}), 403
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400

        combined_context, pdf_paths = _build_combined_context(file_records, requested_lang=requested_lang)
        if not combined_context.strip():
            return jsonify({'success': False, 'error': 'Failed to extract text from selected file(s)'}), 500

        runtime_analyzer = _create_session_ai_analyzer()
        if not _provider_available(runtime_analyzer, provider):
            return jsonify({
                'success': False,
                'error': f'Provider "{provider}" is not configured for this browser session. Open AI Configuration and add your API key.',
                'requires_config': True,
                'provider': provider,
            }), 400

        result = runtime_analyzer.chat_with_context(
            "Summarize these selected documents in a concise way, highlighting key points and important details.",
            combined_context,
            provider,
            pdf_paths=pdf_paths,
        )
        
        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Analysis failed')
            }), 500
        
        # Store analysis in chat history
        analysis_id = str(uuid.uuid4())
        db_manager.add_chat_message(
            message_id=analysis_id,
            file_id=file_id,
            session_id=session_id,
            role='system',
            content=result['response'],
            provider=result['provider']
        )
        
        return jsonify({
            'success': True,
            'summary': result['response'],
            'provider': result['provider'],
            'pages': sum((rec.get('pages') or 0) for rec in file_records),
            'file_size': sum((rec.get('file_size') or 0) for rec in file_records),
            'analyzed_files': len(file_records),
            'ocr_language': requested_lang or 'auto',
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/chat_pdf', methods=['POST'])
def chat_pdf():
    """Chat with AI about PDF content with conversation history."""
    if not HAS_AI_ANALYZER or not HAS_DB:
        return jsonify({'success': False, 'error': 'AI analyzer or database not available'}), 400
    
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        session_id = data.get('session_id')
        message = data.get('message')
        provider = data.get('provider', 'gemini')
        additional_files = data.get('additional_files') or []
        requested_lang = (data.get('lang') or 'auto').strip()
        if requested_lang.lower() in {'', 'auto', 'detect'}:
            requested_lang = None
        
        if not file_id or not session_id or not message:
            return jsonify({'success': False, 'error': 'File ID, Session ID, and message required'}), 400

        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': err}), 403
        
        try:
            file_records = _resolve_analysis_files(file_id, session_id, additional_files)
        except PermissionError as pe:
            return jsonify({'success': False, 'error': str(pe)}), 403
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400

        combined_context, pdf_paths = _build_combined_context(file_records, requested_lang=requested_lang)
        if not combined_context.strip():
            return jsonify({'success': False, 'error': 'Failed to extract text from selected file(s)'}), 500

        runtime_analyzer = _create_session_ai_analyzer()
        if not _provider_available(runtime_analyzer, provider):
            return jsonify({
                'success': False,
                'error': f'Provider "{provider}" is not configured for this browser session. Open AI Configuration and add your API key.',
                'requires_config': True,
                'provider': provider,
            }), 400

        result = runtime_analyzer.chat_with_context(message, combined_context, provider, pdf_paths=pdf_paths)
        
        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Chat failed')
            }), 500
        
        # Store conversation in database
        user_msg_id = str(uuid.uuid4())
        ai_msg_id = str(uuid.uuid4())
        
        db_manager.add_chat_message(user_msg_id, file_id, session_id, 'user', message, None)
        db_manager.add_chat_message(ai_msg_id, file_id, session_id, 'assistant', result['response'], provider)
        
        return jsonify({
            'success': True,
            'response': result['response'],
            'provider': result['provider']
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/get_chat_history/<file_id>', methods=['GET'])
def get_chat_history(file_id):
    """Get chat history for a PDF."""
    if not HAS_DB:
        return jsonify({'error': 'Database not available'}), 400
    
    try:
        session_id = request.args.get('session_id')
        limit = request.args.get('limit', '50', type=int)
        
        if not session_id:
            return jsonify({'error': 'Session ID required'}), 400

        ok, err = _bind_or_validate_browser_session(session_id)
        if not ok:
            return jsonify({'error': err}), 403
        
        # Verify file belongs to session
        pdf_info = db_manager.get_pdf(file_id)
        if not pdf_info or pdf_info['session_id'] != session_id:
            return jsonify({'error': 'Access denied'}), 403
        
        history = db_manager.get_chat_history(file_id, limit)
        
        return jsonify({
            'success': True,
            'history': [
                {
                    'role': h['role'],
                    'content': h['content'],
                    'timestamp': h['timestamp'],
                    'provider': h['provider']
                }
                for h in history
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/test_ollama', methods=['POST'])
def test_ollama():
    """Test Ollama/Msty connection - tries multiple endpoint variants."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        data = request.get_json()
        host = data.get('host', '').rstrip('/')
        if not host:
            return jsonify({'success': False, 'error': 'Host URL required'}), 400
        
        import requests as req
        
        # Try endpoints in order: native Ollama, then Msty/OpenAI-compatible
        endpoints_to_try = [
            ('GET', f'{host}/api/tags',  'Ollama native API', 'models'),
            ('GET', f'{host}/v1/models', 'OpenAI-compatible API (Msty)', 'data'),
        ]
        
        for method, url, api_type, key in endpoints_to_try:
            try:
                resp = req.request(method, url, timeout=5)
                if resp.status_code == 200:
                    models = []
                    try:
                        resp_data = resp.json()
                        raw = resp_data.get(key, [])
                        # Ollama native: [{name: ...}]  OpenAI-compat: [{id: ...}]
                        models = [m.get('name') or m.get('id', '') for m in raw if isinstance(m, dict)]
                    except Exception:
                        pass
                    
                    models = [m for m in models if m]
                    best_model = _score_models_for_api(models) if models else None
                    
                    return jsonify({
                        'success': True,
                        'message': f'Connected via {api_type} at {host}',
                        'api_type': api_type,
                        'models': models,
                        'best_model': best_model,
                        'best_model_info': f'Will auto-use "{best_model}" for analysis' if best_model else 'No models available'
                    })
            except req.exceptions.ConnectionError:
                continue  # try next endpoint variant
            except req.exceptions.Timeout:
                return jsonify({'success': False, 'error': f'Connection timed out at {host} - host reachable but slow'})
            except Exception:
                continue
        
        # All endpoints failed
        return jsonify({
            'success': False,
            'error': (
                f'Cannot connect to {host}. '
                'Check: (1) correct host/port, '
                '(2) Msty/Ollama is running on remote machine, '
                '(3) firewall allows the port, '
                '(4) Msty "Network Access" is enabled in its settings.'
            )
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _score_models_for_api(models: list[str]) -> str:
    """Score and select the best model for PDF analysis from a list of model names."""
    scored = []
    
    for name in models:
        if not name:
            continue
        
        score = 0
        name_lower = name.lower()
        
        # Vision models: highest priority for PDF analysis
        if 'vision' in name_lower:
            score += 100
        
        # Specific good models
        if any(x in name_lower for x in ['llama3', 'mistral', 'neural-chat', 'yi', 'qwen']):
            score += 50
        
        # Avoid very small models
        if any(x in name_lower for x in ['0.5b', '1b', '2b']):
            score -= 30
        
        # Prefer larger models (7b, 13b, 70b)
        if '70b' in name_lower or '65b' in name_lower:
            score += 40
        elif '13b' in name_lower:
            score += 20
        elif '7b' in name_lower:
            score += 10
        
        scored.append((name, score))
    
    if scored:
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]
    
    return models[0] if models else None


@app.route('/get_ai_config', methods=['GET'])
def get_ai_config():
    """Get current AI configuration for this browser session."""
    if not HAS_AI_ANALYZER:
        return jsonify({'error': 'AI analyzer not available'}), 400
    
    try:
        config = _build_effective_ai_config()

        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save_ai_config', methods=['POST'])
def save_ai_config():
    """Save AI configuration for current browser session only."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        config = request.get_json()
        session[SESSION_AI_CONFIG_KEY] = _sanitize_session_ai_config(config)
        session.modified = True
        return jsonify({'success': True, 'scope': 'browser_session'})
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/get_ollama_models', methods=['GET'])
def get_ollama_models():
    """Get list of available Ollama models with metadata."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        runtime_analyzer = _create_session_ai_analyzer()
        models = runtime_analyzer.get_available_ollama_models()
        current_model = runtime_analyzer.ollama_model
        available_ram = runtime_analyzer._get_available_ram_gb()
        
        return jsonify({
            'success': True,
            'models': models,
            'current_model': current_model,
            'available_ram_gb': available_ram
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/set_ollama_model', methods=['POST'])
def set_ollama_model():
    """Set user's preferred Ollama model."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        data = request.get_json()
        model_name = data.get('model')
        
        if not model_name:
            return jsonify({'success': False, 'error': 'Model name required'}), 400
        
        session_cfg = session.get(SESSION_AI_CONFIG_KEY, {})
        if not isinstance(session_cfg, dict):
            session_cfg = {}
        ollama_cfg = session_cfg.get('ollama', {}) if isinstance(session_cfg.get('ollama'), dict) else {}
        ollama_cfg['model'] = model_name
        session_cfg['ollama'] = ollama_cfg
        session[SESSION_AI_CONFIG_KEY] = session_cfg
        session.modified = True

        return jsonify({
            'success': True,
            'message': f'Model set to {model_name}',
            'current_model': model_name,
            'scope': 'browser_session'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# PDF METADATA AND ADVANCED TEXT EXTRACTION ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/get_metadata', methods=['POST'])
def get_metadata():
    """Extract metadata from a PDF file."""
    if not HAS_PYPDF2:
        return jsonify({'error': 'PyPDF2 not available'}), 400
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Read PDF metadata
        pdf_reader = PyPDF2.PdfReader(file.stream)
        metadata = pdf_reader.metadata
        
        result = {
            'title': metadata.get('/Title', '') if metadata else '',
            'author': metadata.get('/Author', '') if metadata else '',
            'subject': metadata.get('/Subject', '') if metadata else '',
            'creator': metadata.get('/Creator', '') if metadata else '',
            'producer': metadata.get('/Producer', '') if metadata else '',
            'creation_date': str(metadata.get('/CreationDate', '')) if metadata else '',
            'modification_date': str(metadata.get('/ModDate', '')) if metadata else '',
            'pages': len(pdf_reader.pages) if pdf_reader.pages else 0
        }
        
        return jsonify(result)
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/get_pdf_form_fields', methods=['POST'])
def get_pdf_form_fields():
    """Read fillable field names/values from a PDF form."""
    if not HAS_PYPDF2:
        return jsonify({'error': 'PyPDF2 not available'}), 400

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400

        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400

        pdf_bytes = file.read()
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        form_fields = _collect_editable_pdf_form_fields(reader)
        annotation_fields = _collect_editable_annotation_fields(pdf_bytes)

        return jsonify({'success': True, 'fields': form_fields + annotation_fields})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/fill_pdf_form', methods=['POST'])
def fill_pdf_form():
    """Fill all PDF form fields from text mapping and return downloadable PDF."""
    if not HAS_PYPDF2:
        return jsonify({'error': 'PyPDF2 not available'}), 400

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400

        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400

        mapping_text = request.form.get('mapping_text', '')
        try:
            mappings = _parse_form_mapping_text(mapping_text)
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 400

        pdf_bytes = file.read()
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        form_fields = _collect_editable_pdf_form_fields(reader)
        annotation_fields = _collect_editable_annotation_fields(pdf_bytes)
        all_fields = form_fields + annotation_fields
        if not all_fields:
            return jsonify({'error': 'No fillable form fields or editable annotations were found in this PDF'}), 400

        field_names = [f.get('name') for f in all_fields if f.get('name')]
        for required_name in field_names:
            if required_name not in mappings:
                return jsonify({'error': f'Value is not defined for field "{required_name}"'}), 400

        # Fill AcroForm fields first using PyPDF2.
        writer = PyPDF2.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        form_mappings = {
            f['name']: mappings[f['name']]
            for f in form_fields
            if f.get('name') in mappings
        }

        for page in writer.pages:
            writer.update_page_form_field_values(page, form_mappings)

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        # Then update editable annotation content using PyMuPDF, when available.
        final_bytes = _apply_annotation_updates(output.getvalue(), mappings)
        final_output = io.BytesIO(final_bytes)
        final_output.seek(0)

        original_name = secure_filename(file.filename or 'filled_form.pdf')
        download_name = original_name.replace('.pdf', '_filled.pdf')

        return send_file(
            final_output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=download_name
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/update_metadata', methods=['POST'])
def update_metadata():
    """Update PDF metadata (stores updated metadata for download)."""
    if not HAS_PYPDF2:
        return jsonify({'error': 'PyPDF2 not available'}), 400
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Save the file temporarily
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)
        
        # Read the original PDF
        with open(file_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            pdf_writer = PyPDF2.PdfWriter()
            
            # Copy pages
            for page in pdf_reader.pages:
                pdf_writer.add_page(page)
            
            # Add metadata
            pdf_writer.add_metadata({
                '/Title': request.form.get('title', ''),
                '/Author': request.form.get('author', ''),
                '/Subject': request.form.get('subject', ''),
                '/Creator': request.form.get('creator', ''),
                '/Producer': request.form.get('producer', ''),
            })
            
            # Save to output
            output_filename = f"metadata_{unique_id}_{secure_filename(file.filename)}"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            
            with open(output_path, 'wb') as output_file:
                pdf_writer.write(output_file)
        
        return jsonify({
            'success': True,
            'message': 'Metadata updated successfully',
            'download_url': f'/api/download/{output_filename}'
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download_pdf_with_metadata', methods=['POST'])
def download_pdf_with_metadata():
    """Download PDF with updated metadata."""
    if not HAS_PYPDF2:
        return jsonify({'error': 'PyPDF2 not available'}), 400
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Read the original PDF
        pdf_reader = PyPDF2.PdfReader(file.stream)
        pdf_writer = PyPDF2.PdfWriter()
        
        # Copy pages
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)
        
        # Add/update metadata
        pdf_writer.add_metadata({
            '/Title': request.form.get('title', ''),
            '/Author': request.form.get('author', ''),
            '/Subject': request.form.get('subject', ''),
            '/Creator': request.form.get('creator', ''),
            '/Producer': request.form.get('producer', ''),
        })
        
        # Write to bytes
        output = io.BytesIO()
        pdf_writer.write(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='pdf_with_metadata.pdf'
        )
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/ocr_download_text', methods=['POST'])
def ocr_download_text():
    """Extract text from PDF and return whichever output is better: pypdf or OCR."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'PDF file is required'}), 400
        
        file = request.files['file']
        if not allowed_file(file.filename):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Save uploaded file temporarily
        unique_id = str(uuid.uuid4())
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{secure_filename(file.filename)}")
        file.save(file_path)

        requested_lang = (request.form.get('lang', 'auto') or 'auto').strip()
        if requested_lang.lower() in {'', 'auto', 'detect'}:
            requested_lang = None

        best = extract_best_text_from_pdf(
            file_path,
            lang=requested_lang,
            dpi=int(request.form.get('dpi', '300'))
        )
        final_text = best.get('text', '')
        print(
            f"[INFO] OCR text selection: method={best.get('method')} "
            f"scores={best.get('scores')}"
        )
        
        if not final_text.strip():
            return jsonify({
                'error': 'No text could be extracted from the PDF. Ensure Tesseract OCR is installed and accessible, then retry.',
                'method': best.get('method'),
                'scores': best.get('scores')
            }), 400
        
        # Return as downloadable text file
        output = io.BytesIO()
        output.write(final_text.encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/plain',
            as_attachment=True,
            download_name=file.filename.replace('.pdf', '_ocr.txt')
        )
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/get_db_stats', methods=['GET'])
def get_db_stats():
    """Get database statistics."""
    if not HAS_DB:
        return jsonify({'error': 'Database not available'}), 400
    
    try:
        stats = db_manager.get_database_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 50)
    print("PDF Toolkit - Web Application")
    print("=" * 50)
    print("Starting server...")
    print("Access the application at: http://localhost:5000")
    print("For network access, use: http://<your-ip>:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)