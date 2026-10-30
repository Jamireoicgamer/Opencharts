import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StaticPrototypeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "legacy" / "index.html").read_text(encoding="utf-8")

    def test_document_foundations(self):
        for value in ("<!doctype html>", "<title>", "</html>"):
            self.assertIn(value, self.page.lower())

    def test_no_external_javascript(self):
        self.assertNotRegex(self.page, r"<script[^>]*\bsrc\s*=")

    def test_docker_configuration_present(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        # The web app publishes on 8080 (localhost by default); the legacy
        # prototype stays available behind the "legacy" profile.
        self.assertIn("${OPENCHART_PORT:-8080}:80", compose)
        self.assertIn("${OPENCHART_BIND:-127.0.0.1}", compose)
        self.assertIn("legacy/index.html", compose)

    def test_core_prototype_content(self):
        for term in ("OpenChart", "watchlist", "thesis", "research"):
            self.assertIn(term.lower(), self.page.lower())


if __name__ == "__main__":
    unittest.main()
