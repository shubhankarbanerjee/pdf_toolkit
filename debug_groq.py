#!/usr/bin/env python3
"""Debug script to check Groq initialization."""

from ai_pdf_analyzer import AIPDFAnalyzer

analyzer = AIPDFAnalyzer()

print(f"Groq initialized: {analyzer.groq_initialized}")
print(f"Groq API key present: {bool(analyzer._groq_api_key)}")
print(f"Groq config enabled: {analyzer.config.get('groq', {}).get('enabled')}")

api_key = analyzer.config.get('groq', {}).get('api_key')
if api_key:
    print(f"Groq API key in config: {api_key[:10]}...")
else:
    print("Groq API key in config: NOT SET")

print(f"\nFull Groq config: {analyzer.config.get('groq', {})}")
print(f"\nHAS_REQUESTS: {analyzer.config_manager.__dict__}")
