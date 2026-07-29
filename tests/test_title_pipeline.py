import unittest

from crawler.title_classifier import StaffClassification, TitleClassifier
from crawler.title_pipeline import TitlePipeline
from crawler.translation import TranslationResult, TranslationStatus


class FakeTranslator:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def translate(self, title, source_language="auto"):
        self.calls.append((title, source_language))
        return self.result


class TitlePipelineTests(unittest.TestCase):
    def test_known_original_title_does_not_call_translation(self) -> None:
        translator = FakeTranslator(TranslationResult(status=TranslationStatus.SUCCESS, translated_text="unused"))
        result = TitlePipeline(TitleClassifier(), translator).process("Professor")
        self.assertEqual(result.classification.classification, StaffClassification.INCLUDE)
        self.assertEqual(translator.calls, [])

    def test_unknown_non_english_title_uses_translation(self) -> None:
        translator = FakeTranslator(TranslationResult(
            status=TranslationStatus.SUCCESS,
            translated_text="Associate Professor",
            detected_language="ar",
        ))
        result = TitlePipeline(TitleClassifier(), translator).process("unknown title", language_hint="ar")
        self.assertEqual(result.classification.classification, StaffClassification.INCLUDE)
        self.assertEqual(result.title_translated, "Associate Professor")
        self.assertEqual(result.title_language, "ar")

    def test_translation_failure_is_review(self) -> None:
        translator = FakeTranslator(TranslationResult(status=TranslationStatus.SERVICE_UNAVAILABLE))
        result = TitlePipeline(TitleClassifier(), translator).process("unknown title", language_hint="ar")
        self.assertEqual(result.classification.classification, StaffClassification.REVIEW)
        self.assertEqual(result.translation_status, "service_unavailable")

    def test_unknown_title_on_english_page_does_not_call_translation(self) -> None:
        translator = FakeTranslator(TranslationResult(
            status=TranslationStatus.SUCCESS,
            translated_text="unused",
        ))
        result = TitlePipeline(TitleClassifier(), translator).process(
            "Programme Director", language_hint="en"
        )
        self.assertEqual(result.classification.classification, StaffClassification.REVIEW)
        self.assertEqual(translator.calls, [])

    def test_empty_title_is_review_without_translation(self) -> None:
        translator = FakeTranslator(TranslationResult(status=TranslationStatus.SUCCESS, translated_text="Professor"))
        result = TitlePipeline(TitleClassifier(), translator).process("")
        self.assertEqual(result.classification.classification, StaffClassification.REVIEW)
        self.assertEqual(translator.calls, [])


if __name__ == "__main__":
    unittest.main()
