#!/usr/bin/env python3
"""Create a checksummed local Homebrew source package; never publish or install it."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
# Package only project resources; never include .git, local state, or arbitrary files.
# Formula/ refers to an already-published archive; exclude it to avoid a self-hash cycle.
RESOURCES = ("README.md", "LICENSE", "CHANGELOG.md", "package.json", "bin", "rex", "scripts", "integrations", "hooks", ".claude-plugin", "tests", "docs")


def ruby_string(value):
    # Escape interpolation as well as ordinary Ruby double-quoted string escapes.
    return json.dumps(str(value), ensure_ascii=False).replace("#{", "\\#{")


def formula_for(archive, digest, version, source_url=None):
    if source_url is not None and source_url != f"https://github.com/arrokh/rex-annotation/releases/download/v{version}/rex-annotation-{version}.tar.gz":
        raise ValueError("Public formula source must be the matching GitHub release asset")
    header = "# Rex Annotation: generated from the checksummed GitHub release." if source_url else "# Generated local-development formula. No remote publication is implied."
    return header + '''
class RexAnnotation < Formula
  desc "Keyboard-first coding-agent reply annotations for Rex"
  homepage "https://github.com/arrokh/rex-annotation"
  url %s
  version %s
  sha256 %s
  license "MIT"

  depends_on :macos
  depends_on "neovim"
  depends_on "python@3.14"

  def install
    libexec.install Dir["*"], ".claude-plugin"
    (bin/"rex-annotation").write <<~SH
      #!/bin/sh
      export REX_ANNOTATION_ROOT="#{opt_libexec}"
      exec "#{Formula["python@3.14"].opt_bin}/python3.14" "#{opt_libexec}/bin/rex-annotation" "$@"
    SH
    chmod 0755, bin/"rex-annotation"
  end

  def caveats
    <<~EOS
      Configure your user environment explicitly:
        rex-annotation install
        rex-annotation status
      Optional agents:
        rex-annotation install --all
      No user configuration is changed by brew install itself.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/rex-annotation --version")
    assert_match "status", shell_output("#{bin}/rex-annotation --help")
    (testpath/"fake-bin/rex").write <<~SH
      #!/bin/sh
      case "$*" in
        *actions*) echo '{"actions":[{"name":"annotate_open"}]}' ;;
        *) echo ok ;;
      esac
    SH
    chmod 0755, testpath/"fake-bin/rex"
    ENV.prepend_path "PATH", testpath/"fake-bin"
    ENV["XDG_CONFIG_HOME"] = (testpath/"config").to_s
    system bin/"rex-annotation", "install", "--reload-rex"
    assert_path_exists testpath/"config/rex/rex-annotation.lua"
    report = JSON.parse(shell_output("#{bin}/rex-annotation status --json"))
    assert_empty report.fetch("checks").select { |check| check.fetch("status") == "fail" }
  end
end
''' % (ruby_string(source_url or archive.as_uri()), ruby_string(version), ruby_string(digest))


def build(output, source_url=None):
    version = json.loads((ROOT / "package.json").read_text())["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?", version):
        raise ValueError("Invalid package version")
    files_result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=10)
    if files_result.returncode:
        raise ValueError("Build release packages from a Git checkout so .gitignore is respected")
    files = []
    for name in files_result.stdout.split("\0"):
        if not name:
            continue
        relative = Path(name)
        if relative.parts[0] not in RESOURCES:
            continue
        source = ROOT / relative
        if source.is_symlink():
            raise ValueError("Refusing to package a source symlink: " + name)
        if source.is_file():
            files.append(source)
    output = output.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ("rex-annotation-" + version + ".tar.gz")
    top = "rex-annotation-" + version
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for source in sorted(files):
                    relative = source.relative_to(ROOT)
                    if "__pycache__" in relative.parts or source.suffix in (".pyc", ".pyo"):
                        continue
                    if source.is_symlink():
                        raise ValueError("Refusing to package a source symlink: " + str(relative))
                    content = source.read_bytes()
                    entry = tarfile.TarInfo(top + "/" + relative.as_posix())
                    entry.size = len(content)
                    entry.mtime = entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    entry.mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
                    tar.addfile(entry, io.BytesIO(content))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    formula = output / "rex-annotation.rb"
    formula.write_text(formula_for(archive, digest, version, source_url))
    return archive, formula, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/homebrew")
    parser.add_argument("--source-url", help="matching public GitHub release asset URL for a publishable formula")
    args = parser.parse_args()
    try:
        archive, formula, digest = build(args.output, args.source_url)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print("Archive: " + str(archive))
    print("SHA256:  " + digest)
    print("Formula: " + str(formula))
    print("See docs/homebrew.md for release/tap instructions." if args.source_url else "Local package only. See docs/homebrew.md for installing it into a local tap.")


if __name__ == "__main__":
    main()
