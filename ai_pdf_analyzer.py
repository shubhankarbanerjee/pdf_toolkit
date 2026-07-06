#!/usr/bin/env python3
"""
AI PDF Analyzer Module
======================

Provides AI-powered PDF analysis with multiple LLM providers.
Supports: OpenAI, Google Gemini, Local Ollama
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


class AIConfigManager:
    """Manage AI provider configurations and API keys."""
    
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "ai_pdf_config.json"
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load AI configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARNING] Could not load AI config: {e}")
        
        return self._default_config()
    
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
    """Extract text from PDF files with caching support."""
    
    @staticmethod
    def extract_text(pdf_path: str, max_pages: int = None, db_manager=None, file_id: str = None) -> str:
        """
        Extract text from PDF file with optional caching.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum pages to extract (None = all)
            db_manager: Database manager for caching
            file_id: File ID for cache lookup
        
        Returns:
            Extracted text (up to 500K characters to stay within token limits)
        """
        # Check cache first
        if db_manager and file_id:
            cached = db_manager.get_cached_text(file_id)
            if cached:
                return cached
        
        text = ""
        page_count = 0
        max_chars = 500000  # ~125K tokens at 4 chars/token
        
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
                    # Check character limit
                    if len(text) >= max_chars:
                        text += f"\n\n[... PDF truncated at {max_chars} characters - extracted {page_num} of {page_count} pages ...]"
                        break
                    
                    try:
                        page = doc[page_num]
                        text += f"\n--- Page {page_num + 1} ---\n"
                        text += page.get_text()
                    except Exception as e:
                        text += f"\n[Error reading page {page_num + 1}: {str(e)}]\n"
                
                doc.close()
                
                # Cache the text
                if db_manager and file_id:
                    db_manager.cache_pdf_text(file_id, text, page_count)
                
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
                        # Check character limit
                        if len(text) >= max_chars:
                            text += f"\n\n[... PDF truncated at {max_chars} characters - extracted {page_num} of {page_count} pages ...]"
                            break
                        
                        try:
                            page = reader.pages[page_num]
                            text += f"\n--- Page {page_num + 1} ---\n"
                            text += page.extract_text()
                        except Exception as e:
                            text += f"\n[Error reading page {page_num + 1}: {str(e)}]\n"
                
                # Cache the text
                if db_manager and file_id:
                    db_manager.cache_pdf_text(file_id, text, page_count)
                
                return text
            except Exception as e:
                print(f"[WARNING] PyPDF2 extraction failed: {e}")
        
        return ""
    
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
        self.gemini_initialized = False
        self.openai_initialized = False
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
        
        # Check Ollama
        self.ollama_available = False
        self.ollama_model = None
        if HAS_REQUESTS and self.config['ollama']['enabled']:
            self.ollama_available = self._check_ollama_connection()
            if self.ollama_available:
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
        """Score and select the best model for PDF analysis.
        
        Scoring priorities:
        1. Vision models (for PDFs with images)
        2. Larger models (better quality)
        3. Specific good models (llama, mistral, neural-chat)
        """
        scored = []
        
        for model in models:
            name = model.get('name' if is_ollama else 'id', '')
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
            # Sort by score (descending) and return best
            scored.sort(key=lambda x: x[1], reverse=True)
            best_name, best_score = scored[0]
            print(f"[OK] Model scores: {[(n, s) for n, s in scored[:3]]}")
            return best_name
        
        return None

    def get_available_providers(self) -> List[str]:
        """Get list of enabled and available providers."""
        providers = []
        
        if self.gemini_initialized:
            providers.append('gemini')
        if self.openai_initialized:
            providers.append('openai')
        if self.ollama_available:
            providers.append('ollama')
        
        return providers
    
    def analyze_pdf(self, pdf_path: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze PDF and generate summary.
        
        Args:
            pdf_path: Path to PDF file
            provider: AI provider to use (gemini, openai, or ollama)
        
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
        
        # Generate analysis
        prompt = f"""
Analyze the following document and provide a comprehensive summary:

{text[:4000]}  # Limit to first 4000 chars for token limit

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
                elif response.status_code in [404, 405]:
                    # Endpoint not found or method not allowed - try Msty OpenAI-compatible endpoint
                    print(f"[DEBUG] Native endpoint returned {response.status_code}, trying Msty fallback...")
                    pass
                else:
                    error_body = response.text[:500] if response.text else "No response body"
                    print(f"[WARNING] Native endpoint error: HTTP {response.status_code} - {error_body}")
                    return {
                        'success': False,
                        'error': f'Ollama error: HTTP {response.status_code} - {error_body[:100]}'
                    }
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
        
        prompt = f"""
You are a helpful assistant analyzing a document. Answer the user's question based on the document content.

**Document Content:**
{context_text[:3000]}

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
                        elif response.status_code in [404, 405]:
                            print(f"[DEBUG] Chat: Native endpoint returned {response.status_code}, trying Msty fallback...")
                            pass
                        else:
                            error_body = response.text[:500] if response.text else "No response body"
                            print(f"[WARNING] Chat: Native endpoint error: HTTP {response.status_code}")
                            return {
                                'success': False,
                                'error': f'Ollama error: HTTP {response.status_code}'
                            }
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
