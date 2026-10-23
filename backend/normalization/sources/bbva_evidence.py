from dataclasses import dataclass
import html
import re
import unicodedata

from bs4 import BeautifulSoup, Comment, NavigableString


BLOCKS = {'address', 'article', 'aside', 'blockquote', 'caption', 'dd', 'details', 'dialog',
          'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'li', 'main', 'nav',
          'ol', 'p', 'pre', 'section', 'summary', 'table', 'tbody', 'tfoot', 'thead', 'tr', 'ul'}
EXAMPLE = re.compile(r'\b(?:(?:por|a\s+modo\s+de)\s+)?ejemplos?\b', re.I)
HEADING = re.compile(r'\b(?:condiciones(?:\s+generales|\s+de\s+la\s+promoci[oó]n)?|bases(?:\s+y\s+condiciones)?)\s*:', re.I)
CAP_MENTION = re.compile(r'\btopes?\b', re.I)
PAIRS = {'(': ')', '[': ']', '{': '}', '«': '»', '“': '”', '‘': '’', '"': '"', "'": "'"}
CAP_TOKENS = re.compile(r'\d+(?:[.,]\d+)*|[^\W\d_]+|[^\w\s]', re.UNICODE)
CURRENCIES = {('ars',): 'ARS', ('$',): 'ARS', ('peso',): 'ARS', ('pesos',): 'ARS',
              ('peso', 'argentino'): 'ARS', ('pesos', 'argentinos'): 'ARS', ('ar', '$'): 'ARS',
              ('usd',): 'USD', ('us', '$'): 'USD', ('u', '$', 's'): 'USD',
              ('dolares', 'estadounidenses'): 'USD', ('eur',): 'EUR', ('€',): 'EUR', ('euros',): 'EUR'}


def cap_tokens(text):
    return [(match.group(), match.start(), match.end()) for match in CAP_TOKENS.finditer(text)]


def token_word(value):
    return ''.join(character for character in unicodedata.normalize('NFD', value.lower())
                   if not unicodedata.combining(character))


def currency_at(tokens, index):
    for size in (3, 2, 1):
        key = tuple(token_word(value) for value, _, _ in tokens[index:index + size])
        if len(key) == size and key in CURRENCIES:
            if (size == 1 and key[0] in {'peso', 'pesos'} and index + 1 < len(tokens)
                    and tokens[index + 1][0].isalpha()
                    and token_word(tokens[index + 1][0]) not in {'por', 'de', 'del', 'y', 'o', 'para', 'en', 'con', 'sin', 'hasta', 'a'}):
                return None, 0
            return CURRENCIES[key], size
    return None, 0


@dataclass(frozen=True)
class LegalClause:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class LegalEvidence:
    text: str
    elements: tuple
    clauses: tuple[LegalClause, ...]

    def cap_mentions(self):
        ranges = clause_ranges(self.text, split_cells=False, split_lines=False)
        enclosures, _ = delimiter_spans(self.text)
        mentions = []
        for match in CAP_MENTION.finditer(self.text):
            roles = [clause for clause in self.clauses if clause.start <= match.start() < clause.end]
            role = next((clause for clause in roles if clause.kind == 'ambiguous'), roles[0] if roles else None)
            kind = role.kind if role else 'ambiguous'
            start, end = next(((left, right) for left, right in ranges if left <= match.start() < right), (match.start(), match.end()))
            if role and kind != 'contractual':
                start, end = role.start, role.end
            elif kind == 'contractual':
                end = min([end] + [right - 1 for left, right in enclosures if left < match.start() < right])
            mentions.append({'start': match.start(), 'label_end': match.end(), 'fragment_start': start,
                             'fragment_end': end, 'classification': kind,
                             'original_fragment': self.text[start:end]})
        return mentions

    def contractual_text(self):
        if any(clause.kind == 'ambiguous' for clause in self.clauses):
            raise ValueError('BBVA unresolved example boundary; monetary cap review required')
        projected = list(self.text)
        for clause in self.clauses:
            if clause.kind == 'example':
                projected[clause.start:clause.end] = [character if character in '\n\t' else ' '
                                                     for character in self.text[clause.start:clause.end]]
                projected[clause.start] = ';'
        return ''.join(projected)


def project_html(value):
    soup = BeautifulSoup(html.unescape(str(value or '')), 'html.parser')
    fragments, elements = [], []
    offset = 0

    def append(text):
        nonlocal offset
        fragments.append(text)
        offset += len(text)

    def visit(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            append(re.sub(r'[\r\u2028\u2029]', '\n', str(node).replace('\r\n', '\n')))
            return
        if node.name in {'script', 'style', 'template'}:
            return
        boundary = '\n' if node.name in BLOCKS or node.name in {'br', 'hr'} else '\t' if node.name in {'td', 'th'} else ''
        append(boundary)
        start = offset
        for child in node.children:
            visit(child)
        elements.append((start, offset, node.name))
        append(boundary)

    visit(soup)
    return ''.join(fragments), tuple(elements)


def delimiter_spans(text):
    stack, spans = [], []
    for index, character in enumerate(text):
        if index and text[index - 1] == '\\':
            continue
        if character == "'" and index and index + 1 < len(text) and text[index - 1].isalnum() and text[index + 1].isalnum():
            continue
        if stack and character == PAIRS[text[stack[-1]]]:
            spans.append((stack.pop(), index + 1))
        elif character in PAIRS:
            if character in {'"', "'"} and index and text[index - 1].isalnum():
                continue
            stack.append(index)
    return spans, stack


def clause_ranges(text, *, split_cells=True, split_lines=True):
    spans, _ = delimiter_spans(text)
    protected = dict(spans)
    ranges, start, index = [], 0, 0
    while index < len(text):
        enclosure = protected.get(index)
        if enclosure is not None:
            index = enclosure
            continue
        character = text[index]
        number_dot = character == '.' and index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit()
        boundary = ((character in '.!?;' and not number_dot)
                    or (split_lines and character == '\n') or (split_cells and character == '\t'))
        if boundary:
            if text[start:index].strip():
                ranges.append((start, index))
            start = index + 1
        index += 1
    if text[start:].strip():
        ranges.append((start, len(text)))
    return ranges


def parse_legal_evidence(value):
    text, elements = project_html(value)
    delimiters, unclosed = delimiter_spans(text)
    examples = sorted((left, right) for left, right in delimiters
                      if EXAMPLE.match(text[left + 1:right - 1].lstrip()))
    examples = [(left, right) for left, right in examples
                if not any(outer_left < left and right < outer_right for outer_left, outer_right in examples)]
    clauses = []
    for left in unclosed:
        if EXAMPLE.match(text[left + 1:].lstrip()) and re.search(r'\btope\b|\d\s*%', text[left:], re.I):
            clauses.append(LegalClause(left, len(text), 'ambiguous'))
    stops = sorted({0, len(text), *(position for bounds in examples for position in bounds)})
    for start, end in zip(stops, stops[1:]):
        if any(left <= start and end <= right for left, right in examples):
            clauses.append(LegalClause(start, end, 'example'))
            continue
        for left, right in clause_ranges(text[start:end]):
            left, right = start + left, start + right
            headings = [match.start() + left for match in HEADING.finditer(text[left:right]) if match.start()]
            boundaries = [left, *headings, right]
            for beginning, ending in zip(boundaries, boundaries[1:]):
                marker = EXAMPLE.search(text[beginning:ending])
                if marker is None:
                    clauses.append(LegalClause(beginning, ending, 'contractual'))
                    continue
                marker_start = beginning + marker.start()
                marker_end = beginning + marker.end()
                if text[beginning:marker_start].strip():
                    clauses.append(LegalClause(beginning, marker_start, 'contractual'))
                body = text[marker_end:ending].strip(' \t\n:,.')
                cap_count = len(re.findall(r'\btope\b', body, re.I))
                later_cap = re.search(r'\btope\b', text[ending:], re.I)
                secondary_label = cap_count > 0 and any(
                    re.search(r'[$%]|\b(?:ARS|USD)\b', body[:index], re.I)
                    or re.match(r'\s*tope\b', body[index + 1:], re.I)
                    for index, character in enumerate(body) if character == ':')
                ambiguous = cap_count > 1 or secondary_label or (not body and later_cap)
                clauses.append(LegalClause(marker_start, ending, 'ambiguous' if ambiguous else 'example'))
    return LegalEvidence(text, elements, tuple(sorted(clauses, key=lambda clause: clause.start)))
