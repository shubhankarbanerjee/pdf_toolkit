#!/usr/bin/env python3
"""
PDF Toolkit - Desktop Application
A standalone client-side application that runs entirely on your machine.
No server, no internet required - all processing happens locally.
"""

import os
import sys
import webbrowser
import threading
import socket
import time
import tempfile
import argparse
from pathlib import Path

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

def check_dependencies():
    """Check if all required dependencies are installed."""
    missing = []
    try:
        import flask
    except ImportError:
        missing.append("Flask")
    
    try:
        import fitz
    except ImportError:
        missing.append("PyMuPDF")
    
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        try:
            from PyPDF2 import PdfReader, PdfWriter
        except ImportError:
            missing.append("pypdf or PyPDF2")
    
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        missing.append("Pillow and pytesseract (for OCR)")
    
    return missing

def create_photo_sheet(image_path, copies=6, photo_width_mm=35, photo_height_mm=45, margin_mm=5, gap_mm=5, top_margin_mm=20, dpi=300, output_dir=None):
    """Create a passport-photo sheet PDF from an image file."""
    from pdf_processor import arrange_photos_on_a4_row

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')

    output_filename, output_path = arrange_photos_on_a4_row(
        image_path,
        copies=copies,
        photo_width_mm=photo_width_mm,
        photo_height_mm=photo_height_mm,
        margin_mm=margin_mm,
        gap_mm=gap_mm,
        top_margin_mm=top_margin_mm,
        dpi=dpi,
        output_dir=output_dir
    )
    return output_filename, output_path


def main():
    """Main function to launch the desktop application."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--photo-sheet', dest='photo_sheet')
    parser.add_argument('--copies', type=int, default=6)
    parser.add_argument('--photo-width-mm', type=float, default=35)
    parser.add_argument('--photo-height-mm', type=float, default=45)
    parser.add_argument('--margin-mm', type=float, default=5)
    parser.add_argument('--gap-mm', type=float, default=5)
    parser.add_argument('--top-margin-mm', type=float, default=5)
    parser.add_argument('--dpi', type=int, default=300)
    args, _ = parser.parse_known_args()

    if args.photo_sheet:
        output_filename, output_path = create_photo_sheet(
            args.photo_sheet,
            copies=args.copies,
            photo_width_mm=args.photo_width_mm,
            photo_height_mm=args.photo_height_mm,
            margin_mm=args.margin_mm,
            gap_mm=args.gap_mm,
            top_margin_mm=args.top_margin_mm,
            dpi=args.dpi
        )
        if output_path:
            print(f"Created photo sheet: {output_filename}")
            print(f"Saved to: {output_path}")
        else:
            print("Failed to create photo sheet")
            sys.exit(1)
        return
    print("=" * 60)
    print("  PDF Toolkit - Desktop Application")
    print("=" * 60)
    print()
    print("Starting PDF Toolkit...")
    print()
    
    # Check dependencies
    missing = check_dependencies()
    if missing:
        print("ERROR: Missing dependencies!")
        print(f"Missing: {', '.join(missing)}")
        print()
        print("Please install them using:")
        print("  pip install -r requirements.txt")
        print()
        input("Press Enter to exit...")
        sys.exit(1)
    
    # Configuration
    port = 5000
    host = "127.0.0.1"  # Only localhost for security
    
    # Find available port
    while True:
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.bind((host, port))
            test_socket.close()
            break
        except OSError:
            port += 1
            if port > 5100:
                print("ERROR: Could not find an available port!")
                input("Press Enter to exit...")
                sys.exit(1)
    
    # Set environment variables
    os.environ['PDF_TOOLKIT_PORT'] = str(port)
    os.environ['PDF_TOOLKIT_HOST'] = host
    os.environ['PDF_TOOLKIT_DEBUG'] = 'false'
    
    # Change to app directory
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)
    
    # Create necessary directories
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('outputs', exist_ok=True)
    
    # Import and start Flask in a separate thread
    from app import app
    
    def run_server():
        """Run the Flask server in a background thread."""
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(2)
    
    # Open browser
    url = f"http://localhost:{port}"
    print(f"Opening PDF Toolkit in your browser...")
    print(f"URL: {url}")
    print()
    print("The application is now running locally on your machine.")
    print("All file processing happens on your computer - nothing is uploaded anywhere.")
    print()
    print("To stop the application, close this window.")
    print("=" * 60)
    
    # Open in default browser
    webbrowser.open(url)
    
    # Keep the application running
    try:
        while server_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down PDF Toolkit...")
        sys.exit(0)

if __name__ == '__main__':
    main()