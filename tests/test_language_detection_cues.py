"""English questions must not be classified as Bangla by short romanised cues."""
import pytest

from src.backend.services.language_utils import detect_language


@pytest.mark.parametrize("question", [
    "What are the working hours?",
    "Is marketing allowed to see finance data?",
    "Explain taking leave",
])
def test_english_questions_with_embedded_cues_stay_english(question):
    assert detect_language(question)[0] == "en"


@pytest.mark.parametrize("question", [
    "ami kemon achi",
    "ki khobor",
    "আমি ছুটি চাই",
    "কর্মচারীরা বছরে কত দিন বার্ষিক ছুটি পায়?",
])
def test_bangla_cues_still_detected(question):
    assert detect_language(question)[0] == "bn"
