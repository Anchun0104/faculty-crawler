from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from crawler.title_classifier import (
    RULES_VERSION,
    ClassificationResult,
    StaffClassification,
    TitleClassifier,
)
from crawler.translation import TranslationResult, TranslationStatus


@dataclass(frozen=True)
class ProcessedTitle:
    title_original: str
    title_translated: str
    title_language: str
    classification: ClassificationResult
    translation_status: str
    translation_engine: str = ""
    rules_version: str = RULES_VERSION


class TitlePipeline:
    def __init__(self, classifier: TitleClassifier, translator=None) -> None:
        self.classifier = classifier
        self.translator = translator

    def process(self, title_original: str, *, language_hint: str = "") -> ProcessedTitle:
        original = title_original.strip()
        language = language_hint.casefold().split("-", 1)[0]
        classification = self.classifier.classify(original)
        if classification.classification is not StaffClassification.REVIEW:
            return ProcessedTitle(original, "", language, classification, TranslationStatus.NOT_NEEDED.value)
        if not original or self.translator is None or language == "en" or not (language or contains_non_ascii_letters(original)):
            return ProcessedTitle(original, "", language, classification, TranslationStatus.NOT_NEEDED.value)

        result: TranslationResult = self.translator.translate(original, source_language=language or "auto")
        if result.status not in {TranslationStatus.SUCCESS, TranslationStatus.CACHE_HIT}:
            return ProcessedTitle(original, "", result.detected_language or language, classification, result.status.value, result.engine)
        translated_classification = self.classifier.classify(result.translated_text, translated=True)
        return ProcessedTitle(
            original,
            result.translated_text,
            result.detected_language or language,
            translated_classification,
            result.status.value,
            result.engine,
        )


def contains_non_ascii_letters(value: str) -> bool:
    return any(char.isalpha() and ord(char) > 127 for char in unicodedata.normalize("NFKC", value))
