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
        pages1 = cls._extract_text_pages(pdf1_path)
        pages2 = cls._extract_text_pages(pdf2_path)
        imgs1 = cls._extract_images_pages(pdf1_path)
        imgs2 = cls._extract_images_pages(pdf2_path)

        n = max(len(pages1), len(pages2), 1)
        page_results = []
        total_text_changes = 0
        total_image_changes = 0
        diff_pages = []

        for i in range(n):
            t1 = pages1[i] if i < len(pages1) else ''
            t2 = pages2[i] if i < len(pages2) else ''
            p1_imgs = imgs1[i] if i < len(imgs1) else []
            p2_imgs = imgs2[i] if i < len(imgs2) else []

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
                'in_pdf1': i < len(pages1),
                'in_pdf2': i < len(pages2),
                'has_text_diff': has_td,
                'text_changes': tc,
                'chunks': chunks,
                'has_image_diff': has_id,
                'images_pdf1': len(p1_imgs),
                'images_pdf2': len(p2_imgs),
                'image_diffs': img_diffs,
            })

        return {
            'success': True,
            'identical': total_text_changes == 0 and total_image_changes == 0,
            'summary': {
                'pages_pdf1': len(pages1),
                'pages_pdf2': len(pages2),
                'text_changes': total_text_changes,
                'image_changes': total_image_changes,
                'diff_pages': diff_pages,
            },
            'pages': page_results,
        }
