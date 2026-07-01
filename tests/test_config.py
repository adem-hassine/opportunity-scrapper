import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from openclaw.models.domain import RemoteMode
from openclaw.core.config import Settings, _load_simple_yaml_mapping, load_job_criteria


class ConfigTests(unittest.TestCase):
    def test_load_job_criteria_from_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "job_criteria.yml"
            criteria_file.write_text(
                "\n".join(
                    [
                        "platform_targets:",
                        "  - free-work",
                        "  - malt",
                        "employment_type:",
                        "  - freelance",
                        "  - cdi",
                        "freelance_criteria:",
                        "  minimum_tjm: 700",
                        "  unspecified_tjm: false",
                        "  minimum_duration_months: 12",
                        "cdd_cdi_criteria:",
                        "  minimum_year_salary: 95000",
                        "allowed_remote_modes:",
                        "  - hybrid",
                        "  - full remote",
                        "  - onsite",
                        "excluded_keywords:",
                        "  - php",
                        "required_keywords:",
                        "  - java",
                        "  - spring",
                    ]
                ),
                encoding="utf-8",
            )

            criteria = load_job_criteria(criteria_file)

            self.assertEqual(criteria.platform_targets, ["free-work", "malt"])
            self.assertEqual(criteria.employment_type, ["freelance", "cdi"])
            self.assertIsNotNone(criteria.freelance_criteria)
            self.assertIsNotNone(criteria.cdd_cdi_criteria)
            self.assertEqual(criteria.freelance_criteria.minimum_tjm, 700)
            self.assertFalse(criteria.freelance_criteria.unspecified_tjm)
            self.assertEqual(criteria.freelance_criteria.minimum_duration_months, 12)
            self.assertEqual(criteria.cdd_cdi_criteria.minimum_year_salary, 95000)
            self.assertEqual(
                criteria.allowed_remote_modes,
                [RemoteMode.HYBRID, RemoteMode.REMOTE, RemoteMode.ONSITE],
            )
            self.assertEqual(criteria.excluded_keywords, ["php"])
            self.assertEqual(criteria.required_keywords, ["java", "spring"])

    def test_settings_reads_job_criteria_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "criteria.yml"
            criteria_file.write_text(
                "\n".join(
                    [
                        "platform_targets:",
                        "  - lehibou",
                        "employment_type:",
                        "  - cdi",
                        "cdd_cdi_criteria:",
                        "  minimum_year_salary: 100000",
                        "allowed_remote_modes:",
                        "  - onsite",
                        "excluded_keywords:",
                        "  - wordpress",
                        "required_keywords:",
                        "  - keycloak",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings(_env_file=None, job_criteria_file=str(criteria_file))

            self.assertEqual(settings.platform_targets, ["lehibou"])
            self.assertEqual(settings.employment_type, ["cdi"])
            self.assertEqual(settings.minimum_tjm, 0)
            self.assertFalse(settings.unspecified_tjm)
            self.assertEqual(settings.minimum_duration_months, 0)
            self.assertEqual(settings.minimum_year_salary, 100000)
            self.assertEqual(settings.allowed_remote_modes, [RemoteMode.ONSITE])
            self.assertEqual(settings.required_keywords, ["keycloak"])

    def test_simple_yaml_parser_supports_comments_and_lists(self) -> None:
        parsed = _load_simple_yaml_mapping(
            "\n".join(
                [
                    "# criteria file",
                    "platform_targets:",
                    "  - free-work",
                    "  - malt",
                    "minimum_tjm: 650",
                    "allowed_remote_modes:",
                    "  - hybrid",
                    "  - full remote",
                    "excluded_keywords:",
                    "  - php",
                ]
            )
        )

        self.assertEqual(parsed["platform_targets"], ["free-work", "malt"])
        self.assertEqual(parsed["minimum_tjm"], 650)
        self.assertEqual(parsed["allowed_remote_modes"], ["hybrid", "full remote"])
        self.assertEqual(parsed["excluded_keywords"], ["php"])

    def test_load_job_criteria_splits_commas_inside_list_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "job_criteria.yml"
            criteria_file.write_text(
                "\n".join(
                    [
                        "employment_type:",
                        "  - freelance",
                        "freelance_criteria:",
                        "  minimum_tjm: 650",
                        "  unspecified_tjm: true",
                        "  minimum_duration_months: 6",
                        "required_keywords:",
                        "  - java, keycloak",
                        "  - spring boot",
                    ]
                ),
                encoding="utf-8",
            )

            criteria = load_job_criteria(criteria_file)

            self.assertEqual(criteria.required_keywords, ["java", "keycloak", "spring boot"])

    def test_load_job_criteria_requires_criteria_for_enabled_employment_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "job_criteria.yml"
            criteria_file.write_text(
                "\n".join(
                    [
                        "employment_type:",
                        "  - freelance",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError):
                load_job_criteria(criteria_file)

    def test_blank_telegram_allowed_user_ids_in_env_becomes_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "criteria.yml"
            env_file = Path(tmpdir) / ".env"
            criteria_file.write_text(
                "\n".join(
                    [
                        "platform_targets:",
                        "  - free-work",
                        "employment_type:",
                        "  - freelance",
                        "freelance_criteria:",
                        "  minimum_tjm: 650",
                        "  unspecified_tjm: true",
                        "  minimum_duration_months: 6",
                    ]
                ),
                encoding="utf-8",
            )
            env_file.write_text(
                "\n".join(
                    [
                        f"JOB_CRITERIA_FILE={criteria_file}",
                        "TELEGRAM_ALLOWED_USER_IDS=",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings(_env_file=env_file)

            self.assertEqual(settings.telegram_allowed_user_ids, [])


if __name__ == "__main__":
    unittest.main()
