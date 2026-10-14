import re
import unicodedata


def normalize(name: str) -> str:
    """Forma normalizada para match de aliases: sem acentos, minúsculas, espaços simples."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s-]", " ", s)
    return " ".join(s.split())
