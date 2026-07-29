import unittest

from crawler.title_classifier import (
    AcademicTrack,
    AffiliationStatus,
    ClassificationResult,
    ConfidenceTier,
    StaffClassification,
    TitleClassifier,
    normalize_title,
)


class TitleClassifierContractTests(unittest.TestCase):
    def test_normalize_title_preserves_unicode_and_normalizes_spacing(self) -> None:
        self.assertEqual(normalize_title("  أستاذ\u00a0 مشارك  "), "أستاذ مشارك")

    def test_result_exposes_auditable_fields(self) -> None:
        result = ClassificationResult(
            classification=StaffClassification.INCLUDE,
            academic_track=AcademicTrack.RESEARCH,
            affiliation_status=AffiliationStatus.CURRENT,
            reason="academic_phrase:research fellow",
            matched_rule="research fellow",
            confidence=ConfidenceTier.HIGH,
        )

        self.assertEqual(result.classification.value, "include")
        self.assertEqual(result.academic_track.value, "research")
        self.assertEqual(result.affiliation_status.value, "current")
        self.assertEqual(result.reason, "academic_phrase:research fellow")
        self.assertEqual(result.matched_rule, "research fellow")
        self.assertEqual(result.confidence.value, "high")


class TitleClassifierRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = TitleClassifier()

    def assert_classification(self, title: str, expected: StaffClassification) -> None:
        result = self.classifier.classify(title)
        self.assertEqual(result.classification, expected, result)

    def test_confirmed_inclusions(self) -> None:
        titles = (
            "Professor",
            "Reader",
            "Associate Lecturer",
            "Research Fellow",
            "Principal Research Scientist",
            "Postdoctoral Researcher",
            "Clinical Lecturer",
            "Professor of Practice",
            "Visiting Professor",
            "Adjunct Professor",
            "Doctoral Researcher",
            "أستاذ مشارك",
            "Maître de conférences",
            "Privatdozent",
            "Universitair docent",
            "Assegnista di ricerca",
        )

        for title in titles:
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.INCLUDE)

    def test_italian_research_grant_holder_is_research_track(self) -> None:
        result = self.classifier.classify("Assegnista di ricerca")

        self.assertEqual(result.classification, StaffClassification.INCLUDE)
        self.assertEqual(result.academic_track, AcademicTrack.RESEARCH)
        self.assertEqual(result.affiliation_status, AffiliationStatus.CURRENT)
        self.assertEqual(result.matched_rule, "assegnista di ricerca")

    def test_validated_gendered_and_localized_titles_use_exact_original_rules(self) -> None:
        expected = {
            "Professoressa ordinaria": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Professoressa associata": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Universitätsprofessorin": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Maîtresse de conférences": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Enseignant-chercheur": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Enseignante-chercheuse": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Chargé de recherche": (AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
            "Chargée de recherche": (AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
            "Professeure des universités": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
            "Professora associada": (AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
        }

        for title, (track, status) in expected.items():
            with self.subTest(title=title):
                result = self.classifier.classify(title)
                self.assertEqual(result.classification, StaffClassification.INCLUDE)
                self.assertEqual(result.academic_track, track)
                self.assertEqual(result.affiliation_status, status)
                self.assertTrue(result.matched_rule)

    def test_status_exclusions_override_academic_titles(self) -> None:
        titles = (
            "Emeritus Professor and Research Director",
            "Professor Emerita",
            "Honorary Clinical Professor",
            "Former Professor, Senior Research Fellow",
            "Retired Reader",
        )

        for title in titles:
            with self.subTest(title=title):
                result = self.classifier.classify(title)
                self.assertEqual(result.classification, StaffClassification.EXCLUDE)
                self.assertEqual(result.affiliation_status, AffiliationStatus.INACTIVE_OR_HONORARY)
                self.assertTrue(result.reason.startswith("inactive_or_honorary:"))

    def test_student_and_assistant_exclusions_override_doctoral_researcher(self) -> None:
        titles = (
            "Doctoral Researcher / PhD Candidate",
            "Doctoral Researcher and Teaching Assistant",
            "Research Assistant",
            "PhD Student",
            "Doctoral Candidate",
        )

        for title in titles:
            with self.subTest(title=title):
                result = self.classifier.classify(title)
                self.assertEqual(result.classification, StaffClassification.EXCLUDE)
                self.assertTrue(result.reason.startswith("student_or_assistant:"))

        doctoral_researcher = self.classifier.classify("Doctoral Researcher")
        self.assertEqual(doctoral_researcher.classification, StaffClassification.INCLUDE)
        self.assertEqual(doctoral_researcher.academic_track, AcademicTrack.DOCTORAL_RESEARCHER)

    def test_professional_services_are_excluded(self) -> None:
        expected_categories = {
            "Academic Librarian": "library_staff",
            "IT Technologist": "it_staff",
            "Research Software Engineer": "it_staff",
            "Bioinformatician": "it_staff",
            "Laboratory Technician": "technical_staff",
            "Research Support Officer": "research_support_staff",
            "Teaching Administrator": "student_services_staff",
            "Communications Officer": "communications_staff",
            "Facilities Manager": "facilities_staff",
        }

        for title, category in expected_categories.items():
            with self.subTest(title=title):
                result = self.classifier.classify(title)
                self.assertEqual(result.classification, StaffClassification.EXCLUDE)
                self.assertTrue(result.reason.startswith(f"{category}:"))

    def test_broad_words_do_not_override_academic_phrases(self) -> None:
        titles = (
            "Professor of Library Science",
            "Assistant Professor",
            "Research Scientist",
            "Professor of Information Technology",
            "Clinical Associate Professor",
        )

        for title in titles:
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.INCLUDE)

    def test_ambiguous_titles_require_review(self) -> None:
        titles = (
            "Researcher",
            "Director",
            "Consultant Cardiologist",
            "Program Coordinator",
            "Faculty Member",
        )

        for title in titles:
            with self.subTest(title=title):
                result = self.classifier.classify(title)
                self.assertEqual(result.classification, StaffClassification.REVIEW)
                self.assertTrue(result.reason.startswith("ambiguous_phrase:"))

    def test_missing_and_unknown_titles_require_review(self) -> None:
        self.assertEqual(self.classifier.classify("").reason, "missing_title")
        self.assertEqual(self.classifier.classify("Unmapped Role").reason, "no_rule_matched")

    def test_translated_match_has_medium_confidence(self) -> None:
        result = self.classifier.classify("Associate Professor", translated=True)

        self.assertEqual(result.classification, StaffClassification.INCLUDE)
        self.assertEqual(result.confidence, ConfidenceTier.MEDIUM)


if __name__ == "__main__":
    unittest.main()

