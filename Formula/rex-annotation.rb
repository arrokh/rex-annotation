# Rex Annotation: generated from the checksummed GitHub release.
class RexAnnotation < Formula
  desc "Keyboard-first coding-agent reply annotations for Rex"
  homepage "https://github.com/arrokh/rex-annotation"
  url "https://github.com/arrokh/rex-annotation/releases/download/v0.1.8/rex-annotation-0.1.8.tar.gz"
  version "0.1.8"
  sha256 "3cdb2da52874cb10fb7846a45edade0544bd38c256eb079dcf3041eab61645d5"
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
