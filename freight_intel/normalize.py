"""Persian text normalization used before every match, hash and comparison."""
from __future__ import annotations

import re
import unicodedata

try:  # hazm is optional; the local map covers everything matching needs
    from hazm import Normalizer as _HazmNormalizer
    _HAZM = _HazmNormalizer()
except Exception:  # pragma: no cover
    _HAZM = None

_MAP = {
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و", "٫": ".", "٬": ",", "ـ": "",
}
for _i in range(10):
    _MAP[chr(0x06F0 + _i)] = str(_i)  # Persian digits
    _MAP[chr(0x0660 + _i)] = str(_i)  # Arabic-Indic digits
_TRANS = str.maketrans(_MAP)
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")
_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_SPACES = re.compile(r"[ \t\u00a0]+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str | None, for_matching: bool = True) -> str:
    """Unify characters and digits. With for_matching, ZWNJ becomes a space so
    regexes written with \\s* match both «پلی‌اتیلن» and «پلی اتیلن»."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    if _HAZM is not None:
        try:
            t = _HAZM.normalize(t)
        except Exception:  # pragma: no cover
            pass
    t = t.translate(_TRANS)
    t = _DIACRITICS.sub("", t)
    t = _BIDI.sub("", t)
    if for_matching:
        t = t.replace("\u200c", " ")
    lines = [_SPACES.sub(" ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def normalize_key(text: str | None) -> str:
    """Lower-cased, punctuation-free single-line key for hashing and lookups."""
    t = normalize(text).lower()
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t.replace("\n", " ")).strip()
