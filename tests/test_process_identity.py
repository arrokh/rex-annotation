import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(sys.platform == "darwin", "macOS native process identity")
class MacProcessIdentityTests(unittest.TestCase):
    def test_process_identity_works_inside_network_denied_sandbox_without_ps(self):
        script = ("import os,sys;sys.dont_write_bytecode=True;sys.path.insert(0," + repr(str(ROOT/'integrations')) + ");"
                  "import session_replies as r;first=r._process_start_identity(os.getpid());"
                  "assert first==r._process_start_identity(os.getpid());print(first)")
        result = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)", sys.executable, "-I", "-c", script],
                                capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^darwin:\d+:\d+$")


if __name__ == "__main__":
    unittest.main()
