"""Happ crypto-link (``happ://crypt4/``) generation.

Happ encrypts subscription links with its own RSA-4096 public key (version 4)
using PKCS#1 v1.5 padding. Only the Happ client (and Happ-compatible forks that
embed the matching private key) can decrypt them, which hides the real
subscription address from the user and prevents server/config sharing.

RSA public-key encryption is just ``pow(m, e, n)``, so this is implemented with
the standard library alone — no third-party crypto dependency.

Reference for the format and the public key: the @kastov/cryptohapp library and
https://www.happ.su/main/dev-docs/crypto-link
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

DEEP_LINK_PREFIX = "happ://crypt4/"

# Happ public key, version 4 (PEM SubjectPublicKeyInfo, RSA-4096).
_HAPP_PUBLIC_KEY_V4_PEM = """
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA3UZ0M3L4K+WjM3vkbQnz
ozHg/cRbEXvQ6i4A8RVN4OM3rK9kU01FdjyoIgywve8OEKsFnVwERZAQZ1Trv60B
hmaM76QQEE+EUlIOL9EpwKWGtTL5lYC1sT9XJMNP3/CI0gP5wwQI88cY/xedpOEB
W72EmOOShHUm/b/3m+HPmqwc4ugKj5zWV5SyiT829aFA5DxSjmIIFBAms7DafmSq
LFTYIQL5cShDY2u+/sqyAw9yZIOoqW2TFIgIHhLPWek/ocDU7zyOrlu1E0SmcQQb
LFqHq02fsnH6IcqTv3N5Adb/CkZDDQ6HvQVBmqbKZKf7ZdXkqsc/Zw27xhG7OfXC
tUmWsiL7zA+KoTd3avyOh93Q9ju4UQsHthL3Gs4vECYOCS9dsXXSHEY/1ngU/hjO
WFF8QEE/rYV6nA4PTyUvo5RsctSQL/9DJX7XNh3zngvif8LsCN2MPvx6X+zLouBX
zgBkQ9DFfZAGLWf9TR7KVjZC/3NsuUCDoAOcpmN8pENBbeB0puiKMMWSvll36+2M
YR1Xs0MgT8Y9TwhE2+TnnTJOhzmHi/BxiUlY/w2E0s4ax9GHAmX0wyF4zeV7kDkc
vHuEdc0d7vDmdw0oqCqWj0Xwq86HfORu6tm1A8uRATjb4SzjTKclKuoElVAVa5Jo
oh/uZMozC65SmDw+N5p6Su8CAwEAAQ==
-----END PUBLIC KEY-----
"""


class _DER:
    """Minimal DER reader: returns ``(tag, body)`` for the next TLV element."""

    def __init__(self, data: bytes) -> None:
        self.d = data
        self.i = 0

    def read(self) -> tuple[int, bytes]:
        tag = self.d[self.i]
        self.i += 1
        length = self.d[self.i]
        self.i += 1
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(self.d[self.i : self.i + n], "big")
            self.i += n
        body = self.d[self.i : self.i + length]
        self.i += length
        return tag, body


def _parse_spki_rsa(pem: str) -> tuple[int, int]:
    """Extract ``(n, e)`` from a PEM RSA SubjectPublicKeyInfo."""
    b64 = "".join(s.strip() for s in pem.splitlines() if "-----" not in s)
    _, seq = _DER(base64.b64decode(b64)).read()  # outer SEQUENCE body
    inner = _DER(seq)
    inner.read()                                 # AlgorithmIdentifier (skip)
    _, bitstr = inner.read()                     # BIT STRING
    _, pub = _DER(bitstr[1:]).read()             # RSAPublicKey SEQUENCE body
    nums = _DER(pub)
    _, n_b = nums.read()
    _, e_b = nums.read()
    return int.from_bytes(n_b, "big"), int.from_bytes(e_b, "big")


_N, _E = _parse_spki_rsa(_HAPP_PUBLIC_KEY_V4_PEM)
_K = (_N.bit_length() + 7) // 8          # modulus size in bytes (512)
MAX_CONTENT = _K - 11                     # PKCS#1 v1.5 plaintext limit


def _rsa_pkcs1v15_encrypt(msg: bytes) -> bytes:
    if len(msg) > MAX_CONTENT:
        raise ValueError(f"content too long for crypt4: {len(msg)} > {MAX_CONTENT}")
    ps_len = _K - 3 - len(msg)
    ps = bytearray()
    while len(ps) < ps_len:  # PS: non-zero random padding
        for b in os.urandom(ps_len - len(ps)):
            if b != 0:
                ps.append(b)
    em = b"\x00\x02" + bytes(ps[:ps_len]) + b"\x00" + msg
    c = pow(int.from_bytes(em, "big"), _E, _N)
    return c.to_bytes(_K, "big")


def to_crypt_link(content: str) -> str:
    """Encrypt ``content`` (a subscription URL) into a ``happ://crypt4/`` link."""
    ct = _rsa_pkcs1v15_encrypt(content.encode("utf-8"))
    return DEEP_LINK_PREFIX + base64.b64encode(ct).decode("ascii")


def format_for_user(url: str | None) -> str | None:
    """Subscription link as handed to the user — a Happ crypt link.

    Falls back to the raw URL only if encryption unexpectedly fails, so the user
    never receives an empty/broken link.
    """
    if not url:
        return url
    try:
        return to_crypt_link(url)
    except Exception:  # noqa: BLE001 - never hand out nothing
        logger.exception("Failed to build happ crypt link; using raw URL")
        return url
