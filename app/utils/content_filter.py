"""Forbidden-content filter for user-provided text (names / usernames).

Goal: a name that references child sexual abuse (or similarly bannable content)
must never be stored, shown in the dashboard, forwarded to the payment provider,
or echoed into a Telegram message — Telegram can ban a bot that emits it.

This is a deliberately conservative heuristic, not a perfect classifier: it
normalises away common obfuscation (leet-speak, spacing, punctuation) and then
looks for high-confidence tokens plus "minor + sexual" combinations. Extend the
lists below as needed.
"""
import re
import unicodedata

# Map common leet substitutions back to letters so "ch1ld p0rn" is caught.
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "6": "g", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s",
})


def _normalize(text: str) -> str:
    """Lowercase, de-leet, and strip everything but latin/cyrillic letters so
    spacing/punctuation obfuscation ("c.h.i.l.d", "k i d") collapses."""
    t = unicodedata.normalize("NFKC", text).lower().translate(_LEET)
    return re.sub(r"[^a-zа-яё]", "", t)


# Single tokens that are damning on their own (already unambiguous).
_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "childporn", "childporno", "kidporn", "kiddieporn", "childsex", "kidsex",
    "pedophil", "pedofil", "paedophil", "pedo", "lolicon", "shotacon", "csam",
    "jailbait", "childabuse", "childrape", "rapechild", "infantporn", "toddlercon",
    # Russian
    "детскоепорно", "детскоепорн", "детскийсекс", "детскоесекс", "педофил", "педо",
    "малолетнийсекс", "малолеткапорно", "порнодети", "порнодетей", "сексдети",
    "сексдетьми", "растлен", "педофилия",
)

# "pedo"/"педо" are strong on their own but ride inside a few benign words —
# don't flag those.
_PEDO_BENIGN = ("torpedo", "speedo", "expedo", "empedo", "cupedo", "педометр")

# "minor" indicators × "sexual" indicators — flagged only when BOTH appear, which
# keeps innocent words ("childhood", "essex") from matching.
_MINOR: tuple[str, ...] = (
    "child", "children", "kid", "minor", "underage", "preteen", "infant",
    "toddler", "loli", "shota", "newborn",
    "детск", "ребенок", "ребёнок", "детей", "детьми", "малолет", "несовершеннолет",
    "младенец", "школьниц", "подрост",
)
_SEXUAL: tuple[str, ...] = (
    "porn", "porno", "sex", "nude", "naked", "xxx", "rape", "hentai", "erotic",
    "fuck", "molest", "incest",
    "порно", "порн", "секс", "голая", "голые", "эротик", "изнасил", "растли",
    "ебля", "трах", "инцест",
)


def is_forbidden(text: str | None) -> bool:
    """True if ``text`` references clearly bannable (CSAM-adjacent) content."""
    if not text:
        return False
    norm = _normalize(text)
    if not norm:
        return False
    for tok in _FORBIDDEN_TOKENS:
        if tok not in norm:
            continue
        # "pedo"/"педо" inside torpedo/speedo/… is not a hit.
        if tok in ("pedo", "педо") and any(b in norm for b in _PEDO_BENIGN):
            continue
        return True
    if any(m in norm for m in _MINOR) and any(s in norm for s in _SEXUAL):
        return True
    return False
