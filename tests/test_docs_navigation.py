"""Offline checks for the human-facing documentation map and local links."""
from collections import Counter
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs/README.md"
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\s)]+)\)")


def prose(path):
    # Shell/Lua examples are not Markdown navigation.
    return re.sub(r"^```[^\n]*\n.*?^```[ \t]*$", "", path.read_text(), flags=re.MULTILINE | re.DOTALL)


def links(path):
    for value in LINK.findall(prose(path)):
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            continue
        target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path.resolve()
        yield target, unquote(parsed.fragment)


def anchors(path):
    found, counts = set(), Counter()
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose(path), flags=re.MULTILINE):
        title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        count = counts[slug]
        counts[slug] += 1
        found.add(slug + ("-" + str(count) if count else ""))
    return found


class DocsNavigationTests(unittest.TestCase):
    def guides(self):
        return [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md")),
                ROOT / "integrations/README.md", *sorted((ROOT / "integrations").glob("*/README.md"))]

    def test_local_files_and_heading_links_resolve(self):
        for guide in self.guides():
            for target, fragment in links(guide):
                with self.subTest(guide=str(guide.relative_to(ROOT)), target=str(target), fragment=fragment):
                    self.assertTrue(target.is_relative_to(ROOT), "Documentation link escapes the repository")
                    self.assertTrue(target.exists(), "Documentation target does not exist")
                    if fragment and target.suffix == ".md":
                        self.assertIn(fragment, anchors(target), "Documentation heading does not exist")

    def test_every_guide_has_a_route_back_to_the_documentation_index(self):
        self.assertTrue(INDEX.is_file())
        for guide in self.guides():
            if guide == INDEX:
                continue
            with self.subTest(guide=str(guide.relative_to(ROOT))):
                self.assertIn(INDEX.resolve(), {target for target, _ in links(guide)})

    def test_related_projects_are_linked_from_readme_and_reference_page(self):
        urls = ("https://github.com/plannotator/herdr-annotate",
                "https://github.com/backnotprop/plannotator",
                "https://github.com/plannotator/plannotator-tui")
        for guide in (ROOT / "README.md", ROOT / "docs/related-tools.md"):
            for url in urls:
                with self.subTest(guide=str(guide.relative_to(ROOT)), url=url):
                    self.assertIn(url, guide.read_text())


if __name__ == "__main__":
    unittest.main()
