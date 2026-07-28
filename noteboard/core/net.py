"""Shared TLS context for stdlib HTTPS calls (no GUI imports).

Frozen (PyInstaller) builds bundle their own OpenSSL, which cannot see the
OS trust store — every https urlopen then fails with
CERTIFICATE_VERIFY_FAILED. certifi ships a CA bundle inside the app, so
prefer it; fall back to the platform defaults when it is missing (source
runs without certifi installed).
"""

import ssl


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
