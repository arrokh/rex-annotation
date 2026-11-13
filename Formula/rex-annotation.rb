# Rex Annotation: generated from the checksummed GitHub release.
class RexAnnotation < Formula
  desc "Keyboard-first coding-agent reply annotations for Rex"
  homepage "https://github.com/arrokh/rex-annotation"
  url "https://github.com/arrokh/rex-annotation/releases/download/v0.1.9/rex-annotation-0.1.9.tar.gz"
  version "0.1.9"
  revision 1
  sha256 "114fb1d0eec1c62d127aeaee1ba7bf465f0ab4dae68e2fbd66ca1c5b6569b170"
  license "MIT"

  depends_on :macos
  depends_on "neovim"
  depends_on "python@3.14"

  def install
    libexec.install Dir["*"], ".claude-plugin"
    # Populate prefix metadata so Homebrew does not move the libexec copies.
    ["README.md", "CHANGELOG.md", "LICENSE"].each do |name|
      cp libexec/name, prefix/name
    end
    (bin/"rex-annotation").write <<~SH
      #!/bin/sh
      export REX_ANNOTATION_ROOT="#{opt_libexec}"
      exec "#{Formula["python@3.14"].opt_bin}/python3.14" "#{opt_libexec}/bin/rex-annotation" "$@"
    SH
    chmod 0755, bin/"rex-annotation"
  end

  def caveats
    <<~EOS
      Automatically configure Rex and detected Pi/Codex/Claude/CUX:
        rex-annotation install
        rex-annotation status
      Setup trusts only its own Codex hooks and never reloads coding agents.
      No user configuration is changed by brew install itself.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/rex-annotation --version")
    assert_match "status", shell_output("#{bin}/rex-annotation --help")
    assert_path_exists libexec/"README.md"
    assert_path_exists libexec/"CHANGELOG.md"
    assert_path_exists libexec/"LICENSE"
    ENV["PYTHONDONTWRITEBYTECODE"] = "1"
    system Formula["python@3.14"].opt_bin/"python3.14", "-m", "unittest", "discover",
           "-s", libexec/"tests", "-p", "test_docs_navigation.py"
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
    system bin/"rex-annotation", "install", "--rex", "--reload-rex"
    assert_path_exists testpath/"config/rex/rex-annotation.lua"
    report = JSON.parse(shell_output("#{bin}/rex-annotation status --json"))
    assert_empty report.fetch("checks").select { |check| check.fetch("status") == "fail" }
  end
end
