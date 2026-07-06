"""
PDF Toolkit - Web-based PDF Processing Application
A platform-independent GUI that works on Android, iPhone, Windows, and macOS.
"""

import os
import io
import sys
import uuid
import tempfile
import traceback
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
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
    arrange_photos_on_a4_row
)

# Import AI PDF Analyzer
try:
    from ai_pdf_analyzer import AIPDFAnalyzer, AIConfigManager
    HAS_AI_ANALYZER = True
except ImportError as e:
    print(f"[WARNING] AI PDF Analyzer not available: {e}")
    HAS_AI_ANALYZER = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Initialize AI Analyzer
ai_analyzer = None
if HAS_AI_ANALYZER:
    ai_analyzer = AIPDFAnalyzer()

# Track uploaded files for AI analysis
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


@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    """Upload PDF/image for AI analysis."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Accept PDF, images, and text files
        allowed_types = {'pdf', 'jpg', 'jpeg', 'png', 'txt', 'gif', 'bmp', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_types:
            return jsonify({'success': False, 'error': f'File type .{file_ext} not supported'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        # Track file
        ai_uploaded_files[unique_filename] = {
            'original_name': filename,
            'path': file_path,
            'size': os.path.getsize(file_path),
            'type': file.content_type
        }
        
        return jsonify({
            'success': True,
            'filename': unique_filename,
            'original_name': filename
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/analyze_pdf', methods=['POST'])
def analyze_pdf():
    """Analyze PDF and generate summary."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        data = request.get_json()
        filename = data.get('filename')
        provider = data.get('provider', 'gemini')
        
        if not filename or filename not in ai_uploaded_files:
            return jsonify({'success': False, 'error': 'File not found'}), 400
        
        file_path = ai_uploaded_files[filename]['path']
        
        # Analyze PDF
        result = ai_analyzer.analyze_pdf(file_path, provider)
        
        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Analysis failed')
            }), 500
        
        return jsonify({
            'success': True,
            'summary': result['summary'],
            'provider': result['provider'],
            'context': ''  # Store context server-side per filename
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/chat_pdf', methods=['POST'])
def chat_pdf():
    """Chat with AI about PDF content."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        data = request.get_json()
        filename = data.get('filename')
        message = data.get('message')
        provider = data.get('provider', 'gemini')
        
        if not filename or filename not in ai_uploaded_files:
            return jsonify({'success': False, 'error': 'File not found'}), 400
        
        if not message:
            return jsonify({'success': False, 'error': 'No message provided'}), 400
        
        file_path = ai_uploaded_files[filename]['path']
        
        # Extract context from PDF
        from ai_pdf_analyzer import PDFTextExtractor
        context = PDFTextExtractor.extract_text(file_path, max_pages=50)
        
        # Chat with context
        result = ai_analyzer.chat_with_context(message, context, provider)
        
        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Chat failed')
            }), 500
        
        return jsonify({
            'success': True,
            'response': result['response'],
            'provider': result['provider']
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/get_ai_config', methods=['GET'])
def get_ai_config():
    """Get current AI configuration."""
    if not HAS_AI_ANALYZER:
        return jsonify({'error': 'AI analyzer not available'}), 400
    
    try:
        config = ai_analyzer.config_manager.get_config()
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save_ai_config', methods=['POST'])
def save_ai_config():
    """Save AI configuration."""
    if not HAS_AI_ANALYZER:
        return jsonify({'success': False, 'error': 'AI analyzer not available'}), 400
    
    try:
        config = request.get_json()
        success = ai_analyzer.config_manager.save_config(config)
        
        if success:
            # Reinitialize AI providers
            ai_analyzer._init_providers()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration'}), 500
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 50)
    print("PDF Toolkit - Web Application")
    print("=" * 50)
    print("Starting server...")
    print("Access the application at: http://localhost:5000")
    print("For network access, use: http://<your-ip>:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)