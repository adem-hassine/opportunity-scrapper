import unittest

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringRules, QualificationRoute, score_opportunity
from openclaw.services.resume_selector import select_best_resume


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = FilteringRules(
            minimum_tjm=650,
            remote_required=True,
            excluded_keywords=("wordpress", "php", "onsite only"),
            required_keywords=("java", "spring", "sso", "keycloak"),
            auto_reject_score_below=45,
            alert_score_from=75,
        )

    def test_high_quality_opportunity_goes_to_alert(self) -> None:
        opportunity = Opportunity(
            platform="free-work",
            external_id="mission-1",
            title="Senior Java IAM Consultant",
            client="Large Banking Group",
            location="Paris",
            daily_rate_eur=750,
            remote_mode=RemoteMode.REMOTE,
            summary="Java 21, Spring Boot, Keycloak, OAuth2, Kubernetes",
            keywords=("java", "spring", "keycloak", "oauth2", "kubernetes"),
            industry="banking",
        )

        result = score_opportunity(opportunity, self.rules)

        self.assertFalse(result.rejected)
        self.assertEqual(result.route, QualificationRoute.ALERT)
        self.assertGreaterEqual(result.score, 75)

    def test_excluded_keyword_rejects_opportunity(self) -> None:
        opportunity = Opportunity(
            platform="malt",
            external_id="mission-2",
            title="PHP WordPress mission",
            daily_rate_eur=700,
            remote_mode=RemoteMode.REMOTE,
            summary="Build and maintain WordPress plugins in PHP.",
            keywords=("wordpress", "php"),
            industry="agency",
        )

        result = score_opportunity(opportunity, self.rules)

        self.assertTrue(result.rejected)
        self.assertEqual(result.route, QualificationRoute.REJECT)
        self.assertIn("Excluded keyword match", result.reasons[0])

    def test_resume_selection_prefers_iam_resume(self) -> None:
        opportunity = Opportunity(
            platform="lehibou",
            external_id="mission-3",
            title="Identity and Access Management Architect",
            client="Insurance Group",
            location="Paris",
            daily_rate_eur=800,
            remote_mode=RemoteMode.HYBRID,
            summary="Keycloak, OAuth2, SSO, SAML federation and security architecture.",
            keywords=("keycloak", "oauth2", "sso", "saml", "security"),
            industry="security",
        )

        match = select_best_resume(opportunity)

        self.assertEqual(match.key, "iam-sso")
        self.assertGreater(match.score, 0)

