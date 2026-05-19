import unittest
from datetime import date
from types import SimpleNamespace

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.scrapers.freework import (
    ScrapedOpportunityRecord,
    _build_parser,
    _build_search_urls,
    _extract_daily_rate,
    _extract_external_id,
    _extract_industry,
    _extract_keywords,
    _extract_published_at,
    _extract_remote_days,
    _extract_remote_mode,
    _filter_records_from_date,
    _keyword_to_search_url,
    _qualify_records,
    _rewrite_launch_error,
)
from openclaw.services.filtering import FilteringRules


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

    def test_extracts_publication_date(self) -> None:
        text = "publiee le 03/04/2026 mission java spring keycloak"

        self.assertEqual(_extract_published_at(text), date(2026, 4, 3))

    def test_rewrites_missing_browser_error(self) -> None:
        error = Exception(
            "BrowserType.launch_persistent_context: Executable doesn't exist at /tmp/chromium\n"
            "Please run the following command to download new browsers: playwright install"
        )

        rewritten = _rewrite_launch_error(error)

        self.assertIsInstance(rewritten, RuntimeError)
        self.assertIn("-m playwright install chromium", str(rewritten))

    def test_filtering_rules_can_be_built_from_settings(self) -> None:
        settings = SimpleNamespace(
            minimum_tjm=700,
            remote_required=False,
            excluded_keywords=["php"],
            required_keywords=["java", "keycloak"],
            auto_reject_score_below=30,
            alert_score_from=80,
        )

        rules = FilteringRules.from_settings(settings)

        self.assertEqual(rules.minimum_tjm, 700)
        self.assertFalse(rules.remote_required)
        self.assertEqual(rules.excluded_keywords, ("php",))
        self.assertEqual(rules.required_keywords, ("java", "keycloak"))
        self.assertEqual(rules.auto_reject_score_below, 30)
        self.assertEqual(rules.alert_score_from, 80)

    def test_keyword_to_search_url_slugifies_terms(self) -> None:
        self.assertEqual(
            _keyword_to_search_url("Spring Boot"),
            "https://www.free-work.com/fr/tech-it/jobs/spring-boot",
        )
        self.assertEqual(
            _keyword_to_search_url("keycloak"),
            "https://www.free-work.com/fr/tech-it/jobs/keycloak",
        )

    def test_build_search_urls_uses_required_keywords_and_deduplicates(self) -> None:
        urls = _build_search_urls(required_keywords=["java", "keycloak", "java"])

        self.assertEqual(
            urls,
            [
                "https://www.free-work.com/fr/tech-it/jobs/java",
                "https://www.free-work.com/fr/tech-it/jobs/keycloak",
            ],
        )

    def test_parser_uses_from_date_and_has_no_limit_option(self) -> None:
        parser = _build_parser()

        self.assertEqual(
            parser.parse_args(["--from-date", "2026-05-01"]).from_date,
            date(2026, 5, 1),
        )
        self.assertNotIn("--limit", parser._option_string_actions)

    def test_filter_records_from_date_keeps_recent_records_only(self) -> None:
        records = [
            ScrapedOpportunityRecord(
                url="https://example.com/recent",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="recent",
                    title="Recent mission",
                    published_at=date(2026, 5, 10),
                ),
            ),
            ScrapedOpportunityRecord(
                url="https://example.com/old",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="old",
                    title="Old mission",
                    published_at=date(2026, 4, 30),
                ),
            ),
            ScrapedOpportunityRecord(
                url="https://example.com/unknown",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="unknown",
                    title="Unknown mission",
                ),
            ),
        ]

        filtered_records = _filter_records_from_date(
            records,
            from_date=date(2026, 5, 1),
        )

        self.assertEqual(len(filtered_records), 1)
        self.assertEqual(filtered_records[0].opportunity.external_id, "recent")

    def test_qualify_records_skips_rejected_results_by_default(self) -> None:
        rules = FilteringRules(
            minimum_tjm=650,
            excluded_keywords=("php",),
            required_keywords=("keycloak",),
        )
        records = [
            ScrapedOpportunityRecord(
                url="https://example.com/accepted",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="accepted",
                    title="Senior IAM Consultant",
                    published_at=date(2026, 5, 10),
                    daily_rate_eur=750,
                    remote_mode=RemoteMode.REMOTE,
                    summary="Java Spring Keycloak migration for a banking client.",
                    keywords=("java", "spring", "keycloak"),
                    industry="banking",
                ),
            ),
            ScrapedOpportunityRecord(
                url="https://example.com/rejected",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="rejected",
                    title="PHP Developer",
                    published_at=date(2026, 5, 10),
                    daily_rate_eur=900,
                    remote_mode=RemoteMode.REMOTE,
                    summary="Legacy PHP maintenance mission.",
                    keywords=("php",),
                ),
            ),
        ]

        qualified_records = _qualify_records(records, rules=rules)

        self.assertEqual(len(qualified_records), 1)
        accepted = qualified_records[0]
        self.assertEqual(accepted["external_id"], "accepted")
        self.assertEqual(accepted["route"], "alert")
        self.assertFalse(accepted["rejected"])
        self.assertEqual(accepted["matched_keywords"], ["keycloak"])

    def test_qualify_records_can_include_rejected_results(self) -> None:
        rules = FilteringRules(
            minimum_tjm=650,
            excluded_keywords=("php",),
            required_keywords=("keycloak",),
        )
        records = [
            ScrapedOpportunityRecord(
                url="https://example.com/rejected",
                opportunity=Opportunity(
                    platform="free-work",
                    external_id="rejected",
                    title="PHP Developer",
                    published_at=date(2026, 5, 10),
                    daily_rate_eur=900,
                    remote_mode=RemoteMode.REMOTE,
                    summary="Legacy PHP maintenance mission.",
                    keywords=("php",),
                ),
            )
        ]

        qualified_records = _qualify_records(
            records,
            rules=rules,
            include_rejected=True,
        )

        self.assertEqual(len(qualified_records), 1)
        rejected = qualified_records[0]
        self.assertEqual(rejected["external_id"], "rejected")
        self.assertEqual(rejected["route"], "reject")
        self.assertTrue(rejected["rejected"])
        self.assertIn("Excluded keyword match: php.", rejected["reasons"])


if __name__ == "__main__":
    unittest.main()
