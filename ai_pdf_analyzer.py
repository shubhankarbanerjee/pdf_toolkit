#!/usr/bin/env python3
"""
AI PDF Analyzer Module
======================

Provides AI-powered PDF analysis with multiple LLM providers.
Supports: OpenAI, Google Gemini, Claude, Groq, GitHub Models, Local Ollama
Features: Session management, PDF caching, unlimited file sizes
"""

import json
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# Try to import optional AI dependencies
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import langdetect
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False


class AIConfigManager:
    """Manage AI provider configurations and API keys."""
    
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "ai_pdf_config.json"
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load AI configuration from file."""
        defaults = self._default_config()
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    loaded = json.load(f)
                for provider, provider_defaults in defaults.items():
                    if isinstance(loaded.get(provider), dict):
                        provider_defaults.update(loaded[provider])
                return defaults
            except Exception as e:
                print(f"[WARNING] Could not load AI config: {e}")
        
        return defaults
    
    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """Return default configuration structure."""
        return {
            'openai': {
                'api_key': '',
                'enabled': False,
                'model': 'gpt-4-turbo'
            },
            'gemini': {
                'api_key': '',
                'enabled': False,
                'model': 'gemini-pro'
            },
            'claude': {
                'api_key': '',
                'enabled': False,
                'model': 'claude-3-5-sonnet-latest'
            },
            'groq': {
                'api_key': '',
                'enabled': False,
                'model': 'llama-3.3-70b-versatile'
            },
            'github': {
                'api_key': '',
                'enabled': False,
                'model': 'gpt-4o-mini',
                'base_url': 'https://models.inference.ai.azure.com'
            },
            'ollama': {
                'host': 'http://localhost:11434',
                'enabled': False,
                'model': 'llama2'
            }
        }
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            self.config = config
            return True
        except Exception as e:
            print(f"[ERROR] Could not save AI config: {e}")
            return False
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self.config
    
    def update_provider(self, provider: str, settings: Dict[str, Any]) -> bool:
        """Update settings for a specific provider."""
        if provider not in self.config:
            return False
        
        self.config[provider].update(settings)
        return self.save_config(self.config)


class PDFTextExtractor:
    """Extract text from PDF files with caching and OCR fallback support."""
    
    @staticmethod
    def extract_text(pdf_path: str, max_pages: int = None, db_manager=None, file_id: str = None, use_ocr: bool = False) -> str:
        """
        Extract text from PDF file with optional caching and OCR fallback.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum pages to extract (None = all)
            db_manager: Database manager for caching
            file_id: File ID for cache lookup
            use_ocr: Force OCR for scanned PDFs
        
        Returns:
            Extracted text (up to 500K characters to stay within token limits)
        """
        # Check cache first
        if db_manager and file_id:
            cached = db_manager.get_cached_text(file_id)
            if cached:
                return cached
        
        # Try regular text extraction first
        text = PDFTextExtractor._extract_text_direct(pdf_path, max_pages)
        
        # If extraction yielded very little text (scanned PDF), try OCR
        if len(text.strip()) < 200 and use_ocr:
            print(f"[INFO] PDF appears to be scanned (extracted {len(text)} chars), attempting OCR...")
            text = PDFTextExtractor._extract_text_ocr(pdf_path, max_pages)
        
        # Cache the text
        if db_manager and file_id and text:
            page_count = PDFTextExtractor._get_page_count(pdf_path)
            db_manager.cache_pdf_text(file_id, text, page_count)
        
        return text
    
    @staticmethod
    def _extract_text_direct(pdf_path: str, max_pages: int = None) -> str:
        """Extract text directly from PDF using PyMuPDF or PyPDF2 (no character limit)."""
        text = ""
        page_count = 0
        
        # Try PyMuPDF first (faster)
        if HAS_FITZ:
            try:
                doc = fitz.open(pdf_path)
                page_count = len(doc)
                
                # Determine pages to extract
                pages_to_extract = page_count
                if max_pages:
                    pages_to_extract = min(pages_to_extract, max_pages)
                
                for page_num in range(pages_to_extract):
                    try:
                        page = doc[page_num]
                        text += f"\n--- Page {page_num + 1} ---\n"
                        text += page.get_text()
                    except Exception as e:
                        text += f"\n[Error reading page {page_num + 1}: {str(e)}]\n"
                
                doc.close()
                print(f"[OK] Extracted {len(text)} characters from PDF (PyMuPDF)")
                return text
            except Exception as e:
                print(f"[WARNING] PyMuPDF extraction failed: {e}")
        
        # Fallback to PyPDF2
        if HAS_PYPDF2:
            try:
                with open(pdf_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    page_count = len(reader.pages)
                    
                    # Determine pages to extract
                    pages_to_extract = page_count
                    if max_pages:
                        pages_to_extract = min(pages_to_extract, max_pages)
                    
                    for page_num in range(pages_to_extract):
                        try:
                            page = reader.pages[page_num]
                            text += f"\n--- Page {page_num + 1} ---\n"
                            text += page.extract_text()
                        except Exception as e:
                            text += f"\n[Error reading page {page_num + 1}: {str(e)}]\n"
                
                print(f"[OK] Extracted {len(text)} characters from PDF (PyPDF2)")
                return text
            except Exception as e:
                print(f"[WARNING] PyPDF2 extraction failed: {e}")
        
        return ""
    
    @staticmethod
    def _extract_text_ocr(pdf_path: str, max_pages: int = None, languages: str = None) -> str:
        """Extract text from scanned PDF using OCR (Tesseract) with multi-language support.
        
        Args:
            pdf_path: Path to PDF
            max_pages: Max pages to process
            languages: Comma-separated language codes (e.g., 'eng,hin,mar' for English, Hindi, Marathi)
        """
        if not HAS_PIL or not HAS_TESSERACT:
            print(f"[WARNING] OCR not available: PIL={HAS_PIL}, Tesseract={HAS_TESSERACT}")
            return ""
        
        if not languages:
            languages = "eng"  # Default to English
        
        text = ""
        page_count = 0
        
        try:
            import pdf2image
            pages = pdf2image.convert_from_path(pdf_path)
            page_count = len(pages)
            
            # Determine pages to extract
            pages_to_extract = page_count
            if max_pages:
                pages_to_extract = min(pages_to_extract, max_pages)
            
            for page_num in range(pages_to_extract):
                try:
                    page_image = pages[page_num]
                    text += f"\n--- Page {page_num + 1} (OCR) ---\n"
                    text += pytesseract.image_to_string(page_image, lang=languages)
                except Exception as e:
                    text += f"\n[Error OCR reading page {page_num + 1}: {str(e)}]\n"
            
            print(f"[OK] OCR extracted {len(text)} characters from PDF ({page_count} pages) with languages: {languages}")
            return text
        except Exception as e:
            print(f"[WARNING] OCR extraction failed: {e}")
            return ""
    
    @staticmethod
    def detect_language(text: str) -> str:
        """Detect primary language in text and return Tesseract language codes.
        
        Supports: English, Hindi, Nepali, Marathi, Tamil, Malayalam, Sanskrit, Bengali, Chinese, Korean, Japanese
        """
        if not HAS_LANGDETECT:
            return "eng"  # Default to English
        
        try:
            # Language code mapping: ISO639-1 -> Tesseract codes
            language_map = {
                'en': 'eng',
                'hi': 'hin',
                'ne': 'nep',
                'mr': 'mar',
                'ta': 'tam',
                'ml': 'mal',
                'sa': 'san',
                'bn': 'ben',
                'zh-cn': 'chi_sim',
                'zh-tw': 'chi_tra',
                'zh': 'chi_sim',
                'ko': 'kor',
                'ja': 'jpn',
            }
            
            # Get primary language from first 1000 chars
            detected = langdetect.detect(text[:1000])
            tesseract_lang = language_map.get(detected, 'eng')
            print(f"[INFO] Detected language: {detected} -> Tesseract: {tesseract_lang}")
            return tesseract_lang
        except Exception as e:
            print(f"[WARNING] Language detection failed: {e}")
            return "eng"
    
    @staticmethod
    def _get_page_count(pdf_path: str) -> int:
        """Get number of pages in PDF."""
        try:
            if HAS_FITZ:
                doc = fitz.open(pdf_path)
                count = len(doc)
                doc.close()
                return count
        except Exception:
            pass
        
        try:
            if HAS_PYPDF2:
                with open(pdf_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    return len(reader.pages)
        except Exception:
            pass
        
        return 0
    
    @staticmethod
    def get_file_hash(file_path: str) -> str:
        """Calculate SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


class AIPDFAnalyzer:
    """Main AI PDF analyzer with multi-provider support."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_manager = AIConfigManager(config_path)
        self.config = self.config_manager.get_config()
        self._init_providers()
    
    def _init_providers(self):
        """Initialize AI providers based on configuration."""
        self._claude_api_key = (self.config.get('claude', {}).get('api_key') or os.environ.get('CLAUDE_API_KEY', '')).strip()
        self._groq_api_key = (self.config.get('groq', {}).get('api_key') or os.environ.get('GROQ_API_KEY', '')).strip()
        self._github_api_key = (self.config.get('github', {}).get('api_key') or os.environ.get('GITHUB_MODELS_API_KEY', '')).strip()

        self.gemini_initialized = False
        self.openai_initialized = False
        self.claude_initialized = False
        self.groq_initialized = False
        self.github_initialized = False
        self.ollama_available = False
        
        # Initialize Gemini
        if HAS_GEMINI and self.config['gemini']['enabled'] and self.config['gemini']['api_key']:
            try:
                genai.configure(api_key=self.config['gemini']['api_key'])
                self.gemini_initialized = True
                print("[OK] Gemini initialized")
            except Exception as e:
                print(f"[WARNING] Gemini init failed: {e}")
        
        # Initialize OpenAI
        if HAS_OPENAI and self.config['openai']['enabled'] and self.config['openai']['api_key']:
            try:
                openai.api_key = self.config['openai']['api_key']
                self.openai_initialized = True
                print("[OK] OpenAI initialized")
            except Exception as e:
                print(f"[WARNING] OpenAI init failed: {e}")

        claude_enabled = bool(self.config.get('claude', {}).get('enabled')) or bool(self._claude_api_key)
        if HAS_REQUESTS and claude_enabled and self._claude_api_key:
            self.claude_initialized = True
            print("[OK] Claude configuration loaded")

        groq_enabled = bool(self.config.get('groq', {}).get('enabled')) or bool(self._groq_api_key)
        if HAS_REQUESTS and groq_enabled and self._groq_api_key:
            self.groq_initialized = True
            print("[OK] Groq configuration loaded")

        github_enabled = bool(self.config.get('github', {}).get('enabled')) or bool(self._github_api_key)
        if HAS_REQUESTS and github_enabled and self._github_api_key:
            self.github_initialized = True
            print("[OK] GitHub Models configuration loaded")
        
        # Check Ollama
        self.ollama_available = False
        self.ollama_model = None
        if HAS_REQUESTS and self.config['ollama']['enabled']:
            self.ollama_available = self._check_ollama_connection()
            if self.ollama_available:
                # First check if user has set a preference
                user_model = self.config['ollama'].get('model', '').strip()
                if user_model and user_model != '':
                    self.ollama_model = user_model
                    print(f"[OK] Using user-selected model: {self.ollama_model}")
                else:
                    # Auto-select best model
                    self.ollama_model = self._get_best_ollama_model()
    
    def _check_ollama_connection(self) -> bool:
        """Test Ollama connection. Returns True if reachable."""
        if not HAS_REQUESTS or not self.config['ollama']['enabled']:
            return False
        host = self.config['ollama']['host'].rstrip('/')
        try:
            resp = requests.get(f"{host}/api/tags", timeout=5)
            if resp.status_code == 200:
                print(f"[OK] Ollama connected at {host}")
                return True
            else:
                print(f"[WARNING] Ollama responded with HTTP {resp.status_code} at {host}")
                return False
        except requests.exceptions.ConnectionError:
            print(f"[WARNING] Ollama not reachable at {host} - connection refused")
        except requests.exceptions.Timeout:
            print(f"[WARNING] Ollama timed out at {host} - check host/port")
        except Exception as e:
            print(f"[WARNING] Ollama check failed: {e}")
        return False
    
    def _get_best_ollama_model(self) -> Optional[str]:
        """Fetch available Ollama models and select the best one for PDF analysis."""
        if not HAS_REQUESTS or not self.config['ollama']['enabled']:
            return None
        
        host = self.config['ollama']['host'].rstrip('/')
        
        try:
            # Try native Ollama endpoint first
            resp = requests.get(f"{host}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get('models', [])
                if models:
                    best_model = self._score_models(models, is_ollama=True)
                    if best_model:
                        print(f"[OK] Selected Ollama model: {best_model}")
                        return best_model
        except Exception:
            pass
        
        try:
            # Fallback to OpenAI-compatible endpoint (Msty)
            resp = requests.get(f"{host}/v1/models", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get('data', [])
                if models:
                    best_model = self._score_models(models, is_ollama=False)
                    if best_model:
                        print(f"[OK] Selected Msty model: {best_model}")
                        return best_model
        except Exception:
            pass
        
        print("[WARNING] No Ollama models found - check remote instance")
        return None
    
    def _score_models(self, models: List[Dict[str, Any]], is_ollama: bool = True) -> Optional[str]:
        """Score and select the best model for PDF analysis considering system RAM.
        
        Scoring priorities:
        1. Model fits in available RAM (hard constraint)
        2. Vision models (for PDFs with images)
        3. Good quality models (llama3, mistral, etc)
        4. Avoid oversized models on low-RAM systems
        """
        # Get available system memory
        available_gb = self._get_available_ram_gb()
        print(f"[DEBUG] Available system RAM: {available_gb:.1f} GB")
        
        scored = []
        
        for model in models:
            name = model.get('name' if is_ollama else 'id', '')
            if not name:
                continue
            
            score = 0
            name_lower = name.lower()
            
            # Estimate RAM requirement based on model name
            estimated_ram = self._estimate_model_ram(name_lower)
            
            # Hard constraint: skip if model clearly too large for available RAM
            if estimated_ram > available_gb * 0.9:  # Leave 10% buffer
                print(f"[DEBUG] Skipping {name}: needs ~{estimated_ram}GB, only {available_gb:.1f}GB available")
                continue
            
            # Vision models: highest priority for PDF analysis
            if 'vision' in name_lower:
                score += 100
            
            # Specific good models
            if any(x in name_lower for x in ['llama3', 'mistral', 'neural-chat', 'yi', 'qwen']):
                score += 50
            
            # Favor smaller models on memory-constrained systems
            if available_gb < 8:  # Low RAM system
                if '1b' in name_lower:
                    score += 40  # Prefer tiny models
                elif '3b' in name_lower or '4b' in name_lower:
                    score += 30
                elif '7b' in name_lower:
                    score += 20
                elif '13b' in name_lower:
                    score += 10
                else:
                    score -= 50  # Penalize unknown large models
            else:  # Plenty of RAM
                # Prefer larger models (better quality)
                if '70b' in name_lower or '65b' in name_lower:
                    score += 40
                elif '13b' in name_lower:
                    score += 20
                elif '7b' in name_lower:
                    score += 10
            
            scored.append((name, score, estimated_ram))
        
        if scored:
            # Sort by score (descending) and return best
            scored.sort(key=lambda x: x[1], reverse=True)
            best_name, best_score, best_ram = scored[0]
            print(f"[OK] Model scores: {[(n, s) for n, s, _ in scored[:3]]}")
            print(f"[OK] Selected {best_name} (est. {best_ram}GB RAM)")
            return best_name
        
        return None
    
    def _get_available_ram_gb(self) -> float:
        """Get available system RAM in GB."""
        try:
            if HAS_PSUTIL:
                return psutil.virtual_memory().available / (1024**3)
        except Exception:
            pass
        # Fallback estimate
        return 4.0
    
    def _estimate_model_ram(self, model_name: str) -> float:
        """Estimate RAM requirement (GB) for a model based on its name."""
        # Common model size to RAM mappings
        if any(x in model_name for x in ['0.5b']):
            return 1.0
        elif any(x in model_name for x in ['1b']):
            return 2.0
        elif any(x in model_name for x in ['3b', '4b']):
            return 3.5
        elif any(x in model_name for x in ['7b']):
            return 6.0
        elif any(x in model_name for x in ['13b']):
            return 10.0
        elif any(x in model_name for x in ['70b', '65b']):
            return 40.0
        else:
            # Unknown model - assume medium sized
            return 8.0

    def get_available_providers(self) -> List[str]:
        """Get list of enabled and available providers."""
        providers = []
        
        if self.gemini_initialized:
            providers.append('gemini')
        if self.openai_initialized:
            providers.append('openai')
        if self.claude_initialized:
            providers.append('claude')
        if self.groq_initialized:
            providers.append('groq')
        if self.github_initialized:
            providers.append('github')
        if self.ollama_available:
            providers.append('ollama')
        
        return providers
    
    def get_available_ollama_models(self) -> List[Dict[str, Any]]:
        """Fetch and return list of available Ollama models with metadata."""
        models = []
        available_ram = self._get_available_ram_gb()
        
        if not self.ollama_available or not HAS_REQUESTS:
            return models
        
        host = self.config['ollama']['host'].rstrip('/')
        
        try:
            # Try native Ollama endpoint
            resp = requests.get(f"{host}/api/tags", timeout=5)
            if resp.status_code == 200:
                raw_models = resp.json().get('models', [])
                for m in raw_models:
                    name = m.get('name', '')
                    if name:
                        estimated_ram = self._estimate_model_ram(name.lower())
                        models.append({
                            'name': name,
                            'estimated_ram_gb': estimated_ram,
                            'fits_in_memory': estimated_ram <= available_ram * 0.9
                        })
                return models
        except Exception:
            pass
        
        try:
            # Fallback to OpenAI-compatible endpoint
            resp = requests.get(f"{host}/v1/models", timeout=5)
            if resp.status_code == 200:
                raw_models = resp.json().get('data', [])
                for m in raw_models:
                    name = m.get('id', '')
                    if name:
                        estimated_ram = self._estimate_model_ram(name.lower())
                        models.append({
                            'name': name,
                            'estimated_ram_gb': estimated_ram,
                            'fits_in_memory': estimated_ram <= available_ram * 0.9
                        })
                return models
        except Exception:
            pass
        
        return models
    
    def set_ollama_model(self, model_name: str) -> bool:
        """Save user's model preference to config."""
        try:
            self.config['ollama']['model'] = model_name
            self.config_manager.save_config(self.config)
            self.ollama_model = model_name
            print(f"[OK] Saved model preference: {model_name}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save model preference: {e}")
            return False
    
    def analyze_pdf(self, pdf_path: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze PDF and generate summary.
        
        Args:
            pdf_path: Path to PDF file
            provider: AI provider to use (gemini, openai, claude, groq, github, or ollama)
        
        Returns:
            Analysis result with summary
        """
        # Extract text from PDF
        text = PDFTextExtractor.extract_text(pdf_path, max_pages=50)
        
        if not text.strip():
            return {
                'success': False,
                'error': 'Could not extract text from PDF'
            }
        
        # Choose provider
        if provider is None:
            available = self.get_available_providers()
            if not available:
                return {
                    'success': False,
                    'error': 'No AI providers configured'
                }
            provider = available[0]
        
        # Generate analysis with full document text (no character limit)
        prompt = f"""
Analyze the following document and provide a comprehensive summary:

{text}

Provide:
1. **Main Topic**: What is this document about?
2. **Key Points**: 3-5 most important points
3. **Summary**: 2-3 paragraph executive summary
4. **Purpose**: What is the intended use of this document?
5. **Recommendations**: Any notable takeaways or actions

Keep the summary concise and well-structured.
"""
        
        try:
            if provider == 'gemini' and self.gemini_initialized:
                return self._analyze_with_gemini(prompt, text)
            elif provider == 'openai' and self.openai_initialized:
                return self._analyze_with_openai(prompt, text)
            elif provider == 'claude' and self.claude_initialized:
                return self._analyze_with_claude(prompt, text)
            elif provider == 'groq' and self.groq_initialized:
                return self._analyze_with_groq(prompt, text)
            elif provider == 'github' and self.github_initialized:
                return self._analyze_with_github(prompt, text)
            elif provider == 'ollama' and self.ollama_available:
                return self._analyze_with_ollama(prompt, text)
            else:
                return {
                    'success': False,
                    'error': f'Provider {provider} not available'
                }
        except Exception as e:
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }
    
    def _analyze_with_gemini(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using Gemini."""
        try:
            model = genai.GenerativeModel(self.config['gemini']['model'])
            response = model.generate_content(prompt)
            
            return {
                'success': True,
                'provider': 'gemini',
                'summary': response.text,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Gemini analysis failed: {str(e)}'
            }
    
    def _analyze_with_openai(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using OpenAI."""
        try:
            response = openai.ChatCompletion.create(
                model=self.config['openai']['model'],
                messages=[
                    {"role": "system", "content": "You are a document analysis expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1500
            )
            
            return {
                'success': True,
                'provider': 'openai',
                'summary': response.choices[0].message.content,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'OpenAI analysis failed: {str(e)}'
            }

    def _call_openai_compatible_service(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        prompt: str,
        base_url: str,
        system_prompt: str = "You are a document analysis expert.",
        max_tokens: int = 1500,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Call an OpenAI-compatible chat completions endpoint."""
        try:
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            if extra_headers:
                headers.update(extra_headers)

            response = requests.post(
                url,
                headers=headers,
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': prompt},
                    ],
                    'temperature': 0.7,
                    'max_tokens': max_tokens,
                },
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            summary = payload.get('choices', [{}])[0].get('message', {}).get('content', '')
            if not summary:
                raise ValueError(f'{provider_name} returned an empty response')
            return {
                'success': True,
                'provider': provider_name,
                'summary': summary,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'{provider_name.title()} analysis failed: {str(e)}'
            }

    def _analyze_with_claude(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using Claude via the Anthropic Messages API."""
        try:
            response = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': self._claude_api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': self.config['claude']['model'],
                    'max_tokens': 1500,
                    'temperature': 0.7,
                    'system': 'You are a document analysis expert.',
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            parts = payload.get('content', [])
            summary = ''.join(part.get('text', '') for part in parts if isinstance(part, dict))
            if not summary:
                raise ValueError('Claude returned an empty response')
            return {
                'success': True,
                'provider': 'claude',
                'summary': summary,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Claude analysis failed: {str(e)}'
            }

    def _analyze_with_groq(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using Groq's OpenAI-compatible API."""
        return self._call_openai_compatible_service(
            provider_name='groq',
            api_key=self._groq_api_key,
            model=self.config['groq']['model'],
            prompt=prompt,
            base_url='https://api.groq.com/openai/v1',
        )

    def _analyze_with_github(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using GitHub Models with a personal access token."""
        return self._call_openai_compatible_service(
            provider_name='github',
            api_key=self._github_api_key,
            model=self.config['github']['model'],
            prompt=prompt,
            base_url=self.config['github'].get('base_url', 'https://models.inference.ai.azure.com'),
        )
    
    def _analyze_with_ollama(self, prompt: str, context: str) -> Dict[str, Any]:
        """Analyze using local Ollama or Msty (OpenAI-compatible mode)."""
        if not self.ollama_model:
            return {
                'success': False,
                'error': 'No Ollama models available - pull a model first'
            }
        
        host = self.config['ollama']['host'].rstrip('/')
        model = self.ollama_model
        
        print(f"[DEBUG] Starting PDF analysis with model: {model} at {host}")
        
        try:
            # Try native Ollama endpoint first
            try:
                url = f"{host}/api/generate"
                print(f"[DEBUG] Trying native Ollama endpoint: POST {url}")
                response = requests.post(
                    url,
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "temperature": 0.7
                    },
                    timeout=120
                )
                
                print(f"[DEBUG] Response status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"[OK] Ollama analysis succeeded")
                    return {
                        'success': True,
                        'provider': 'ollama',
                        'model': model,
                        'summary': result.get('response', ''),
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    # Any error (404, 405, 500, etc) - try Msty fallback
                    error_body = response.text[:200] if response.text else ""
                    print(f"[DEBUG] Native endpoint error HTTP {response.status_code}{f' - {error_body}' if error_body else ''}, trying Msty fallback...")
                    pass
            except requests.exceptions.ConnectionError as e:
                print(f"[WARNING] Connection error on native endpoint: {e}")
                print(f"[DEBUG] Trying Msty fallback...")
            except requests.exceptions.Timeout as e:
                print(f"[WARNING] Timeout on native endpoint: {e}")
                print(f"[DEBUG] Trying Msty fallback...")
            except Exception as e:
                print(f"[WARNING] Exception on native endpoint: {e}")
                print(f"[DEBUG] Trying Msty fallback...")
            
            # Fallback to Msty's OpenAI-compatible endpoint
            url_fallback = f"{host}/v1/chat/completions"
            print(f"[DEBUG] Trying Msty endpoint: POST {url_fallback}")
            response = requests.post(
                url_fallback,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a document analysis expert."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1500
                },
                timeout=120
            )
            
            print(f"[DEBUG] Msty response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                message_content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                print(f"[OK] Msty analysis succeeded")
                return {
                    'success': True,
                    'provider': 'ollama (Msty)',
                    'model': model,
                    'summary': message_content,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                error_body = response.text[:500] if response.text else "No response body"
                print(f"[ERROR] Msty endpoint returned HTTP {response.status_code}: {error_body}")
                return {
                    'success': False,
                    'error': f'Msty error: HTTP {response.status_code} - {error_body[:100]}'
                }
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] Unexpected exception in Ollama analysis: {error_msg}")
            return {
                'success': False,
                'error': f'Ollama analysis failed: {error_msg}'
            }
    
    def chat_with_context(self, message: str, context_text: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Chat with AI about PDF content.
        
        Args:
            message: User message
            context_text: PDF text context
            provider: AI provider to use
        
        Returns:
            Chat response
        """
        if provider is None:
            available = self.get_available_providers()
            if not available:
                return {
                    'success': False,
                    'error': 'No AI providers configured'
                }
            provider = available[0]
        
        # Use full document text for better analysis (no character limit)
        # For large documents, provide complete text to maintain context
        doc_context = context_text
        
        prompt = f"""
You are a helpful assistant analyzing a document. Answer the user's question based on the document content provided.

**Document Content:**
{doc_context}

**User Question:**
{message}

Provide a clear, concise answer based on the document. If the answer is not in the document, say so.
"""
        
        try:
            if provider == 'gemini' and self.gemini_initialized:
                model = genai.GenerativeModel(self.config['gemini']['model'])
                response = model.generate_content(prompt)
                return {
                    'success': True,
                    'response': response.text,
                    'provider': provider
                }
            elif provider == 'openai' and self.openai_initialized:
                response = openai.ChatCompletion.create(
                    model=self.config['openai']['model'],
                    messages=[
                        {"role": "system", "content": "You are a document assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=1000
                )
                return {
                    'success': True,
                    'response': response.choices[0].message.content,
                    'provider': provider
                }
            elif provider == 'claude' and self.claude_initialized:
                result = self._analyze_with_claude(prompt, context_text)
                if result.get('success'):
                    return {
                        'success': True,
                        'response': result.get('summary', ''),
                        'provider': provider
                    }
                return result
            elif provider == 'groq' and self.groq_initialized:
                result = self._analyze_with_groq(prompt, context_text)
                if result.get('success'):
                    return {
                        'success': True,
                        'response': result.get('summary', ''),
                        'provider': provider
                    }
                return result
            elif provider == 'github' and self.github_initialized:
                result = self._analyze_with_github(prompt, context_text)
                if result.get('success'):
                    return {
                        'success': True,
                        'response': result.get('summary', ''),
                        'provider': provider
                    }
                return result
            elif provider == 'ollama':
                # Use the auto-selected model with endpoint fallback
                if not self.ollama_model:
                    return {
                        'success': False,
                        'error': 'No Ollama models available - pull a model first'
                    }
                
                host = self.config['ollama']['host'].rstrip('/')
                model = self.ollama_model
                
                print(f"[DEBUG] Chat: Starting Ollama analysis with model: {model} at {host}")
                
                try:
                    # Try native Ollama endpoint first
                    try:
                        url = f"{host}/api/generate"
                        print(f"[DEBUG] Chat: Trying native Ollama endpoint: POST {url}")
                        response = requests.post(
                            url,
                            json={
                                "model": model,
                                "prompt": prompt,
                                "stream": False
                            },
                            timeout=120
                        )
                        
                        print(f"[DEBUG] Chat: Response status: {response.status_code}")
                        
                        if response.status_code == 200:
                            result = response.json()
                            print(f"[OK] Chat: Ollama analysis succeeded")
                            return {
                                'success': True,
                                'response': result.get('response', ''),
                                'provider': provider
                            }
                        else:
                            # Any error (404, 405, 500, etc) - try Msty fallback
                            error_body = response.text[:200] if response.text else ""
                            print(f"[DEBUG] Chat: Native endpoint error HTTP {response.status_code}{f' - {error_body}' if error_body else ''}, trying Msty fallback...")
                            pass
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                        print(f"[DEBUG] Chat: Native endpoint connection error: {e}, trying Msty fallback...")
                    
                    # Fallback to Msty's OpenAI-compatible endpoint
                    url_fallback = f"{host}/v1/chat/completions"
                    print(f"[DEBUG] Chat: Trying Msty endpoint: POST {url_fallback}")
                    response = requests.post(
                        url_fallback,
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": "You are a document assistant."},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.7,
                            "max_tokens": 1000
                        },
                        timeout=120
                    )
                    
                    print(f"[DEBUG] Chat: Msty response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        message_content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                        print(f"[OK] Chat: Msty analysis succeeded")
                        return {
                            'success': True,
                            'response': message_content,
                            'provider': f"{provider} (Msty)"
                        }
                    else:
                        error_body = response.text[:500] if response.text else "No response body"
                        print(f"[ERROR] Chat: Msty endpoint returned HTTP {response.status_code}")
                        return {
                            'success': False,
                            'error': f'Ollama request failed: HTTP {response.status_code}'
                        }
                except Exception as e:
                    error_msg = str(e)
                    print(f"[ERROR] Chat: Unexpected exception in Ollama: {error_msg}")
                    return {
                        'success': False,
                        'error': f'Ollama analysis failed: {error_msg}'
                    }
            else:
                return {
                    'success': False,
                    'error': f'Provider {provider} not available'
                }
        except Exception as e:
            return {
                'success': False,
                'error': f'Chat failed: {str(e)}'
            }
