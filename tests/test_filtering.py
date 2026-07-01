import unittest

from openclaw.models.domain import Opportunity, RemoteMode, ResumeVariant
from openclaw.services.filtering import FilteringRules, QualificationRoute, score_opportunity
from openclaw.services.resume_selector import select_best_resume
from openclaw.services.telegram import build_opportunity_alert


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = FilteringRules(
            minimum_tjm=650,
            allowed_remote_modes=(RemoteMode.REMOTE, RemoteMode.HYBRID),
            excluded_keywords=("wordpress", "php", "onsite only"),
            required_keywords=("java", "spring", "sso", "keycloak"),
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

    def test_excluded_keyword_still_alerts_during_temporary_pass_through(self) -> None:
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

        self.assertFalse(result.rejected)
        self.assertEqual(result.route, QualificationRoute.ALERT)

    def test_resume_selection_prefers_iam_resume(self) -> None:
        test_resumes = (
            ResumeVariant(
                key="java-backend",
                label="Java Backend",
                summary="Generic Java/Spring backend consulting profile.",
                primary_keywords=("java", "spring", "spring boot", "rest", "microservices"),
                industries=("banking", "finance", "retail"),
                preferred_tone="consultative",
            ),
            ResumeVariant(
                key="iam-sso",
                label="IAM / SSO Expert",
                summary="Identity, federation, and access management profile.",
                primary_keywords=("keycloak", "oauth2", "sso", "saml", "auth0", "okta"),
                industries=("banking", "insurance", "security"),
                preferred_tone="enterprise",
            ),
        )
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

        match = select_best_resume(opportunity, test_resumes)

        self.assertEqual(match.key, "iam-sso")
        self.assertGreater(match.score, 0)

    def test_telegram_alert_includes_duration_and_required_experience(self) -> None:
        opportunity = Opportunity(
            platform="free-work",
            external_id="mission-4",
            title="Responsable Cybersécurité",
            daily_rate_eur=650,
            duration_months=36,
            required_experience_years=10,
            remote_mode=RemoteMode.HYBRID,
            summary="IAM Keycloak security architecture.",
            keywords=("iam", "keycloak"),
        )

        result = score_opportunity(opportunity, self.rules)
        message = build_opportunity_alert(opportunity, result)

        self.assertIn("Duration: 3 year(s)", message)
        self.assertIn("Required experience: 10+ year(s)", message)
