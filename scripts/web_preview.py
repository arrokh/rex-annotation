"""Serve only the bundled synthetic web preview over temporary loopback HTTPS."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import signal
import ssl
import subprocess
import sys
import tempfile

SECURITY = "/usr/bin/security"
ASSETS = {"/": ("index.html", "text/html"), "/markdown.js": ("markdown.js", "text/javascript")}


class PreviewServer(ThreadingHTTPServer):
    def __init__(self, assets):
        self.assets = assets
        super().__init__(("127.0.0.1", 0), PreviewHandler)

    def get_request(self):
        connection, peer = super().get_request()
        connection.settimeout(5)
        try:
            return self.context.wrap_socket(connection, server_side=True), peer
        except BaseException:
            connection.close()
            raise


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_port
        if self.headers.get("Host") != f"localhost:{port}":
            self.send_error(400)
            return
        resource = self.server.assets.get(self.path.split("?", 1)[0])
        if resource is None:
            self.send_error(404)
            return
        content_type, content = resource
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)


def _run(*argv):
    result = subprocess.run(argv, timeout=120, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"{Path(argv[0]).name} {argv[1]} failed ({result.returncode}): {detail}")


def run_preview(root, keychain):
    assets = {route: (kind, (root / "rex" / "web-prototype" / name).read_bytes())
              for route, (name, kind) in ASSETS.items()}
    with tempfile.TemporaryDirectory(prefix="rex-annotation-preview-") as directory, PreviewServer(assets) as server:
        cert = Path(directory) / "localhost.crt"
        key = Path(directory) / "localhost.key"
        _run("/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "1",
             "-subj", "/CN=Rex Annotation Preview " + secrets.token_hex(8), "-addext", "subjectAltName=DNS:localhost",
             "-addext", "basicConstraints=critical,CA:FALSE", "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
             "-addext", "extendedKeyUsage=serverAuth", "-keyout", str(key), "-out", str(cert))
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        try:
            _run(SECURITY, "add-trusted-cert", "-r", "trustRoot", "-p", "ssl", "-s", "localhost", "-k", str(keychain), str(cert))
            _run(SECURITY, "verify-cert", "-c", str(cert), "-p", "ssl", "-s", "localhost", "-q")
            server.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.context.load_cert_chain(cert, key)
            url = f"https://localhost:{server.server_port}/"
            print(f"Shift+Cmd-click \033]8;;{url}\033\\{url}\033]8;;\033\\ to preview inside Rex.\n"
                  "Sample replies only. Press Ctrl+C to stop and remove the test certificate.\n"
                  f"Test certificate SHA-256: {fingerprint}", flush=True)
            server.serve_forever()
        finally:
            try:
                _run(SECURITY, "delete-certificate", "-t", "-Z", fingerprint, str(keychain))
            except (OSError, subprocess.SubprocessError):
                print(f"Certificate cleanup not confirmed. Remove this test certificate with:\n"
                      f'  security delete-certificate -t -Z {fingerprint} "{keychain}"', file=sys.stderr)
                raise


def main(argv, root):
    parser = argparse.ArgumentParser(prog="rex-annotation web-preview", description=__doc__)
    parser.add_argument("--trust-local-certificate", action="store_true",
                        help="allow temporary user-keychain trust for an SSL localhost-only test certificate")
    args = parser.parse_args(argv)
    if not args.trust_local_certificate:
        parser.error("preview requires explicit certificate consent: pass --trust-local-certificate")
    if sys.platform != "darwin":
        parser.error("the Rex Quick Look experiment requires macOS")
    keychain = Path.home() / "Library/Keychains/login.keychain-db"
    if not keychain.is_file():
        parser.error("the macOS login keychain was not found")

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop)
    try:
        run_preview(root, keychain)
    except KeyboardInterrupt:
        return 0
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Web preview failed: {error}", file=sys.stderr)
        return 1
    return 0
