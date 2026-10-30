import re
import unicodedata


def slugify(value: str) -> str:
    """Same rules as the frontend: lowercase, strip accents, non-alphanumerics -> '-'."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def make_excerpt(content: str, length: int = 160) -> str:
    plain = re.sub(r"[#*_`>]", "", content).strip()
    return plain if len(plain) <= length else plain[:length].rstrip() + "…"
