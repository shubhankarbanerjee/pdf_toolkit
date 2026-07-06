"""
PDF Processor Module
Contains all PDF processing functions for the PDF Toolkit application.
"""

import os
import io
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import fitz  # PyMuPDF
    if not hasattr(fitz, 'open'):
        raise ImportError("Imported fitz module is not PyMuPDF")
except Exception:
    try:
        import pymupdf as fitz
    except Exception:
        print("Error: PyMuPDF is not installed.")
        print("Install it using: pip install PyMuPDF")
        sys.exit(1)

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        print("Error: pypdf or PyPDF2 is required.")
        print("Install it using: pip install pypdf")
        sys.exit(1)

try:
    from PIL import Image, ImageOps
    import pytesseract
except ImportError:
    print("Error: PIL and pytesseract are required for OCR functions.")
    print("Install them using: pip install pillow pytesseract")
    print("Also install Tesseract OCR from: https://github.com/UB-Mannheim/tesseract/wiki")
    # We'll handle this gracefully - OCR functions will fail if not available
    Image = None
    pytesseract = None


def merge_pdfs(pdf_path1, pdf_path2):
    """
    Merge two PDF files into one.
    
    Args:
        pdf_path1: Path to the first PDF file
        pdf_path2: Path to the second PDF file
    
    Returns:
        tuple: (output_filename, output_path) or (None, None) on failure
    """
    try:
        # Validate files exist
        if not os.path.exists(pdf_path1) or not os.path.exists(pdf_path2):
            return None, None
        
        # Extract file names
        file_name1 = Path(pdf_path1).name
        file_name2 = Path(pdf_path2).name
        
        # Get directory of first PDF
        output_dir = os.path.dirname(os.path.abspath(pdf_path1))
        if not os.path.exists('outputs'):
            os.makedirs('outputs')
        output_dir = 'outputs'
        
        # Extract first 6 characters of file_name1 (without extension)
        name1_base = Path(file_name1).stem
        first_6_chars = name1_base[:6] if len(name1_base) >= 6 else name1_base
        
        # Extract last 6 characters of file_name2 (without extension)
        name2_base = Path(file_name2).stem
        last_6_chars = name2_base[-6:] if len(name2_base) >= 6 else name2_base
        
        # Create output filename
        output_filename = f"{first_6_chars}_{last_6_chars}.pdf"
        output_path = os.path.join(output_dir, output_filename)
        
        # Create PDF merger object
        merger = PdfMerger() if 'PdfMerger' in globals() else fitz.open()
        
        if isinstance(merger, fitz.Document):
            # Use PyMuPDF
            doc1 = fitz.open(pdf_path1)
            doc2 = fitz.open(pdf_path2)
            merger.insert_pdf(doc1)
            merger.insert_pdf(doc2)
            merger.save(output_path, garbage=4, deflate=True)
            merger.close()
            doc1.close()
            doc2.close()
        else:
            # Use PyPDF2/pypdf
            merger.append(pdf_path1)
            merger.append(pdf_path2)
            merger.write(output_path)
            merger.close()
        
        return output_filename, output_path
        
    except Exception as e:
        print(f"Error during PDF merge: {e}")
        return None, None


def split_pdf_by_size(input_pdf_path, max_size_mb=200):
    """
    Split a PDF file into multiple PDFs based on maximum file size.
    
    Args:
        input_pdf_path (str): Path to the input PDF file
        max_size_mb (int): Maximum size of each split part in MB (default: 200)
    
    Returns:
        list: List of output file paths created
    """
    max_size_bytes = (max_size_mb - 1) * 1024 * 1024  # 199 MB in bytes
    
    if not os.path.exists(input_pdf_path):
        return []
    
    input_size = os.path.getsize(input_pdf_path)
    
    # If input is smaller than max size, no splitting needed
    if input_size <= max_size_bytes:
        # Just copy to outputs
        output_path = os.path.join('outputs', os.path.basename(input_pdf_path))
        import shutil
        shutil.copy2(input_pdf_path, output_path)
        return [output_path]
    
    # Read the PDF
    reader = PdfReader(input_pdf_path)
    total_pages = len(reader.pages)
    
    input_path = Path(input_pdf_path)
    stem = input_path.stem
    
    if not os.path.exists('outputs'):
        os.makedirs('outputs')
    
    output_files = []
    current_part = 1
    current_page_start = 0
    
    while current_page_start < total_pages:
        writer = PdfWriter()
        current_size = 0
        pages_in_part = 0
        current_page_end = current_page_start
        
        # Add pages until we reach the size limit
        for page_idx in range(current_page_start, total_pages):
            # Estimate page size
            writer_test = PdfWriter()
            writer_test.add_page(reader.pages[page_idx])
            buffer = io.BytesIO()
            writer_test.write(buffer)
            page_size = buffer.tell()
            buffer.close()
            
            if current_size + page_size > max_size_bytes and pages_in_part > 0:
                break
            
            writer.add_page(reader.pages[page_idx])
            current_size += page_size
            pages_in_part += 1
            current_page_end = page_idx + 1
        
        if pages_in_part == 0 and current_page_start < total_pages:
            writer.add_page(reader.pages[current_page_start])
            pages_in_part = 1
            current_page_end = current_page_start + 1
        
        output_filename = f"{stem}_part{current_part}.pdf"
        output_path = os.path.join('outputs', output_filename)
        
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        
        output_files.append(output_path)
        current_page_start = current_page_end
        current_part += 1
    
    return output_files


def ocr_page(page_num, page, dpi=150, lang='eng+hin'):
    """
    Perform OCR on a single PDF page.
    
    Args:
        page_num: Page number (0-indexed)
        page: PyMuPDF page object
        dpi: Resolution for rendering page to image
        lang: Tesseract language code
        
    Returns:
        tuple: (page_num, text_blocks, image_bytes, success, error_msg)
    """
    if Image is None or pytesseract is None:
        return (page_num, [], None, False, "OCR libraries not installed")
    
    try:
        # Render page to image
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        # Get OCR data with bounding boxes
        ocr_data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
        
        # Get page dimensions for coordinate scaling
        page_rect = page.rect
        scale_x = page_rect.width / img.width
        scale_y = page_rect.height / img.height
        
        # Extract text blocks with positions
        text_blocks = []
        
        for i in range(len(ocr_data['text'])):
            if ocr_data['text'][i].strip():
                x = ocr_data['left'][i] * scale_x
                y = ocr_data['top'][i] * scale_y
                w = ocr_data['width'][i] * scale_x
                h = ocr_data['height'][i] * scale_y
                conf = ocr_data['conf'][i]
                
                if conf > 30:
                    text_blocks.append({
                        'text': ocr_data['text'][i],
                        'bbox': (x, y, x + w, y + h),
                        'confidence': conf
                    })
        
        # Get optimized image
        output_pix = page.get_pixmap()
        image_bytes = output_pix.tobytes("png")
        
        return (page_num, text_blocks, image_bytes, True, None)
        
    except Exception as e:
        return (page_num, [], None, False, str(e))


def ocr_pdf_to_pdf(input_path, dpi=150, lang='eng+hin', max_workers=4):
    """
    Create an OCR-processed PDF with searchable text layer.
    
    Args:
        input_path: Path to input PDF
        dpi: Resolution for OCR processing
        lang: Tesseract language code
        max_workers: Number of parallel workers
        
    Returns:
        tuple: (output_filename, output_path) or (None, None) on failure
    """
    if not os.path.exists(input_path):
        return None, None
    
    if not os.path.exists('outputs'):
        os.makedirs('outputs')
    
    try:
        doc = fitz.open(input_path)
        total_pages = len(doc)
        
        input_path_obj = Path(input_path)
        output_filename = f"OCR_{input_path_obj.stem}.pdf"
        output_path = os.path.join('outputs', output_filename)
        
        new_doc = fitz.open()
        
        use_parallel = max_workers > 1 and total_pages > 1
        
        if use_parallel:
            results_dict = {}
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {
                    executor.submit(ocr_page, page_num, doc[page_num], dpi, lang): page_num
                    for page_num in range(total_pages)
                }
                
                for future in as_completed(future_to_page):
                    result_page_num, text_blocks, image_bytes, success, error = future.result()
                    results_dict[result_page_num] = (text_blocks, image_bytes, success, error)
            
            for page_num in range(total_pages):
                text_blocks, image_bytes, success, error = results_dict[page_num]
                _process_page_result(new_doc, doc, page_num, text_blocks, image_bytes, success, error)
        else:
            for page_num in range(total_pages):
                page = doc[page_num]
                _, text_blocks, image_bytes, success, error = ocr_page(page_num, page, dpi, lang)
                _process_page_result(new_doc, doc, page_num, text_blocks, image_bytes, success, error)
        
        new_doc.save(output_path, garbage=4, deflate=True)
        new_doc.close()
        doc.close()
        
        return output_filename, output_path
        
    except Exception as e:
        print(f"Error during OCR processing: {e}")
        return None, None


def _process_page_result(new_doc, doc, page_num, text_blocks, image_bytes, success, error):
    """
    Process OCR result for a single page and add to new document.
    """
    try:
        if success and image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            img_width, img_height = img.size
            
            new_page = new_doc.new_page(width=img_width, height=img_height)
            
            new_page.insert_image(
                fitz.Rect(0, 0, img_width, img_height),
                stream=image_bytes
            )
            
            if text_blocks:
                fontname = "helv"
                for block in text_blocks:
                    x, y, x2, y2 = block['bbox']
                    font_size = max(6, min((y2 - y) * 0.8, 12))
                    
                    new_page.insert_text(
                        (x, y + font_size),
                        block['text'],
                        fontname=fontname,
                        fontsize=font_size,
                        color=(0, 0, 0, 0)
                    )
        else:
            src_page = doc[page_num]
            new_page = new_doc.new_page(
                width=src_page.rect.width,
                height=src_page.rect.height
            )
            new_page.show_pdf_page(0, 0, src_page)
            
    except Exception as e:
        print(f"Error processing page result: {e}")
        try:
            src_page = doc[page_num]
            new_page = new_doc.new_page(
                width=src_page.rect.width,
                height=src_page.rect.height
            )
            new_page.show_pdf_page(0, 0, src_page)
        except Exception as e2:
            print(f"Fallback also failed: {e2}")


def split_odd_even_pdfs(input_pdf_path):
    """
    Split a PDF into odd and even pages.
    
    Args:
        input_pdf_path: Path to input PDF
        
    Returns:
        tuple: (odd_path, even_path)
    """
    if not os.path.exists(input_pdf_path):
        return None, None
    
    try:
        doc = fitz.open(input_pdf_path)
        total_pages = len(doc)
        
        if total_pages == 0:
            doc.close()
            return None, None
        
        input_path = Path(input_pdf_path)
        stem = input_path.stem
        
        if not os.path.exists('outputs'):
            os.makedirs('outputs')
        
        odd_pages = []
        even_pages = []
        
        for i in range(total_pages):
            if i % 2 == 0:
                odd_pages.append(i)
            else:
                even_pages.append(i)
        
        odd_path = None
        even_path = None
        
        if odd_pages:
            odd_doc = fitz.open()
            for page_num in odd_pages:
                odd_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            
            odd_filename = f"{stem}_Odd.pdf"
            odd_path = os.path.join('outputs', odd_filename)
            odd_doc.save(odd_path, garbage=4, deflate=True, clean=True)
            odd_doc.close()
        
        if even_pages:
            even_doc = fitz.open()
            for page_num in even_pages:
                even_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            
            even_filename = f"{stem}_Even.pdf"
            even_path = os.path.join('outputs', even_filename)
            even_doc.save(even_path, garbage=4, deflate=True, clean=True)
            even_doc.close()
        
        doc.close()
        return odd_path, even_path
        
    except Exception as e:
        print(f"Error during odd/even split: {e}")
        return None, None


def compress_pdf(input_path, dpi=100, lang='eng+hin'):
    """
    Compress a PDF file by re-rendering pages at lower DPI and adding OCR text layer.
    This significantly reduces file size while maintaining readability.
    
    Args:
        input_path: Path to input PDF
        dpi: Resolution for rendering (lower = smaller file size)
        lang: Tesseract language code for OCR
        
    Returns:
        tuple: (output_filename, output_path) or (None, None) on failure
    """
    if not os.path.exists(input_path):
        return None, None
    
    if not os.path.exists('outputs'):
        os.makedirs('outputs')
    
    try:
        doc = fitz.open(input_path)
        total_pages = len(doc)
        
        input_path_obj = Path(input_path)
        output_filename = f"Compressed_{input_path_obj.stem}.pdf"
        output_path = os.path.join('outputs', output_filename)
        
        new_doc = fitz.open()
        
        for page_num in range(total_pages):
            page = doc[page_num]
            
            # Render page at lower DPI for compression
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            
            # Use pil_tobytes for JPEG compression (works with newer PyMuPDF)
            img_data = pix.pil_tobytes("jpeg", quality=85, optimize=True)
            img = Image.open(io.BytesIO(img_data))
            img_width, img_height = img.size
            
            # Create new page
            new_page = new_doc.new_page(width=img_width, height=img_height)
            
            # Insert compressed image
            new_page.insert_image(
                fitz.Rect(0, 0, img_width, img_height),
                stream=img_data
            )
            
            # Add OCR text layer if available
            if Image is not None and pytesseract is not None:
                try:
                    ocr_data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                    
                    page_rect = page.rect
                    scale_x = img_width / img.width
                    scale_y = img_height / img.height
                    
                    for i in range(len(ocr_data['text'])):
                        if ocr_data['text'][i].strip() and ocr_data['conf'][i] > 30:
                            x = ocr_data['left'][i] * scale_x
                            y = ocr_data['top'][i] * scale_y
                            w = ocr_data['width'][i] * scale_x
                            h = ocr_data['height'][i] * scale_y
                            
                            font_size = max(6, min(h * 0.8, 12))
                            
                            new_page.insert_text(
                                (x, y + font_size),
                                ocr_data['text'][i],
                                fontname="helv",
                                fontsize=font_size,
                                color=(0, 0, 0, 0)
                            )
                except Exception:
                    pass  # Skip OCR if it fails
        
        # Save with maximum compression
        new_doc.save(output_path, garbage=4, deflate=True, clean=True)
        new_doc.close()
        doc.close()
        
        return output_filename, output_path
        
    except Exception as e:
        print(f"Error during PDF compression: {e}")
        return None, None


def pdf_page_count(input_pdf_path):
    """Return the page count for a PDF file."""
    if not os.path.exists(input_pdf_path):
        return 0

    try:
        doc = fitz.open(input_pdf_path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def pdf_to_images(input_pdf_path, output_format='png', from_page=1, to_page=None, dpi=300, output_dir='outputs'):
    """
    Convert selected PDF pages to A4-sized image files.

    Args:
        input_pdf_path (str): Path to the PDF file.
        output_format (str): Desired image format ('png', 'jpg', 'jpeg', 'gif').
        from_page (int): First page number to convert (1-indexed).
        to_page (int or None): Last page number to convert (1-indexed).
        dpi (int): Target resolution in DPI.
        output_dir (str): Directory to save output images.

    Returns:
        list: List of saved image file paths.
    """
    if not os.path.exists(input_pdf_path):
        return []

    if output_format.lower() not in {'png', 'jpg', 'jpeg', 'gif'}:
        output_format = 'png'

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        doc = fitz.open(input_pdf_path)
        total_pages = len(doc)
        if total_pages == 0:
            doc.close()
            return []

        if from_page < 1:
            from_page = 1
        if to_page is None or to_page > total_pages:
            to_page = total_pages
        if to_page < from_page:
            to_page = from_page

        output_files = []
        pdf_stem = Path(input_pdf_path).stem.replace(' ', '_')
        a4_w_px = int(round(210.0 / 25.4 * dpi))
        a4_h_px = int(round(297.0 / 25.4 * dpi))

        for page_number in range(from_page, to_page + 1):
            page = doc.load_page(page_number - 1)
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            img = Image.open(io.BytesIO(pix.tobytes('png')))
            img = ImageOps.exif_transpose(img)
            img = img.convert('RGB')

            img = ImageOps.contain(img, (a4_w_px, a4_h_px), method=Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS)

            # Place the rendered page onto an A4 white background to preserve exact A4 size
            background = Image.new('RGB', (a4_w_px, a4_h_px), 'white')
            x = (a4_w_px - img.width) // 2
            y = (a4_h_px - img.height) // 2
            background.paste(img, (x, y))

            ext = output_format.lower()
            if ext == 'jpeg':
                ext = 'jpg'
            output_filename = f"{pdf_stem}_{page_number}.{ext}"
            output_path = os.path.join(output_dir, output_filename)

            save_kwargs = {}
            if ext in {'jpg', 'jpeg'}:
                save_kwargs['quality'] = 95
                save_kwargs['subsampling'] = 0
            if ext == 'gif':
                background = background.convert('P', palette=Image.ADAPTIVE)

            background.save(output_path, format=ext.upper(), **save_kwargs)
            output_files.append(output_path)

        doc.close()
        return output_files
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []


# Import PdfMerger if available
try:
    from PyPDF2 import PdfMerger
except ImportError:
    try:
        from pypdf import PdfMerger
    except ImportError:
        PdfMerger = None


def arrange_photos_on_a4_row(input_image_path, copies=6, photo_width_mm=35, photo_height_mm=45,
                             margin_mm=5, gap_mm=5, top_margin_mm=5, dpi=300, output_dir='outputs'):
    """
    Arrange multiple passport-size photos on the first row of an A4 PDF page.

    Args:
        input_image_path (str): Path to the source image file.
        copies (int): Number of copies to place side-by-side (default 6).
        photo_width_mm (float): Desired photo width in millimetres (default 35mm).
        photo_height_mm (float): Desired photo height in millimetres (default 45mm).
        margin_mm (float): Horizontal margin around the row in mm (default 5mm).
        gap_mm (float): Space between adjacent photos in mm (default 5mm).
        top_margin_mm (float): Top margin from top edge of A4 page in mm (default 5mm).
        dpi (int): Target DPI for output images (default 300).
        output_dir (str): Directory to write output PDF into (default 'outputs').

    Returns:
        tuple: (output_filename, output_path) or (None, None) on failure
    """
    if not os.path.exists(input_image_path):
        return None, None

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        # A4 size in mm
        A4_W_MM = 210.0
        A4_H_MM = 297.0

        def mm_to_points(mm):
            return mm * 72.0 / 25.4

        def mm_to_pixels(mm, dpi):
            return int(round((mm / 25.4) * dpi))

        slot_total_width_mm = copies * photo_width_mm + max(0, copies - 1) * gap_mm + 2 * margin_mm

        scale = 1.0
        if slot_total_width_mm > A4_W_MM:
            scale = A4_W_MM / slot_total_width_mm

        photo_w_mm_scaled = photo_width_mm * scale
        photo_h_mm_scaled = photo_height_mm * scale
        margin_mm_scaled = margin_mm * scale
        gap_mm_scaled = gap_mm * scale

        px_w = mm_to_pixels(photo_w_mm_scaled, dpi)
        px_h = mm_to_pixels(photo_h_mm_scaled, dpi)

        src_img = Image.open(input_image_path)
        src_img = ImageOps.exif_transpose(src_img)
        src_img = src_img.convert('RGB')

        target_ratio = px_w / max(1, px_h)
        if src_img.width > src_img.height and target_ratio < 1.0:
            src_img = src_img.rotate(270, expand=True)

        resized = ImageOps.contain(
            src_img,
            (px_w, px_h),
            method=Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
        )

        page_w_pt = mm_to_points(A4_W_MM)
        page_h_pt = mm_to_points(A4_H_MM)

        out_doc = fitz.open()
        page = out_doc.new_page(width=page_w_pt, height=page_h_pt)

        total_used_width_mm = copies * photo_w_mm_scaled + max(0, copies - 1) * gap_mm_scaled + 2 * margin_mm_scaled
        start_x_mm = max(margin_mm_scaled, (A4_W_MM - total_used_width_mm) / 2.0)
        y_mm = top_margin_mm

        img_buffer = io.BytesIO()
        resized.save(img_buffer, format='PNG')
        img_bytes = img_buffer.getvalue()

        for i in range(copies):
            x_mm = start_x_mm + i * (photo_w_mm_scaled + gap_mm_scaled)
            x0 = mm_to_points(x_mm)
            y0 = mm_to_points(y_mm)
            x1 = x0 + mm_to_points(photo_w_mm_scaled)
            y1 = y0 + mm_to_points(photo_h_mm_scaled)

            rect = fitz.Rect(x0, y0, x1, y1)
            page.insert_image(rect, stream=img_bytes)

        output_filename = f"PhotosRow_{Path(input_image_path).stem}_{copies}.pdf"
        output_path = os.path.join(output_dir, output_filename)
        out_doc.save(output_path, garbage=4, deflate=True, clean=True)
        out_doc.close()
        return output_filename, output_path

    except Exception as e:
        print(f"Error creating photos row PDF: {e}")
        return None, None