"""
PDF Diff Module
===============
Compare two PDF files for text and image differences.

Priority 1 – Text & spelling differences (word-level diff)
Priority 2 – Image content differences (ignores compression/quality/size)

A PDF compared to its compressed version will show zero differences because
perceptual hashing is used for images (not pixel-exact comparison).
"""

import io
import difflib
import hashlib
from collections import Counter

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False


# ─────────────────────────────────────────────────────────────
# Perceptual hashing (quality-insensitive image comparison)
# ─────────────────────────────────────────────────────────────

def _phash(img, size=16):
    """
    Average-hash: resize to size×size grayscale, threshold at mean pixel value.
    Identical images compressed differently will produce the same hash.
    """
    img = img.convert('L').resize((size, size), Image.LANCZOS)
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    return ''.join('1' if p > avg else '0' for p in pixels)


def _hamming(h1, h2):
    """Bit-level Hamming distance between two hash strings."""
    return sum(c1 != c2 for c1, c2 in zip(h1, h2))


# ─────────────────────────────────────────────────────────────
# Main Differ class
# ─────────────────────────────────────────────────────────────

class PDFDiffer:
    """Compare two PDF files for text/spelling and image differences."""

    # Image similarity threshold: how many bits of the 16×16 hash (=256 bits)
    # may differ before we call images "different".
    # 20/256 ≈ 92% similarity required.  Raise to allow more tolerance.
    IMAGE_THRESHOLD = 20
    MAX_DIFF_PAGES = 5

    # ── Text extraction ──────────────────────────────────────

    @staticmethod
    def _extract_text_pages(pdf_path):
        """Return a list of strings, one per page."""
        if HAS_FITZ:
            try:
                doc = fitz.open(pdf_path)
                pages = [page.get_text() for page in doc]
                doc.close()
                return pages
            except Exception as e:
                print(f"[WARNING] PyMuPDF text extraction failed: {e}")

        if HAS_PYPDF2:
            try:
                with open(pdf_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    return [p.extract_text() or '' for p in reader.pages]
            except Exception as e:
                print(f"[WARNING] PyPDF2 text extraction failed: {e}")

        return []

    # ── Image extraction ─────────────────────────────────────

    @staticmethod
    def _extract_images_pages(pdf_path):
        """Return a list-of-lists: [[PIL.Image, ...], ...] one sub-list per page."""
        if not HAS_FITZ or not HAS_PIL:
            return []
        try:
            doc = fitz.open(pdf_path)
            result = []
            for page in doc:
                page_imgs = []
                for img_info in page.get_images(full=True):
                    try:
                        base = doc.extract_image(img_info[0])
                        img = Image.open(io.BytesIO(base['image']))
                        # Normalise mode so hash is consistent across colour spaces
                        img = img.convert('RGB')
                        page_imgs.append(img)
                    except Exception:
                        pass
                result.append(page_imgs)
            doc.close()
            return result
        except Exception as e:
            print(f"[WARNING] Image extraction failed: {e}")
            return []

    @staticmethod
    def _extract_images_for_page(doc, page_index):
        """Return PIL images for one page from an opened PyMuPDF document."""
        if not HAS_FITZ or not HAS_PIL or doc is None or page_index < 0 or page_index >= len(doc):
            return []

        page = doc.load_page(page_index)
        page_imgs = []
        for img_info in page.get_images(full=True):
            try:
                base = doc.extract_image(img_info[0])
                img = Image.open(io.BytesIO(base['image'])).convert('RGB')
                page_imgs.append(img)
            except Exception:
                pass
        return page_imgs

    @staticmethod
    def _safe_page_count(pdf_path):
        """Get page count without fully extracting all pages."""
        if HAS_FITZ:
            try:
                doc = fitz.open(pdf_path)
                count = len(doc)
                doc.close()
                return count
            except Exception:
                pass

        if HAS_PYPDF2:
            try:
                with open(pdf_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    return len(reader.pages)
            except Exception:
                pass

        return 0

    @staticmethod
    def _normalize_text(text):
        """Normalize text for stable page-signature comparison."""
        return ' '.join((text or '').split()).strip().lower()

    @classmethod
    def _page_signature(cls, text, images):
        """Build a page signature from normalized text and perceptual image hashes."""
        norm_text = cls._normalize_text(text)
        text_hash = hashlib.sha256(norm_text.encode('utf-8')).hexdigest()

        img_hashes = []
        if HAS_PIL:
            for img in images or []:
                try:
                    img_hashes.append(_phash(img))
                except Exception:
                    continue
        img_hashes.sort()

        return f"{text_hash}|{'|'.join(img_hashes)}"

    @classmethod
    def _build_page_signatures(cls, pdf_path):
        """Build page signatures for repetition/new-content analysis."""
        signatures = []

        if HAS_FITZ:
            try:
                doc = fitz.open(pdf_path)
                for i in range(len(doc)):
                    page = doc.load_page(i)
                    text = page.get_text() or ''
                    images = cls._extract_images_for_page(doc, i)
                    signatures.append(cls._page_signature(text, images))
                doc.close()
                return signatures
            except Exception as e:
                print(f"[WARNING] Signature extraction via PyMuPDF failed: {e}")

        # Fallback: text-only signatures
        text_pages = cls._extract_text_pages(pdf_path)
        for text in text_pages:
            signatures.append(cls._page_signature(text or '', []))
        return signatures

    # ── Word-level text diff ──────────────────────────────────

    @staticmethod
    def _word_diff(text1, text2):
        """
        Word-level diff of two text strings.
        Captures spelling differences and word changes naturally.

        Returns (has_diff, change_count, chunks)
        where chunks is a list of:
          {'type': 'equal'|'delete'|'insert', 'text': str, 'word_count': int}
        """
        words1 = text1.split()
        words2 = text2.split()

        sm = difflib.SequenceMatcher(None, words1, words2, autojunk=False)
        chunks = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                t = ' '.join(words1[i1:i2])
                chunks.append({'type': 'equal', 'text': t, 'word_count': i2 - i1})
            elif tag == 'replace':
                # Show as delete + insert (spelling/word change)
                chunks.append({'type': 'delete', 'text': ' '.join(words1[i1:i2]), 'word_count': i2 - i1})
                chunks.append({'type': 'insert', 'text': ' '.join(words2[j1:j2]), 'word_count': j2 - j1})
            elif tag == 'delete':
                chunks.append({'type': 'delete', 'text': ' '.join(words1[i1:i2]), 'word_count': i2 - i1})
            elif tag == 'insert':
                chunks.append({'type': 'insert', 'text': ' '.join(words2[j1:j2]), 'word_count': j2 - j1})

        has_diff = any(c['type'] != 'equal' for c in chunks)
        change_count = sum(1 for c in chunks if c['type'] in ('delete', 'insert'))
        return has_diff, change_count, chunks

    # ── Image comparison (perceptual, quality-insensitive) ───

    @classmethod
    def _compare_images(cls, imgs1, imgs2):
        """
        Compare two lists of PIL images using perceptual hashing.
        A compressed/resized version of the same image will match.

        Returns list of:
          {'index': int, 'status': 'same'|'different'|'added'|'removed', 'similarity': float}
        """
        results = []
        n = max(len(imgs1), len(imgs2), 0)

        for i in range(n):
            if i >= len(imgs1):
                results.append({'index': i + 1, 'status': 'added', 'similarity': 0})
            elif i >= len(imgs2):
                results.append({'index': i + 1, 'status': 'removed', 'similarity': 0})
            elif HAS_PIL:
                try:
                    dist = _hamming(_phash(imgs1[i]), _phash(imgs2[i]))
                    similarity = round(max(0.0, (1 - dist / 256)) * 100, 1)
                    status = 'same' if dist <= cls.IMAGE_THRESHOLD else 'different'
                    results.append({'index': i + 1, 'status': status, 'similarity': similarity})
                except Exception:
                    results.append({'index': i + 1, 'status': 'unknown', 'similarity': None})
            else:
                results.append({'index': i + 1, 'status': 'unknown', 'similarity': None})

        return results

    # ── Main entry point ─────────────────────────────────────

    @classmethod
    def diff(cls, pdf1_path, pdf2_path):
        """
        Full diff of two PDF files.

        Returns a dict:
        {
          'success': True,
          'identical': bool,
          'summary': { pages_pdf1, pages_pdf2, text_changes, image_changes, diff_pages },
          'pages': [ {page, in_pdf1, in_pdf2, has_text_diff, text_changes,
                      chunks, has_image_diff, images_pdf1, images_pdf2, image_diffs}, ... ]
        }
        """
        pages_pdf1 = cls._safe_page_count(pdf1_path)
        pages_pdf2 = cls._safe_page_count(pdf2_path)
        page_count_different = pages_pdf1 != pages_pdf2

        # Analyze repeated pages / new content when page counts differ.
        repetition_in_modified = 0
        new_unique_pages_in_modified = 0
        first_new_page_in_modified = None
        if page_count_different:
            try:
                sigs1 = cls._build_page_signatures(pdf1_path)
                sigs2 = cls._build_page_signatures(pdf2_path)
                count1 = Counter(sigs1)
                count2 = Counter(sigs2)

                repetition_in_modified = sum(
                    max(0, count2[sig] - count1.get(sig, 0))
                    for sig in count2
                    if sig in count1
                )
                new_unique_pages_in_modified = sum(1 for sig in count2 if sig not in count1)

                sigs1_set = set(sigs1)
                for idx, sig in enumerate(sigs2, 1):
                    if sig not in sigs1_set:
                        first_new_page_in_modified = idx
                        break
            except Exception as e:
                print(f"[WARNING] Repetition/new-content analysis failed: {e}")

        n = max(pages_pdf1, pages_pdf2, 1)
        page_results = []
        total_text_changes = 0
        total_image_changes = 0
        diff_pages = []
        stopped_early = False

        doc1 = None
        doc2 = None

        try:
            if HAS_FITZ:
                try:
                    doc1 = fitz.open(pdf1_path)
                except Exception as e:
                    print(f"[WARNING] Unable to open PDF 1 with PyMuPDF: {e}")
                    doc1 = None
                try:
                    doc2 = fitz.open(pdf2_path)
                except Exception as e:
                    print(f"[WARNING] Unable to open PDF 2 with PyMuPDF: {e}")
                    doc2 = None

            # Fallback readers if fitz is unavailable
            pages1_fallback = None
            pages2_fallback = None
            imgs1_fallback = None
            imgs2_fallback = None
            if doc1 is None or doc2 is None:
                pages1_fallback = cls._extract_text_pages(pdf1_path)
                pages2_fallback = cls._extract_text_pages(pdf2_path)
                imgs1_fallback = cls._extract_images_pages(pdf1_path)
                imgs2_fallback = cls._extract_images_pages(pdf2_path)

            for i in range(n):
                if doc1 is not None:
                    t1 = doc1.load_page(i).get_text() if i < len(doc1) else ''
                    p1_imgs = cls._extract_images_for_page(doc1, i) if i < len(doc1) else []
                else:
                    t1 = pages1_fallback[i] if pages1_fallback is not None and i < len(pages1_fallback) else ''
                    p1_imgs = imgs1_fallback[i] if imgs1_fallback is not None and i < len(imgs1_fallback) else []

                if doc2 is not None:
                    t2 = doc2.load_page(i).get_text() if i < len(doc2) else ''
                    p2_imgs = cls._extract_images_for_page(doc2, i) if i < len(doc2) else []
                else:
                    t2 = pages2_fallback[i] if pages2_fallback is not None and i < len(pages2_fallback) else ''
                    p2_imgs = imgs2_fallback[i] if imgs2_fallback is not None and i < len(imgs2_fallback) else []

                has_td, tc, chunks = cls._word_diff(t1, t2)
                img_diffs = cls._compare_images(p1_imgs, p2_imgs)
                has_id = any(d['status'] in ('different', 'added', 'removed') for d in img_diffs)

                total_text_changes += tc
                total_image_changes += sum(1 for d in img_diffs if d['status'] in ('different', 'added', 'removed'))

                page_num = i + 1
                if has_td or has_id:
                    diff_pages.append(page_num)

                page_results.append({
                    'page': page_num,
                    'in_pdf1': i < pages_pdf1,
                    'in_pdf2': i < pages_pdf2,
                    'has_text_diff': has_td,
                    'text_changes': tc,
                    'chunks': chunks,
                    'has_image_diff': has_id,
                    'images_pdf1': len(p1_imgs),
                    'images_pdf2': len(p2_imgs),
                    'image_diffs': img_diffs,
                })

                if len(diff_pages) >= cls.MAX_DIFF_PAGES:
                    stopped_early = True
                    break
        finally:
            try:
                if doc1 is not None:
                    doc1.close()
            except Exception:
                pass
            try:
                if doc2 is not None:
                    doc2.close()
            except Exception:
                pass

        if page_count_different and first_new_page_in_modified is not None:
            page_count_note = (
                f"Page counts differ ({pages_pdf1} vs {pages_pdf2}). "
                f"First page in modified with data not present in original: page {first_new_page_in_modified}. "
                f"Detected repeated-page occurrences in modified: {repetition_in_modified}."
            )
        elif page_count_different:
            page_count_note = (
                f"Page counts differ ({pages_pdf1} vs {pages_pdf2}). "
                f"No uniquely new page content detected in modified; extra pages appear to be repetitions. "
                f"Detected repeated-page occurrences in modified: {repetition_in_modified}."
            )
        else:
            page_count_note = f"Page counts match ({pages_pdf1})."

        identical = (
            (not page_count_different)
            and (total_text_changes == 0)
            and (total_image_changes == 0)
            and (not stopped_early)
        )

        return {
            'success': True,
            'identical': identical,
            'summary': {
                'pages_pdf1': pages_pdf1,
                'pages_pdf2': pages_pdf2,
                'text_changes': total_text_changes,
                'image_changes': total_image_changes,
                'diff_pages': diff_pages,
                'page_count_different': page_count_different,
                'repetition_in_modified': repetition_in_modified,
                'new_unique_pages_in_modified': new_unique_pages_in_modified,
                'first_new_page_in_modified': first_new_page_in_modified,
                'page_count_note': page_count_note,
                'compared_diff_pages_limit': cls.MAX_DIFF_PAGES,
                'stopped_early': stopped_early,
                'scanned_pages': len(page_results),
                'comparison_mode': 'text_and_image',
                'image_resolution_agnostic': True,
            },
            'pages': page_results,
        }
