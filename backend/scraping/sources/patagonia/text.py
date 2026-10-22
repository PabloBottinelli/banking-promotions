import re
import unicodedata


def legal_header_segments(line: str) -> list[str] | None:
    text = "".join(c for c in unicodedata.normalize("NFKD", line.lower()) if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"(?:terminos y condiciones|legales)\s*[:.]?", text):
        return []
    prefix = re.match(r"^(?:legales\s+)?patagonia\b", text)
    if not prefix:
        return None
    tail = text[prefix.end():]
    remaining = re.sub(r"\b(?:clasica|plus|singular|on|exclusivo|exclusiva|plan|sueldo|sueldos|jubilado|jubilados|y|e)\b", "", tail)
    if re.sub(r"[\s,;/|&+.():\-]+", "", remaining):
        return None
    return [segment for segment in ("clasica", "plus", "singular", "on") if re.search(rf"\b{segment}\b", tail)]


def strip_legal_headers(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        if legal_header_segments(line) is not None:
            continue
        prefix, separator, body = line.partition(":")
        if separator and legal_header_segments(prefix) is not None:
            line = body
        lines.append(line)
    return "\n".join(lines).strip()
