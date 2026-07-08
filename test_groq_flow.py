#!/usr/bin/env python3
"""Test Groq provider in the actual analyzer flow."""

from ai_pdf_analyzer import AIPDFAnalyzer
import json

# Initialize analyzer
analyzer = AIPDFAnalyzer()

print("=== ANALYZER STATE ===")
print(f"groq_initialized: {analyzer.groq_initialized}")
print(f"groq API key: {bool(analyzer._groq_api_key)}")
print(f"\nAvailable providers: {analyzer.get_available_providers()}")

# Try a simple analysis
test_text = """
This is a test document. It contains some sample text to analyze using Groq provider.
The Groq API should be able to process this and return a summary.
"""

print("\n=== ATTEMPTING ANALYSIS WITH GROQ ===")
result = analyzer.chat_with_context(
    message="Please summarize this document.",
    context_text=test_text,
    provider='groq'
)

print(f"\nResult: {json.dumps(result, indent=2)}")
