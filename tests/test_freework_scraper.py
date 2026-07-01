import unittest
from datetime import date
from types import SimpleNamespace

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.scrapers.freework import (
    ScrapedOpportunityRecord,
    _build_parser,
    _build_search_urls,
    _card_text_matches_listing_criteria,
    _extract_card_annual_salary,
    _extract_card_daily_rate,
    _extract_card_duration_months,
    _extract_daily_rate,
    _extract_duration_months,
    _extract_external_id,
    _extract_industry,
    _extract_keywords,
    _extract_published_at,
    _extract_required_experience_years,
    _extract_remote_days,
    _extract_remote_mode,
    _filter_records_from_date,
    _is_blank_page_url,
    _keyword_to_search_url,
    _listing_body_indicates_no_results,
    _qualify_records,
    _rewrite_launch_error,
    _url_with_page,
)
from openclaw.services.filtering import FilteringRules


class FreeWorkScraperParsingTests(unittest.TestCase):
    def test_extracts_upper_bound_of_rate_range(self) -> None:
        body = "Freelance\n400-550 \u20ac\u2044j\nTeletravail partiel\n"
        self.assertEqual(_extract_daily_rate(body), 550)

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
            unspecified_tjm=True,
            allowed_remote_modes=[RemoteMode.REMOTE, RemoteMode.HYBRID],
            excluded_keywords=["php"],
            required_keywords=["java", "keycloak"],
        )

        rules = FilteringRules.from_settings(settings)

        self.assertEqual(rules.minimum_tjm, 700)
        self.assertTrue(rules.unspecified_tjm)
        self.assertEqual(rules.allowed_remote_modes, (RemoteMode.REMOTE, RemoteMode.HYBRID))
        self.assertEqual(rules.excluded_keywords, ("php",))
        self.assertEqual(rules.required_keywords, ("java", "keycloak"))

    def test_keyword_to_search_url_slugifies_terms(self) -> None:
        self.assertEqual(
            _keyword_to_search_url("Spring Boot"),
            "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=spring%20boot&sort=date",
        )
        self.assertEqual(
            _keyword_to_search_url("keycloak"),
            "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=keycloak&sort=date",
        )

    def test_build_search_urls_uses_one_url_per_required_keyword_and_deduplicates(self) -> None:
        urls = _build_search_urls(required_keywords=["java", "keycloak", "java"])

        self.assertEqual(
            urls,
            [
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=java&sort=date",
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=keycloak&sort=date",
            ],
        )

    def test_build_search_urls_keeps_yaml_list_items_as_separate_queries(self) -> None:
        urls = _build_search_urls(
            required_keywords=["senior java developer", "keycloak", "iam"]
        )

        self.assertEqual(
            urls,
            [
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=senior%20java%20developer&sort=date",
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=keycloak&sort=date",
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=iam&sort=date",
            ],
        )

    def test_build_search_urls_splits_comma_separated_terms(self) -> None:
        urls = _build_search_urls(required_keywords=["java, keycloak"])

        self.assertEqual(
            urls,
            [
                "https://www.free-work.com/fr/tech-it/jobs?locations=fr~~~&query=java%20keycloak&sort=date",
            ],
        )

    def test_url_with_page_preserves_query_and_replaces_page(self) -> None:
        self.assertEqual(
            _url_with_page(
                "https://www.free-work.com/fr/tech-it/jobs/java?query=java&locations=fr~~~",
                3,
            ),
            "https://www.free-work.com/fr/tech-it/jobs/java?query=java&locations=fr~~~&page=3",
        )
        self.assertEqual(
            _url_with_page(
                "https://www.free-work.com/fr/tech-it/jobs/java?query=java&page=2",
                5,
            ),
            "https://www.free-work.com/fr/tech-it/jobs/java?query=java&page=5",
        )

    def test_blank_and_no_result_pages_are_detected(self) -> None:
        self.assertTrue(_is_blank_page_url("about:blank"))
        self.assertFalse(
            _is_blank_page_url("https://www.free-work.com/fr/tech-it/jobs?query=java")
        )
        self.assertTrue(_listing_body_indicates_no_results("Aucune offre ne correspond."))
        self.assertTrue(_listing_body_indicates_no_results("0 mission trouvee"))
        self.assertFalse(_listing_body_indicates_no_results("Mission Java Keycloak"))

    def test_card_pay_extractors_read_tjm_and_annual_salary(self) -> None:
        self.assertEqual(_extract_card_daily_rate("TJM 700-850 €⁄j"), 850)
        self.assertEqual(_extract_card_daily_rate("Salaire 500 EUR / j"), 500)
        self.assertEqual(_extract_card_annual_salary("Salaire 90k-120k €⁄an"), 90_000)
        self.assertEqual(_extract_card_annual_salary("40k-65k €⁄an"), 40_000)

    def test_card_matching_filters_by_employment_type_and_compensation(self) -> None:
        freelance_and_cdi = "Freelance CDI Ingénieur Java TJM 750 €⁄j Durée 12 mois Salaire 70k-90k €⁄an"
        cdi_only = "CDI Data engineer Salaire 100k-120k €⁄an"
        low_salary_cdi = "CDI Data engineer Salaire 40k-65k €⁄an"

        self.assertTrue(
            _card_text_matches_listing_criteria(
                freelance_and_cdi,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )
        self.assertFalse(
            _card_text_matches_listing_criteria(
                cdi_only,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )
        self.assertTrue(
            _card_text_matches_listing_criteria(
                cdi_only,
                employment_types=("cdi",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )
        self.assertFalse(
            _card_text_matches_listing_criteria(
                low_salary_cdi,
                employment_types=("cdi",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )

    def test_card_matching_allows_unspecified_freelance_tjm_when_enabled(self) -> None:
        freelance_without_rate = "Freelance Architecte Java Keycloak Durée 12 mois"

        self.assertTrue(
            _card_text_matches_listing_criteria(
                freelance_without_rate,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )
        self.assertFalse(
            _card_text_matches_listing_criteria(
                freelance_without_rate,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=False,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )

    def test_card_duration_extractors_read_months_and_years(self) -> None:
        self.assertEqual(_extract_card_duration_months("Durée 12 mois"), 12)
        self.assertEqual(_extract_card_duration_months("Duree 1 an"), 12)
        self.assertEqual(_extract_card_duration_months("Durée 2 ans"), 24)
        self.assertIsNone(_extract_card_duration_months("Dès que possible"))

    def test_detail_metadata_extractors_read_duration_and_experience(self) -> None:
        text = "29/06/2026\n36 mois\n650-750 €⁄j\n> 10 ans d’expérience"

        self.assertEqual(_extract_duration_months(text), 36)
        self.assertEqual(_extract_required_experience_years(text), 10)

    def test_card_matching_filters_freelance_by_minimum_duration(self) -> None:
        short_mission = "Freelance Développeur Java TJM 750 €⁄j Durée 3 mois"
        long_mission = "Freelance Développeur Java TJM 750 €⁄j Durée 12 mois"

        self.assertFalse(
            _card_text_matches_listing_criteria(
                short_mission,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )
        self.assertTrue(
            _card_text_matches_listing_criteria(
                long_mission,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
            )
        )

    def test_card_matching_filters_by_allowed_remote_modes(self) -> None:
        onsite_mission = "Freelance Développeur Java TJM 750 €⁄j Durée 12 mois Présentiel"

        self.assertFalse(
            _card_text_matches_listing_criteria(
                onsite_mission,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
                allowed_remote_modes=(RemoteMode.REMOTE, RemoteMode.HYBRID),
            )
        )
        self.assertTrue(
            _card_text_matches_listing_criteria(
                onsite_mission,
                employment_types=("freelance",),
                minimum_tjm=650,
                unspecified_tjm=True,
                minimum_duration_months=6,
                minimum_year_salary=90_000,
                allowed_remote_modes=(RemoteMode.ONSITE,),
            )
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

    def test_qualify_records_keeps_all_results_during_temporary_pass_through(self) -> None:
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

        self.assertEqual(len(qualified_records), 2)
        accepted = qualified_records[0]
        self.assertEqual(accepted["external_id"], "accepted")
        self.assertEqual(accepted["route"], "alert")
        self.assertFalse(accepted["rejected"])
        self.assertEqual(accepted["matched_keywords"], ["keycloak"])
        previously_rejected = qualified_records[1]
        self.assertEqual(previously_rejected["external_id"], "rejected")
        self.assertEqual(previously_rejected["route"], "alert")
        self.assertFalse(previously_rejected["rejected"])

    def test_qualify_records_include_rejected_flag_has_no_effect_during_pass_through(self) -> None:
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
        record = qualified_records[0]
        self.assertEqual(record["external_id"], "rejected")
        self.assertEqual(record["route"], "alert")
        self.assertFalse(record["rejected"])


if __name__ == "__main__":
    unittest.main()
