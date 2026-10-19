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


def fold(text: str | None) -> str:
    text = norm(text).replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def tokens(text: str | None) -> list[str]:
    folded = fold(text)
    return folded.split() if folded else []
