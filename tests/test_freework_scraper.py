import unittest

from openclaw.models.domain import RemoteMode
from openclaw.scrapers.freework import (
    _extract_daily_rate,
    _extract_external_id,
    _extract_industry,
    _extract_keywords,
    _extract_remote_days,
    _extract_remote_mode,
    _rewrite_launch_error,
)


class FreeWorkScraperParsingTests(unittest.TestCase):
    def test_extracts_lower_bound_of_rate_range(self) -> None:
        body = "Freelance\n400-550 \u20ac\u2044j\nTeletravail partiel\n"
        self.assertEqual(_extract_daily_rate(body), 400)

    def test_extracts_remote_mode_and_days(self) -> None:
        text = (
            "mission java spring boot keycloak teletravail partiel "
            "localisation paris 2 jours remote"
        )

        self.assertEqual(_extract_remote_mode(text), RemoteMode.HYBRID)
        self.assertEqual(_extract_remote_days(text), 2)

    def test_extracts_keywords_industry_and_external_id(self) -> None:
        text = (
            "reference de l offre : abc123 banque java spring boot "
            "keycloak oauth2 kubernetes"
        )

        self.assertEqual(
            _extract_keywords(text),
            ("spring boot", "java", "spring", "keycloak", "oauth2", "kubernetes"),
        )
        self.assertEqual(_extract_industry(text), "banking")
        self.assertEqual(
            _extract_external_id(
                "https://www.free-work.com/fr/tech-it/job-mission/backend-java",
                text,
            ),
            "abc123",
        )

    def test_rewrites_missing_browser_error(self) -> None:
        error = Exception(
            "BrowserType.launch_persistent_context: Executable doesn't exist at /tmp/chromium\n"
            "Please run the following command to download new browsers: playwright install"
        )

        rewritten = _rewrite_launch_error(error)

        self.assertIsInstance(rewritten, RuntimeError)
        self.assertIn("-m playwright install chromium", str(rewritten))


if __name__ == "__main__":
    unittest.main()
