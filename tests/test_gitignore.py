from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class GitignoreTests(unittest.TestCase):
    def test_generated_private_state_is_ignored_and_release_source_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
            (repo/'.gitignore').write_text((ROOT/'.gitignore').read_text())
            ignored = ['dist/release.tar.gz', 'build/output', 'node_modules/pkg/index.js', 'scripts/__pycache__/x.pyc',
                       '.venv/bin/python', 'test.log', '.pi/sessions/session.jsonl', '.codex/auth.json', '.claude/settings.json',
                       'sessions/private.jsonl', 'state/binding.json', '.env', '.env.local', 'private.key', 'auth.json',
                       'credentials.json', 'secrets.json', '.DS_Store']
            kept = ['LICENSE', 'README.md', 'package.json', 'bin/rex-annotation', '.github/workflows/ci.yml',
                    '.claude-plugin/plugin.json', 'hooks/hooks.json', 'rex/annotate.lua', '.env.example',
                    'integrations/codex/skills/rex-annotation/SKILL.md', 'integrations/pi/extensions/index.js',
                    'integrations/tests/fixtures/codex_session.jsonl', 'integrations/tests/fixtures/claude_session.jsonl']
            for path in ignored + kept:
                with self.subTest(path=path):
                    result = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--no-index', path], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0 if path in ignored else 1, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
