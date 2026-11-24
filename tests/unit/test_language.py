"""
Unit tests for language detection and translation capabilities.
"""

import unittest
from unittest.mock import patch
import pytest
from typing import Dict, List, Any, Tuple

from src.backend.services.language_utils import (
    detect_language,
    translate_text,
    translate_content_blocks,
    normalize_language_name
)

class TestLanguageDetection(unittest.TestCase):
    """Test language detection functionality"""
    
    def test_detect_english(self):
        """Test that English is correctly detected"""
        lang, confidence = detect_language("Hello, this is a test message in English.")
        self.assertEqual(lang, "en")
        self.assertGreater(confidence, 0.5)
        
    def test_detect_bengali(self):
        """Test that Bengali is correctly detected"""
        lang, confidence = detect_language("আমি বাংলায় কথা বলি।")
        self.assertEqual(lang, "bn")
        self.assertGreater(confidence, 0.5)
        
    def test_detect_spanish(self):
        """Test that Spanish is correctly detected"""
        lang, confidence = detect_language("Hola, ¿cómo estás? Este es un mensaje de prueba.")
        self.assertEqual(lang, "es")
        self.assertGreater(confidence, 0.5)
        
    def test_detect_short_text(self):
        """Test that short text defaults to English"""
        lang, confidence = detect_language("Hi")
        self.assertEqual(lang, "en")
        
    def test_detect_empty_text(self):
        """Test that empty text defaults to English"""
        lang, confidence = detect_language("")
        self.assertEqual(lang, "en")
        
class TestTranslation(unittest.TestCase):
    """Test translation functionality"""
    
    @patch("src.backend.services.language_utils.GoogleTranslator")
    def test_translate_to_english(self, translator):
        """Legacy utility forwards the source and target without requiring network."""
        translator.return_value.translate.return_value = "Hello, how are you?"
        translated = translate_text("Hola, ¿cómo estás?", target_lang="en", source_lang="es")
        translator.assert_called_once_with(source="es", target="en")
        self.assertEqual(translated, "Hello, how are you?")
        
    @patch("src.backend.services.language_utils.GoogleTranslator")
    def test_translate_to_spanish(self, translator):
        translator.return_value.translate.return_value = "Hola, ¿cómo estás?"
        translated = translate_text("Hello, how are you?", target_lang="es", source_lang="en")
        translator.assert_called_once_with(source="en", target="es")
        self.assertEqual(translated, "Hola, ¿cómo estás?")
        
    def test_translate_same_language(self):
        """Test that text remains unchanged when source and target are the same"""
        original = "Hello, how are you?"
        translated = translate_text(original, target_lang="en", source_lang="en")
        self.assertEqual(original, translated)
        
    def test_translate_empty_text(self):
        """Test that empty text remains empty"""
        translated = translate_text("", target_lang="fr", source_lang="en")
        self.assertEqual("", translated)
        
    @patch("src.backend.services.language_utils.GoogleTranslator")
    def test_translate_content_blocks(self, translator):
        translator.return_value.translate_batch.return_value = [
            "Hola, esto es una prueba.", "Otro mensaje de prueba."
        ]
        blocks = [
            {
                "content": "Hello, this is a test.",
                "metadata": {"source": "test1.txt"}
            },
            {
                "content": "Another test message.",
                "metadata": {"source": "test2.txt"}
            }
        ]
        
        translated = translate_content_blocks(blocks, target_lang="es")
        
        self.assertEqual(len(translated), 2)
        self.assertIn("hola", translated[0]["content"].lower())
        self.assertNotEqual(blocks[0]["content"], translated[0]["content"])
        self.assertNotEqual(blocks[1]["content"], translated[1]["content"])
        self.assertEqual(translated[0]["metadata"], blocks[0]["metadata"])
        
    def test_translate_content_blocks_en_to_en(self):
        """Test that content blocks remain unchanged when target is English"""
        blocks = [
            {
                "content": "Hello, this is a test.",
                "metadata": {"source": "test1.txt"}
            }
        ]
        
        translated = translate_content_blocks(blocks, target_lang="en")
        
        self.assertEqual(len(translated), 1)
        self.assertEqual(blocks[0]["content"], translated[0]["content"])
        
    def test_normalize_language_name(self):
        """Test language name normalization"""
        self.assertEqual(normalize_language_name("en"), "english")
        self.assertEqual(normalize_language_name("EN"), "english")
        self.assertEqual(normalize_language_name("english"), "english")
        self.assertEqual(normalize_language_name("ENGLISH"), "english")
        self.assertEqual(normalize_language_name("custom"), "custom")

if __name__ == "__main__":
    unittest.main() 
