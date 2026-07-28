"""Pure URL title fetching, ported verbatim from v1 _fetch_url_title
(QuickNoteBoard.py ~L9391-9478).

No Qt/Tk imports allowed in this module.
"""

import gzip
import html
import re
import urllib.request
import zlib
from urllib.parse import urlparse

from noteboard.core import net

# Same browser-like headers as v1 (L9399-9404)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_title(url, timeout=5):
    """Synchronously fetch the <title> of a URL. Returns title string or None."""
    try:
        original_host = urlparse(url).hostname

        req = urllib.request.Request(url, headers=dict(_HEADERS))
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=net.ssl_context()) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            # Detect auth/login redirects (redirected to a different host with login-like path)
            final_host = urlparse(resp.url).hostname
            final_path = urlparse(resp.url).path.lower()
            is_login_redirect = (
                final_host != original_host and
                any(kw in final_path for kw in ("/login", "/signin", "/auth", "/accounts", "/sso"))
            )

            # Read first 48KB — some sites have large heads (e.g. GitHub > 22KB)
            data = resp.read(49152)

            # Decompress if gzip/deflate encoded (handle truncated streams)
            encoding = resp.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                try:
                    data = gzip.decompress(data)
                except EOFError:
                    # Truncated gzip — use zlib with gzip wrapper flag
                    dec = zlib.decompressobj(zlib.MAX_WBITS | 16)
                    data = dec.decompress(data)
            elif encoding == "deflate":
                try:
                    data = zlib.decompress(data, -zlib.MAX_WBITS)
                except zlib.error:
                    data = zlib.decompress(data)

            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            text = data.decode(charset, errors="replace")

            title = None
            # Try <title> tag first
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if m:
                title = html.unescape(m.group(1)).strip()
                title = re.sub(r"\s+", " ", title)

            # Fallback: og:title or twitter:title meta tags
            if not title:
                m = re.search(
                    r'<meta\s+(?:property|name)=["\'](?:og:title|twitter:title)["\']\s+content=["\']([^"\']+)["\']',
                    text, re.IGNORECASE
                )
                if not m:
                    # Also try content-first order
                    m = re.search(
                        r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\'](?:og:title|twitter:title)["\']',
                        text, re.IGNORECASE
                    )
                if m:
                    title = html.unescape(m.group(1)).strip()
                    title = re.sub(r"\s+", " ", title)

            # If redirected to login page, ignore the login page title
            if is_login_redirect:
                # Use the original domain name as a fallback hint
                domain = original_host.replace("www.", "")
                return domain

            if not title:
                return None

            if len(title) > 50:
                title = title[:50] + "…"
            return title
    except Exception:
        pass
    return None
