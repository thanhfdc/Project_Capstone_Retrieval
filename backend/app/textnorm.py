"""Vietnamese text normalisation shared by import, entity linking and search.

`norm` keeps diacritics (lowercase, NFC, single spaces); `fold` removes them so that
"Phạm Nhật Vượng" and "pham nhat vuong" match the same alias.
"""
import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def norm(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).lower()
    text = _PUNCT.sub(" ", text).replace("_", " ")
    return _SPACES.sub(" ", text).strip()


def cased_tokens(text: str | None) -> list[str]:
    """The words of `norm(text)` with their case kept: "Jack Ma" -> ["Jack", "Ma"]."""
    if not text:
        return []
    text = _PUNCT.sub(" ", unicodedata.normalize("NFC", text)).replace("_", " ")
    return text.split()


def fold(text: str | None) -> str:
    text = norm(text).replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


_OLD_TONE_PLACE = re.compile(r"(?<!q)([ou])([aey])([\u0300\u0301\u0303\u0309\u0323])(?=\s|$)")


def tone_style(text: str) -> str:
    """One placement of the tone mark: "hoà" and "hòa", "thuỷ" and "thủy" are the same word written in the
    old and new style. Moves the mark of a final "oa", "oe", "uy" to its first vowel ("quý" keeps it)."""
    return unicodedata.normalize("NFC", _OLD_TONE_PLACE.sub(r"\1\3\2", unicodedata.normalize("NFD", text)))


def tokens(text: str | None) -> list[str]:
    folded = fold(text)
    return folded.split() if folded else []
