import tempfile
import unittest
from pathlib import Path

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
                        "minimum_tjm: 700",
                        "remote_required: true",
                        "excluded_keywords:",
                        "  - php",
                        "required_keywords:",
                        "  - java",
                        "  - spring",
                        "auto_reject_score_below: 50",
                        "alert_score_from: 80",
                    ]
                ),
                encoding="utf-8",
            )

            criteria = load_job_criteria(criteria_file)

            self.assertEqual(criteria.platform_targets, ["free-work", "malt"])
            self.assertEqual(criteria.minimum_tjm, 700)
            self.assertTrue(criteria.remote_required)
            self.assertEqual(criteria.excluded_keywords, ["php"])
            self.assertEqual(criteria.required_keywords, ["java", "spring"])
            self.assertEqual(criteria.auto_reject_score_below, 50)
            self.assertEqual(criteria.alert_score_from, 80)

    def test_settings_reads_job_criteria_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "criteria.yml"
            criteria_file.write_text(
                "\n".join(
                    [
                        "platform_targets:",
                        "  - lehibou",
                        "minimum_tjm: 725",
                        "remote_required: false",
                        "excluded_keywords:",
                        "  - wordpress",
                        "required_keywords:",
                        "  - keycloak",
                        "auto_reject_score_below: 40",
                        "alert_score_from: 70",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings(_env_file=None, job_criteria_file=str(criteria_file))

            self.assertEqual(settings.platform_targets, ["lehibou"])
            self.assertEqual(settings.minimum_tjm, 725)
            self.assertFalse(settings.remote_required)
            self.assertEqual(settings.required_keywords, ["keycloak"])
            self.assertEqual(settings.auto_reject_score_below, 40)
            self.assertEqual(settings.alert_score_from, 70)

    def test_simple_yaml_parser_supports_comments_and_lists(self) -> None:
        parsed = _load_simple_yaml_mapping(
            "\n".join(
                [
                    "# criteria file",
                    "platform_targets:",
                    "  - free-work",
                    "  - malt",
                    "minimum_tjm: 650",
                    "remote_required: true",
                    "excluded_keywords:",
                    "  - php",
                ]
            )
        )

        self.assertEqual(parsed["platform_targets"], ["free-work", "malt"])
        self.assertEqual(parsed["minimum_tjm"], 650)
        self.assertIs(parsed["remote_required"], True)
        self.assertEqual(parsed["excluded_keywords"], ["php"])

    def test_blank_telegram_allowed_user_ids_in_env_becomes_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            criteria_file = Path(tmpdir) / "criteria.yml"
            env_file = Path(tmpdir) / ".env"
            criteria_file.write_text("platform_targets:\n  - free-work\n", encoding="utf-8")
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
