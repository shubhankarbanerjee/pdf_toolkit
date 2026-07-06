#!/usr/bin/env python3
"""
PDF Toolkit - Startup Script
Launches the PDF Toolkit web application and opens the browser.
"""

import os
import sys
import webbrowser
import socket
import time
import threading

def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser(url, delay=2):
    """Open the browser after a delay to allow the server to start."""
    time.sleep(delay)
    webbrowser.open(url)

def main():
    """Main function to start the PDF Toolkit application."""
    print("=" * 60)
    print("  PDF Toolkit - All-in-One PDF Processor")
    print("=" * 60)
    print()
    
    # Check if dependencies are installed
    try:
        import flask
        import fitz
        from pypdf import PdfReader, PdfWriter
    except ImportError as e:
        print("Error: Missing dependencies!")
        print(f"Missing: {e.name}")
        print()
        print("Please install the required packages:")
        print("  pip install -r requirements.txt")
        print()
        input("Press Enter to exit...")
        sys.exit(1)
    
    # Get configuration
    port = int(os.environ.get('PDF_TOOLKIT_PORT', '5000'))
    host = os.environ.get('PDF_TOOLKIT_HOST', '0.0.0.0')
    debug = os.environ.get('PDF_TOOLKIT_DEBUG', 'false').lower() == 'true'
    
    # Get local network info
    local_ip = get_local_ip()
    
    print("Configuration:")
    print(f"  Port: {port}")
    print(f"  Host: {host}")
    print(f"  Debug: {debug}")
    print()
    print("Access URLs:")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{local_ip}:{port}")
    print()
    print("Platform Support:")
    print("  ✓ Windows  - Access via browser")
    print("  ✓ macOS    - Access via browser")
    print("  ✓ Linux    - Access via browser")
    print("  ✓ Android  - Access via browser (same WiFi network)")
    print("  ✓ iPhone   - Access via browser (same WiFi network)")
    print()
    print("Features:")
    print("  🔗 Merge PDFs      - Combine two PDF files")
    print("  ✂️  Split PDF        - Split by file size")
    print("  🔍 OCR PDF          - Make scanned PDFs searchable")
    print("  📑 Split Odd/Even   - For duplex printing")
    print("  🗜️  Compress PDF     - Reduce file size with OCR")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    print()
    
    # Open browser in a separate thread
    browser_thread = threading.Thread(target=open_browser, args=(f"http://localhost:{port}",))
    browser_thread.daemon = True
    browser_thread.start()
    
    # Import and run the Flask app
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # Change to the pdf_toolkit directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    from app import app
    app.run(host=host, port=port, debug=debug, threaded=True)

if __name__ == '__main__':
    main()