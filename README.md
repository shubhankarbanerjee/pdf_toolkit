# PDF Toolkit - Desktop Application

A **100% client-side** PDF processing application that runs entirely on your machine. No server, no internet connection required, no data leaves your computer. Works on **Windows, Mac, Linux, Android, and iPhone**.

## 🚀 Quick Start

### Windows (Easiest Method)
1. **Download and extract** the pdf_toolkit folder
2. **Double-click** `launch.bat`
3. Your browser will automatically open to the application
4. Start processing PDFs!

### All Platforms (Python Required)
```bash
# 1. Install Python (3.8 or higher)
# 2. Open terminal/command prompt in the pdf_toolkit folder
# 3. Run:
pip install -r requirements.txt
python desktop_app.py
```

### Create Standalone Executable (Windows)
```bash
# Run the build script to create PDF-Toolkit.exe
build_exe.bat
```
After building, you'll find `PDF-Toolkit.exe` in the `dist` folder. You can copy this single file anywhere and run it without installing Python.

## 📋 Features

- 🔗 **Merge PDFs** - Combine two PDF files into one
- ✂️ **Split PDF** - Split large PDFs by file size (e.g., 200MB parts)
- 🔍 **OCR PDF** - Make scanned PDFs searchable (English & Hindi)
- 📑 **Split Odd/Even** - Separate pages for duplex printing
- 🗜️ **Compress PDF** - Reduce file size with OCR (maximum compression)

## 🔒 Privacy & Security

**This application is 100% private:**
- ✅ All processing happens on YOUR computer
- ✅ No files are uploaded to any server
- ✅ No internet connection required
- ✅ No data collection
- ✅ Works offline

The application runs a local web server on `localhost` (your computer only) that you access through your browser. All file processing occurs on your machine.

## 📱 Platform Support

### Desktop (Full Features)
- **Windows** - Run `launch.bat` or `PDF-Toolkit.exe`
- **macOS** - Run `python desktop_app.py`
- **Linux** - Run `python desktop_app.py`

### Mobile (Access via Browser)
- **Android** - Open browser, go to `http://<computer-ip>:5000`
- **iPhone/iPad** - Open Safari, go to `http://<computer-ip>:5000`

*Note: For mobile access, your phone and computer must be on the same WiFi network.*

## 🛠️ Installation

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Install Tesseract OCR (Required for OCR functions)

**Windows:**
- Download from: https://github.com/UB-Mannheim/tesseract/wiki
- Install and add to PATH
- During installation, select Hindi language pack if needed

**macOS:**
```bash
brew install tesseract
# For Hindi: brew install tesseract-lang
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install tesseract-ocr
sudo apt-get install tesseract-ocr-hin  # For Hindi
```

## 📖 Usage Guide

### 1. Merge PDFs
1. Click "Select First PDF" → choose file
2. Click "Select Second PDF" → choose file
3. Click "Merge PDFs"
4. Download the merged PDF

### 2. Split PDF by Size
1. Select the PDF to split
2. Set maximum size per part (default: 200 MB)
3. Click "Split PDF"
4. Download all parts

### 3. OCR PDF (Make Searchable)
1. Select scanned PDF
2. Choose OCR resolution (DPI)
3. Select language (English, Hindi, or both)
4. Choose parallel workers (more = faster but uses more memory)
5. Click "Perform OCR"
6. Download searchable PDF

### 4. Split Odd/Even Pages
1. Select PDF
2. Click "Split Odd/Even Pages"
3. Download two files: `_Odd.pdf` and `_Even.pdf`

### 5. Compress PDF
1. Select PDF to compress
2. Choose output resolution (lower DPI = smaller size)
3. Select OCR language
4. Click "Compress PDF"
5. Download compressed PDF

## 🏗️ Architecture

```
pdf_toolkit/
├── desktop_app.py      # Main application launcher
├── app.py              # Flask web server (runs locally)
├── pdf_processor.py    # PDF processing functions
├── templates/
│   └── index.html      # Web interface
├── requirements.txt    # Python dependencies
├── launch.bat          # Windows launcher
├── build_exe.bat       # Build standalone .exe
├── uploads/            # Temporary upload folder
└── outputs/            # Processed files output
```

## 🔧 Troubleshooting

### "Module not found" errors
```bash
pip install -r requirements.txt
```

### "Tesseract not found" errors
- Install Tesseract OCR and add to system PATH
- Restart terminal/command prompt after installation

### Cannot access from phone
- Ensure phone and computer are on the **same WiFi network**
- Check Windows Firewall isn't blocking port 5000
- Use computer's IP address (shown when app starts)

### Application won't start
- Make sure port 5000 isn't already in use
- Try running as administrator (Windows)
- Check if Python is installed: `python --version`

### OCR not working
- Verify Tesseract installation: `tesseract --version`
- For Hindi, ensure Hindi language pack is installed

## 📦 Building Standalone Executable

### Windows
```bash
build_exe.bat
```
This creates `dist/PDF-Toolkit.exe` that can be distributed without requiring Python installation.

### macOS/Linux
```bash
pyinstaller --onefile --name PDF-Toolkit \
    --add-data "templates:templates" \
    --hidden-import flask \
    --hidden-import fitz \
    desktop_app.py
```

## 🎯 Key Benefits

1. **100% Client-Side** - Everything runs on your machine
2. **Cross-Platform** - Works on Windows, Mac, Linux, Android, iPhone
3. **No Installation** (with .exe) - Single file, no setup required
4. **Privacy First** - No data leaves your computer
5. **Offline Capable** - Works without internet
6. **Free & Open Source** - Modify and distribute as needed

## 📄 License

MIT License - Free to use, modify, and distribute.

## 🙏 Credits

Built with:
- [Flask](https://flask.palletsprojects.com/) - Lightweight web framework
- [PyMuPDF](https://pymupdf.readthedocs.io/) - PDF processing
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - Text recognition
- [pypdf](https://pypdf.readthedocs.io/) - PDF manipulation
- [PyInstaller](https://www.pyinstaller.org/) - Create standalone executables

---

**Note:** This application is designed to run entirely on your local machine. No data is transmitted to external servers. All PDF processing happens on your device, ensuring complete privacy and security.