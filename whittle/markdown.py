# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude's Markdown as lines a Blender panel can draw.

A Blender label has one font, weight and size, so the styling has to live
in the text itself: bold and italic become Unicode's sans-serif bold and
italic letters (𝗯𝗼𝗹𝗱, 𝘪𝘵𝘢𝘭𝘪𝘤), code its monospace letters (𝚌𝚘𝚍𝚎),
which Blender's fallback fonts draw, and the markers go. Struck text gets a
stroke overlay between its letters, footnote references superscript
numbers, link text an underline, and TeX maths its Unicode symbols.
Blocks become Lines: wrapped
text with a hanging indent, a bullet, number or box in the margin, and a
kind the panel styles (a heading by its level, a code line in a box, a
table of cells, a collapsible section, a rule, a gap between paragraphs);
quoted lines carry their depth and are drawn dim.

Pure Python: the width of text comes from the caller's measure, so this
runs (and is tested) without Blender."""

import html
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

Measure = Callable[[str], float]

# Sans-serif bold, italic and bold italic, and monospace: (A, a, 0) code
# points; italic has no digits of its own.
_STYLES = {
    "b": (0x1D5D4, 0x1D5EE, 0x1D7EC),
    "i": (0x1D608, 0x1D622, None),
    "bi": (0x1D63C, 0x1D656, 0x1D7EC),
    "m": (0x1D670, 0x1D68A, 0x1D7F6),
}

BULLETS = ("•", "◦", "▪")
# The letters of a heading by its level: H5 and H6 are also drawn dim.
HEADING_STYLES = {1: ("b",), 2: ("b",), 3: ("b",), 4: ("b",), 5: ("b",), 6: ("i",)}
# Task list boxes, both from Noto Sans Symbols 2: Blender draws ☑ from its
# emoji font, half as wide again as ☐ and too wide for the margin.
TASKS = {" ": "☐", "x": "🗹", "X": "🗹"}

# Indentation per list level and for quotes, in multiples of the width of
# "M" so it follows the UI scale.
INDENT_EMS = 1.4
# What a table cell's label takes from its column besides the text.
CELL_PAD_EMS = 1.2

# Blender draws no combining stroke over a letter (U+0336 is only in its
# monospace font, and a mark after a letter is lifted above it), but a
# mark after a space stays where the font puts it: a hair space and the
# leftwards-arrow overlay between two letters draw a line through them.
STRIKE = "\u200a\u20ea"
# Link text is underlined: U+0332 is only in the monospace font, but Inter
# has U+035F (a double macron below, reaching under the next letter), and
# one after each letter joins into a line under the text.
UNDERLINE = "\u035f"
CODE_SPACE = "\u2002"


@dataclass(frozen=True)
class Table:
    """A table's columns (their widths in pixels, cell padding included,
    and alignments) and rows of cells, each cell its wrapped lines; the
    first row is the header."""

    widths: tuple[float, ...]
    aligns: tuple[str, ...]  # LEFT | CENTER | RIGHT
    rows: tuple[tuple[tuple[str, ...], ...], ...]
    fills: bool = False  # wider than the panel: drawn at its full width

    @property
    def height(self) -> int:
        return sum(max((len(cell) for cell in row), default=1) for row in self.rows)


@dataclass(frozen=True)
class Line:
    """One drawn line: its text starts indent pixels in, and a list item's
    first line has its marker (a bullet, "3." or a task box) in the margin
    before it. quote is how many quotes it is inside, links the (text,
    address) of each link on it. A code block's head carries its language
    as text and the block's code to copy; a table carries its cells, a
    collapsible section its summary as text and its body as Lines."""

    text: str
    kind: str = "text"  # text | heading | codehead | code | math | note | rule | gap | table | details
    indent: float = 0.0
    marker: str = ""
    level: int = 0  # a heading's level, 1 to 6
    quote: int = 0
    links: tuple[tuple[str, str], ...] = ()
    table: Table | None = None
    body: tuple["Line", ...] = ()
    copy: str = ""

    @property
    def link(self) -> str:
        """The address of the first link on it."""
        return self.links[0][1] if self.links else ""

    @property
    def height(self) -> int:
        """Rows of text it takes (a section counts closed)."""
        return self.table.height if self.table is not None else 1


def styled(text: str, style: str) -> str:
    upper, lower, digit = _STYLES[style]
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(upper + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(lower + ord(ch) - 97))
        elif digit is not None and "0" <= ch <= "9":
            out.append(chr(digit + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


_SUP = dict(zip("0123456789+-=()niabcdefghjklmoprstuvwxyzABDEGHIJKLMNOPRTUVW∘′",
                "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ°′"))
_SUB = dict(zip("0123456789+-=()aehijklmnoprstuvx",
                "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))
_SUP["−"] = "⁻"
_SUB["−"] = "₋"


def superscript(text: str) -> str | None:
    """text in superscript letters, or None when one has no such form."""
    if all(ch in _SUP or ch == " " for ch in text):
        return "".join(_SUP.get(ch, ch) for ch in text)
    return None


def subscript(text: str) -> str | None:
    if all(ch in _SUB or ch == " " for ch in text):
        return "".join(_SUB.get(ch, ch) for ch in text)
    return None


# -- emoji --------------------------------------------------------------------

# Blender 5.2 draws emoji in monochrome from its bundled Noto Emoji. These
# code points have no glyph in any of its fonts, and draw as a box.
_NO_GLYPH = ((0x1F10D, 0x1F10F), (0x1F16D, 0x1F16F), (0x1F1AD, 0x1F1AD), (0x1F260, 0x1F265),
             (0x1F6D3, 0x1F6D4), (0x1F774, 0x1F77F), (0x1F7D5, 0x1F7D9), (0x1F8B0, 0x1F8C1),
             (0x1F900, 0x1F90B), (0x1FA00, 0x1FA6D), (0x1FA89, 0x1FA89), (0x1FA8F, 0x1FA8F),
             (0x1FABE, 0x1FABE), (0x1FAC6, 0x1FAC6), (0x1FADC, 0x1FADC), (0x1FADF, 0x1FADF),
             (0x1FAE9, 0x1FAFF), (0x1FB00, 0x1FFFF))
# Variation selectors, skin tones and the keycap frame: a box or a swatch
# beside the emoji in Blender, nothing lost without them.
_DROPPED = re.compile("[\ufe0e\ufe0f\U0001F3FB-\U0001F3FF\u20e3]")
# A joined emoji (a family, a profession) is its first part.
_JOINED = re.compile("\u200d\\S?")


def clean(text: str) -> str:
    """text without what Blender would draw as boxes: emoji sequences
    become their first emoji, and emoji no font has are dropped."""
    if not any(ord(ch) > 0x2000 for ch in text):
        return text
    text = _DROPPED.sub("", text)
    text = _JOINED.sub("", text)
    return "".join(ch for ch in text if not _no_glyph(ord(ch)))


def _no_glyph(cp: int) -> bool:
    return cp >= 0x1F10D and any(lo <= cp <= hi for lo, hi in _NO_GLYPH)


# -- TeX ----------------------------------------------------------------------

_GREEK = {name: chr(cp) for name, cp in (
    ("alpha", 0x3B1), ("beta", 0x3B2), ("gamma", 0x3B3), ("delta", 0x3B4), ("epsilon", 0x3F5),
    ("varepsilon", 0x3B5), ("zeta", 0x3B6), ("eta", 0x3B7), ("theta", 0x3B8), ("vartheta", 0x3D1),
    ("iota", 0x3B9), ("kappa", 0x3BA), ("lambda", 0x3BB), ("mu", 0x3BC), ("nu", 0x3BD), ("xi", 0x3BE),
    ("pi", 0x3C0), ("varpi", 0x3D6), ("rho", 0x3C1), ("varrho", 0x3F1), ("sigma", 0x3C3),
    ("varsigma", 0x3C2), ("tau", 0x3C4), ("upsilon", 0x3C5), ("phi", 0x3D5), ("varphi", 0x3C6),
    ("chi", 0x3C7), ("psi", 0x3C8), ("omega", 0x3C9), ("Gamma", 0x393), ("Delta", 0x394),
    ("Theta", 0x398), ("Lambda", 0x39B), ("Xi", 0x39E), ("Pi", 0x3A0), ("Sigma", 0x3A3),
    ("Upsilon", 0x3A5), ("Phi", 0x3A6), ("Psi", 0x3A8), ("Omega", 0x3A9))}
_TEX_SYMBOLS = {
    **_GREEK,
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗", "star": "⋆",
    "circ": "∘", "bullet": "•", "oplus": "⊕", "otimes": "⊗", "cup": "∪", "cap": "∩",
    "wedge": "∧", "land": "∧", "vee": "∨", "lor": "∨", "neg": "¬", "lnot": "¬", "setminus": "∖",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈",
    "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝", "ll": "≪", "gg": "≫",
    "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇", "in": "∈", "notin": "∉",
    "ni": "∋", "perp": "⊥", "parallel": "∥", "mid": "|", "to": "→", "rightarrow": "→",
    "leftarrow": "←", "gets": "←", "leftrightarrow": "↔", "Rightarrow": "⇒", "implies": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "iff": "⇔", "mapsto": "↦", "uparrow": "↑",
    "downarrow": "↓", "longrightarrow": "⟶", "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫",
    "iint": "∬", "iiint": "∭", "oint": "∮", "bigcup": "⋃", "bigcap": "⋂", "infty": "∞",
    "partial": "∂", "nabla": "∇", "forall": "∀", "exists": "∃", "emptyset": "∅",
    "varnothing": "∅", "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "prime": "′", "angle": "∠", "degree": "°", "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ", "Im": "ℑ",
    "aleph": "ℵ", "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈",
    "rceil": "⌉", "|": "‖", "Vert": "‖", "vert": "|", "therefore": "∴", "because": "∵",
    "top": "⊤", "bot": "⊥", "dagger": "†", "checkmark": "✓", "sqrt": "√",
    # Spacing: thin and medium spaces, which also keep maths together when
    # a line wraps.
    ",": "\u2009", ";": "\u2005", ":": "\u2005", ">": "\u2005", "!": "", " ": " ", "quad": "  ",
    "qquad": "   ", "\\": " ", "{": "{", "}": "}", "%": "%", "$": "$", "&": "&", "#": "#", "_": "_",
}
# Commands that only size or space what follows.
_TEX_DROP = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr",
             "displaystyle", "textstyle", "limits", "nolimits", "middle"}
_TEX_TEXT = {"text", "textrm", "mathrm", "operatorname", "mathsf", "textsf", "mathcal", "mathscr",
             "mathfrak", "textnormal", "mbox", "hbox"}
_TEX_BOLD = {"mathbf", "textbf", "boldsymbol", "bm"}
_TEX_ITALIC = {"mathit", "textit", "emph"}
_TEX_FRACS = {"frac", "tfrac", "dfrac", "cfrac"}
_TEX_ACCENTS = {"hat": "\u0302", "widehat": "\u0302", "bar": "\u0304", "overline": "\u0304",
                "tilde": "\u0303", "widetilde": "\u0303", "dot": "\u0307", "ddot": "\u0308",
                "vec": "\u20d7"}
_DOUBLE_STRUCK = {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}
_TEX_TOKEN = re.compile(r"\\([A-Za-z]+|.)|([{}^_])|(\s+)|(.)", re.S)


def tex(source: str) -> str:
    """TeX maths as Unicode, as far as it goes: Greek letters, operators
    and relations as their symbols, ^ and _ as superscript and subscript
    letters (in brackets when one has no such form), fractions with a
    fraction slash, roots with √. Unknown commands lose their backslash."""
    tokens = [m.groups() for m in _TEX_TOKEN.finditer(source)]
    out, _ = _tex_group(tokens, 0, top=True)
    # TeX ignores the spaces in its source: beside a spacing command they
    # would only widen it.
    out = re.sub(" *([\u2009\u2005]) *", r"\1", out)
    return re.sub(r" {2,}", "  ", out).strip()


def _tex_group(tokens, i, top=False):
    """Tokens from i up to the } that closes the group (or the end) as
    text, and the index after it."""
    out = []
    while i < len(tokens):
        special = tokens[i][1]
        if special == "}" and not top:
            return "".join(out), i + 1
        if special in ("^", "_"):
            arg, i = _tex_argument(tokens, i + 1)
            out.append(_tex_script(arg, special))
            continue
        piece, i = _tex_atom(tokens, i)
        out.append(piece)
    return "".join(out), i


def _tex_atom(tokens, i):
    """One token or group at i as text, and the index after it."""
    command, special, space, char = tokens[i]
    if special == "{":
        return _tex_group(tokens, i + 1)
    if special == "}":
        return "", i + 1
    if space is not None:
        return " ", i + 1
    if char is not None:
        return char, i + 1
    i += 1
    if command in _TEX_DROP:
        return "", i
    if command in _TEX_FRACS:
        top, i = _tex_argument(tokens, i)
        bottom, i = _tex_argument(tokens, i)
        return f"{_tex_operand(top)}⁄{_tex_operand(bottom)}", i
    if command == "sqrt":
        index = ""
        if i < len(tokens) and tokens[i][3] == "[":
            j = i + 1
            while j < len(tokens) and tokens[j][3] != "]":
                j += 1
            index = "".join(t[3] or t[2] or "" for t in tokens[i + 1:j]).strip()
            i = j + 1
        radicand, i = _tex_argument(tokens, i)
        sign = {"": "√", "2": "√", "3": "∛", "4": "∜"}.get(index) or (superscript(index) or index) + "√"
        return sign + _tex_operand(radicand), i
    if command in _TEX_TEXT or command in _TEX_BOLD or command in _TEX_ITALIC or command == "mathbb":
        arg, i = _tex_argument(tokens, i)
        if command in _TEX_BOLD:
            return styled(arg, "b"), i
        if command in _TEX_ITALIC:
            return styled(arg, "i"), i
        if command == "mathbb":
            return "".join(_DOUBLE_STRUCK.get(ch, ch) for ch in arg), i
        return arg, i
    if command in _TEX_ACCENTS:
        arg, i = _tex_argument(tokens, i)
        return (arg + _TEX_ACCENTS[command]) if len(arg) == 1 else arg, i
    if command in _TEX_SYMBOLS:
        return _TEX_SYMBOLS[command], i
    # A named function (\sin, \lim) or an unknown command: its name.
    return command, i


def _tex_argument(tokens, i):
    while i < len(tokens) and tokens[i][2] is not None:
        i += 1
    if i >= len(tokens):
        return "", i
    return _tex_atom(tokens, i)


def _tex_operand(text: str) -> str:
    """A fraction's or root's part, bracketed when it is more than one
    term."""
    text = text.strip()
    if len(text) <= 1 or re.fullmatch(r"[\w.′]+", text):
        return text
    if text.startswith("(") and text.endswith(")"):
        return text
    return f"({text})"


def _tex_script(arg: str, kind: str) -> str:
    """arg raised (^) or lowered (_), or after the sign as it is."""
    arg = arg.strip()
    mapped = superscript(arg) if kind == "^" else subscript(arg)
    if mapped is not None:
        return mapped
    return f"{kind}{arg}" if len(arg) == 1 else f"{kind}({arg})"


# -- inline -------------------------------------------------------------------

# Style switches in the text while it is parsed: each style has an on and
# an off character (private use, never in Claude's text), counted so
# nested and unbalanced markers do no harm.
_ON = {"b": "\ue001", "i": "\ue003", "m": "\ue005", "s": "\ue007", "sup": "\ue009", "sub": "\ue00b"}
_OFF = {style: chr(ord(on) + 1) for style, on in _ON.items()}
_SWITCH = {**{on: (style, 1) for style, on in _ON.items()}, **{off: (style, -1) for style, off in _OFF.items()}}
_LINK_ON, _LINK_OFF = "\ue010", "\ue011"
# What the scan has already decided (an escaped character, a code span, a
# link's address) stands in the text as one character from here on, so
# the later passes cannot touch it.
_HELD = 0xF0000
_PRIVATE = re.compile("[\ue000-\ue0ff\U000F0000-\U000FFFFF]")

_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_AUTOLINK = re.compile(r"<((?:https?|ftp)://[^\s<>]+|mailto:[^\s<>]+|[\w.+-]+@[\w-]+\.[\w.-]+)>")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)((?:\s+[^<>]*?)?)\s*(/?)>")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HREF = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
# Tags that are HTML: any other <Name> (List<String>) is text.
_HTML_TAGS = {"a", "abbr", "b", "big", "blockquote", "br", "center", "cite", "code", "dd", "del", "details",
              "div", "dl", "dt", "em", "figcaption", "figure", "font", "h1", "h2", "h3", "h4", "h5", "h6",
              "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "picture", "pre", "q", "s", "samp",
              "section", "small", "source", "span", "strike", "strong", "sub", "summary", "sup", "table",
              "tbody", "td", "th", "thead", "tr", "tt", "u", "ul", "var"}
_TAG_STYLES = {"b": "b", "strong": "b", "i": "i", "em": "i", "cite": "i", "var": "i", "code": "m",
               "kbd": "m", "tt": "m", "samp": "m", "s": "s", "del": "s", "strike": "s", "sup": "sup",
               "sub": "sub"}
# A link's address may hold balanced parentheses (Foo_(bar)).
_LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?((?:[^()\s<>]|\([^()\s<>]*\))*)>?"
                   r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_NOTE_REF = re.compile(r"\[\^([^\]\s]+)\]")
_BARE_URL = re.compile("(?<![\\w/])(?:https?://|www\\.)[^\\s<>\ue000-\ue0ff\U000F0000-\U000FFFFF]*"
                       "[^\\s<>.,;:!?'\"\\]*_~\ue000-\ue0ff\U000F0000-\U000FFFFF]")
# What a bare address does not end with: punctuation after it, and a
# closing parenthesis that has no opening one in it (as GFM reads).
_URL_TAIL = set(".,;:!?'\"]*_~")
# Emphasis opens before a non-space and closes after one. Underscores only
# count at word edges, so snake_case names stay as they are.
_EMPHASIS = (
    (re.compile(r"(\*\*\*|___)(?=\S)(.+?)(?<=\S)\1"), ("b", "i")),
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"), ("b",)),
    (re.compile(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)|(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)"), ("i",)),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), ("s",)),
)


class Notes:
    """A document's footnotes: their text by name, and the numbers they
    get in the order they are first referred to."""

    def __init__(self, texts: dict[str, str] | None = None):
        self.texts = texts or {}
        self.order: list[str] = []

    def number(self, name: str) -> int | None:
        if name not in self.texts:
            return None
        if name not in self.order:
            self.order.append(name)
        return self.order.index(name) + 1


def inline(text: str, notes: Notes | None = None, *, styles: tuple = ()) -> str:
    """One line of Markdown as plain text with styled letters: bold, italic
    and code become their Unicode letters, struck text gets a stroke, links
    show their text, maths its symbols and escaped characters themselves."""
    return inline_links(text, notes, styles=styles)[0]


def inline_links(text: str, notes: Notes | None = None, *, styles: tuple = ()):
    """inline's text and its links, as (start, end, address) in it. A <br>
    is a line break in the text; styles ("b", "i") apply to all of it."""
    held: list[tuple[str, str]] = []

    def hold(kind: str, value: str) -> str:
        held.append((kind, value))
        return chr(_HELD + len(held) - 1)

    text = _scan(_PRIVATE.sub("", text), hold)
    if notes is not None:
        def note(m):
            n = notes.number(m.group(1))
            return m.group(0) if n is None else hold("raw", superscript(str(n)))
        text = _NOTE_REF.sub(note, text)
    text = _LINK.sub(lambda m: _LINK_ON + hold("url", m.group(2)) + (m.group(1) or hold("raw", m.group(2)))
                     + _LINK_OFF, text)
    def bare(m):
        url = _trim_url(m.group(0))
        return (_LINK_ON + hold("url", _address(url)) + hold("raw", url) + _LINK_OFF
                + m.group(0)[len(url):])
    text = _BARE_URL.sub(bare, text)
    for pattern, marked in _EMPHASIS:
        text = pattern.sub(lambda m, s=marked: _wrap_styles(_content(m), s), text)
    if styles:
        text = _wrap_styles(text, styles)
    return _finish(text, held)


def _trim_url(url: str) -> str:
    """A bare address without the punctuation after it, keeping a closing
    parenthesis that closes one in the address."""
    while len(url) > 1:
        if url[-1] == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        elif url[-1] in _URL_TAIL:
            url = url[:-1]
        else:
            break
    return url


# The schemes a link may open. Replies can carry text from a shared file or
# a web page, so any other (file:, a custom protocol handler) is plain text.
OPEN_SCHEMES = ("http", "https", "mailto")


def openable(url: str) -> bool:
    try:
        return urlsplit(url).scheme.lower() in OPEN_SCHEMES
    except ValueError:
        return False


def _address(url: str) -> str:
    return url if "://" in url else "https://" + url


def _content(match: re.Match) -> str:
    # Bold italic and strike have their text in the last group; bold and
    # italic one group per marker (* or _), of which one matched.
    groups = [g for g in match.groups() if g is not None]
    return groups[-1]


def _wrap_styles(content: str, styles) -> str:
    return "".join(_ON[s] for s in styles) + content + "".join(_OFF[s] for s in reversed(styles))


def _scan(text: str, hold) -> str:
    """The first pass, left to right as CommonMark reads: a backslash
    escape, a code span, inline maths, an autolink and an HTML tag each
    take their characters before anything else can."""
    text = _COMMENT.sub("", text)
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _PUNCT:
            out.append(hold("text", text[i + 1]))
            i += 2
            continue
        if ch == "`":
            run = 0
            while i + run < n and text[i + run] == "`":
                run += 1
            close = _closing_ticks(text, i + run, run)
            if close is None:
                out.append(hold("text", "`" * run))
                i += run
                continue
            code = text[i + run:close].replace("\n", " ")
            if code.startswith(" ") and code.endswith(" ") and code.strip():
                code = code[1:-1]
            out.append(hold("code", code))
            i = close + run
            continue
        if ch == "$":
            end = _closing_dollar(text, i)
            if end is not None:
                double = text.startswith("$$", i)
                start = i + (2 if double else 1)
                out.append(hold("text", tex(text[start:end])))
                i = end + (2 if double else 1)
                continue
        if ch == "<":
            link = _AUTOLINK.match(text, i)
            if link:
                address = link.group(1)
                if "@" in address and "://" not in address and not address.startswith("mailto:"):
                    address = "mailto:" + address
                shown = link.group(1).removeprefix("mailto:")
                out.append(_LINK_ON + hold("url", address) + hold("raw", shown) + _LINK_OFF)
                i = link.end()
                continue
            tag = _TAG.match(text, i)
            if tag and tag.group(2).lower() in _HTML_TAGS:
                out.append(_tag(tag, hold))
                i = tag.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _closing_ticks(text: str, start: int, run: int) -> int | None:
    """Where the backtick run of exactly run backticks that closes a code
    span opened before start begins."""
    i = start
    while True:
        i = text.find("`" * run, i)
        if i < 0:
            return None
        end = i + run
        if (end >= len(text) or text[end] != "`") and text[i - 1] != "`":
            return i
        while i < len(text) and text[i] == "`":
            i += 1


def _closing_dollar(text: str, i: int) -> int | None:
    """The end of the maths opened by the $ (or $$) at i: it opens before a
    non-space and closes after one, not before a digit, so prices stay."""
    double = text.startswith("$$", i)
    start = i + (2 if double else 1)
    if start >= len(text) or text[start].isspace():
        return None
    j = start
    while True:
        j = text.find("$$" if double else "$", j)
        if j < 0:
            return None
        if j > start and text[j - 1] == "\\":
            j += 1
            continue
        after = j + (2 if double else 1)
        if not text[j - 1].isspace() and j > start and not (after < len(text) and text[after].isdigit()):
            return j
        j += 1


def _tag(tag: re.Match, hold) -> str:
    """An HTML tag as a style switch, a line break or a link; other tags go
    (their text stays)."""
    closing, name = tag.group(1), tag.group(2).lower()
    if name == "br":
        return "\n"
    style = _TAG_STYLES.get(name)
    if style:
        return (_OFF if closing else _ON)[style]
    if name == "a":
        if closing:
            return _LINK_OFF
        href = _HREF.search(tag.group(3) or "")
        if href:
            return _LINK_ON + hold("url", next(g for g in href.groups() if g is not None))
    return ""


def _finish(text: str, held) -> tuple[str, list]:
    """The switches applied: letters in their styles, struck runs with
    their stroke, link text underlined, entities decoded, emoji cleaned;
    and where the links are."""
    depth = dict.fromkeys(_ON, 0)
    chars: list[tuple[str, bool]] = []  # (character, struck)
    links: list[list] = []
    open_links: list[list] = []
    expect_url = False

    def emit(value: str, kind: str):
        for ch in clean(value):
            chars.append((_style_char(ch, depth, kind), depth["s"] > 0 and ch != "\n"))

    for part in re.split(f"([{''.join(_SWITCH)}{_LINK_ON}{_LINK_OFF}]|[\U000F0000-\U000FFFFF])", text):
        if not part:
            continue
        if part in _SWITCH:
            style, step = _SWITCH[part]
            depth[style] = max(0, depth[style] + step)
        elif part == _LINK_ON:
            expect_url = True
        elif part == _LINK_OFF:
            if open_links:
                link = open_links.pop()
                link[1] = len(chars)
                if link[1] > link[0] and openable(link[2]):
                    links.append(link)
        elif ord(part[0]) >= _HELD:
            kind, value = held[ord(part[0]) - _HELD]
            if kind == "url" and expect_url:
                open_links.append([len(chars), len(chars), value])
            elif kind != "url":
                emit(value, kind)
            expect_url = False
        else:
            expect_url = False
            emit(html.unescape(part), "text")
    # The underline goes after each letter of a link and the stroke between
    # consecutive struck characters, so the offsets of the links move with
    # them.
    # Not under a link's last letter (the mark reaches under the next one),
    # unless that is its only letter.
    linked = {k for a, b, _url in links for k in range(a, b - 1 if b - a > 1 else b)}
    out, where, at = [], [], 0
    for k, (ch, struck) in enumerate(chars):
        where.append(at)
        if k in linked and not ch.isspace():
            ch += UNDERLINE
        if struck and k + 1 < len(chars) and chars[k + 1][1]:
            ch += STRIKE
        out.append(ch)
        at += len(ch)
    where.append(at)
    spans = [(where[a], where[b], url) for a, b, url in sorted(links)]
    return "".join(out), spans


def _style_char(ch: str, depth: dict, kind: str) -> str:
    if kind == "raw":
        return ch
    if depth["sup"] and ch in _SUP:
        return _SUP[ch]
    if depth["sub"] and ch in _SUB:
        return _SUB[ch]
    if kind == "code" or depth["m"]:
        return styled(ch, "m")
    if depth["b"] and depth["i"]:
        return styled(ch, "bi")
    if depth["b"]:
        return styled(ch, "b")
    if depth["i"]:
        return styled(ch, "i")
    return ch


# -- wrapping -----------------------------------------------------------------

def wrap(text: str, width: float, measure: Measure) -> list[str]:
    """text in lines no wider than width, broken at spaces; a word too long
    for a line is broken where it must be."""
    return [line for line, _start, _end in wrap_spans(text, width, measure)]


def wrap_spans(text: str, width: float, measure: Measure) -> list[tuple[str, int, int]]:
    """wrap's lines with where each starts and ends in text. Only spaces
    and tabs break a line (a no-break or hair space does not), and a line
    break in text always does."""
    out = []
    offset = 0
    for paragraph in text.split("\n"):
        line, start, end = "", offset, offset
        for m in re.finditer(r"[^ \t]+", paragraph):
            word, at = m.group(), offset + m.start()
            candidate = f"{line} {word}" if line else word
            if measure(candidate) <= width:
                if not line:
                    start = at
                line, end = candidate, at + len(word)
                continue
            if line:
                out.append((line, start, end))
            while len(word) > 1 and measure(word) > width:
                n = _fitting(word, width, measure)
                out.append((word[:n], at, at + n))
                word, at = word[n:], at + n
            line, start, end = word, at, at + len(word)
        out.append((line, start, end))
        offset += len(paragraph) + 1
    return out


def _fitting(text: str, width: float, measure: Measure) -> int:
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid]) <= width:
            lo = mid
        else:
            hi = mid - 1
    return lo


# -- blocks -------------------------------------------------------------------

_FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_NOTE_DEF = re.compile(r"^\s{0,3}\[\^([^\]\s]+)\]:\s?(.*)$")
_DETAILS = re.compile(r"<(/?)details\b[^>]*>", re.I)
_SUMMARY = re.compile(r"<summary\b[^>]*>(.*?)</summary\s*>", re.I | re.S)
_INDENTED = re.compile(r"^(?: {4}|\t)")


def _cells(row: str) -> list[str]:
    """A table row's cells, split at pipes that are neither escaped nor in
    a code span."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, cell, ticks, i = [], [], 0, 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row) and row[i + 1] == "|":
            cell.append("|")
            i += 2
            continue
        if ch == "`":
            ticks ^= 1
        if ch == "|" and not ticks:
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(ch)
        i += 1
    cells.append("".join(cell).strip())
    return cells


def _aligns(rule: str) -> list[str]:
    out = []
    for cell in _cells(rule):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("CENTER" if left and right else "RIGHT" if right else "LEFT")
    return out


def _footnotes(source: list[str]) -> tuple[list[str], dict[str, str]]:
    """The footnote definitions taken out of the source (outside code
    blocks), with the indented lines that continue them."""
    kept, texts = [], {}
    fence = None
    i = 0
    while i < len(source):
        line = source[i]
        mark = _FENCE.match(line)
        if mark and fence is None:
            fence = mark.group(2)[0] * 3
        elif fence is not None and line.strip().startswith(fence):
            fence = None
        elif fence is None:
            note = _NOTE_DEF.match(line)
            if note:
                parts = [note.group(2).strip()]
                while i + 1 < len(source) and source[i + 1].strip() and source[i + 1][:2] in ("  ", "\t"):
                    i += 1
                    parts.append(source[i].strip())
                texts[note.group(1)] = " ".join(p for p in parts if p)
                i += 1
                continue
        kept.append(line)
        i += 1
    return kept, texts


class _Layout:
    def __init__(self, width: float, measure: Measure, box_pad: float, link_room: float, copy_room: float):
        self.width = width
        self.measure = measure
        self.box_pad = box_pad
        self.link_room = link_room
        self.copy_room = copy_room
        self.em = measure("M") or 8.0
        self.step = indent_step(measure)
        self.notes = Notes()

    def text(self, out, content: str, indent: float, quote: int, kind="text", marker="", level=0, styles=()):
        """content's lines (a <br> or a trailing backslash breaks one), each
        with the links on it."""
        text, links = inline_links(content, self.notes, styles=styles)
        if not text.strip():
            return
        room = max(self.width - indent - (self.link_room if links else 0), self.em)
        for n, (line, start, end) in enumerate(wrap_spans(text, room, self.measure)):
            # A link's button goes on the line where the link starts, once.
            on = tuple((plain(text[a:b]), url) for a, b, url in links if start <= a < end)
            out.append(Line(line, kind, indent, marker if n == 0 else "", level, quote, on))

    def code_block(self, out, code: list[str], language: str, indent: float, quote: int):
        """A code block: its head (the language, and the code to copy), then
        its lines."""
        out.append(Line(language, "codehead", indent, quote=quote, copy="\n".join(code)))
        # Without a language there is no head row: the copy button shares the
        # code's rows (the first), so they leave room for it.
        reserve = 0.0 if language else self.copy_room
        for text in code:
            self.code(out, text, indent, quote, reserve)

    def code(self, out, text: str, indent: float, quote: int, reserve: float = 0.0):
        """A code line in monospace letters, its spaces en spaces (about as
        wide as those letters, where a space is half that) so indentation
        lines up, broken where it is wider than its box."""
        text = styled(clean(text.rstrip().expandtabs(4)), "m").replace(" ", CODE_SPACE)
        if not text:
            out.append(Line("", "code", indent, quote=quote))
        for piece in _code_pieces(text, max(self.width - indent - self.box_pad - reserve, self.em), self.measure):
            out.append(Line(piece, "code", indent, quote=quote))

    def blocks(self, source: list[str], indent: float = 0.0, quote: int = 0) -> list[Line]:
        """The Lines of a run of source lines, indent pixels in."""
        out: list[Line] = []
        i = 0
        stack: list[int] = []  # the source indentation of each open list level
        after_blank = True

        def gap():
            if out and out[-1].kind != "gap":
                out.append(Line("", "gap", quote=quote))

        while i < len(source):
            raw = source[i]
            line = raw.rstrip()
            blank = not line.strip()
            fence = _FENCE.match(line)
            if fence:
                lead, mark = len(fence.group(1)), fence.group(2)
                inset = self.step * len(stack) if stack and lead else 0.0
                language = (line[fence.end():].split() or [""])[0].strip("`~{}.")
                i += 1
                code = []
                while i < len(source) and not source[i].strip().startswith(mark):
                    code.append(source[i][min(lead, len(source[i]) - len(source[i].lstrip())):].rstrip())
                    i += 1
                self.code_block(out, code, language, indent + inset, quote)
                i += 1
            elif blank:
                # A list goes on past a blank line: an indented line
                # after it continues its item, a new item joins it.
                gap()
                i += 1
            elif _INDENTED.match(raw) and after_blank and not stack:
                # An indented code block: four spaces after a blank line,
                # up to the next line that is less indented.
                end = i
                while end < len(source) and (not source[end].strip() or _INDENTED.match(source[end])):
                    end += 1
                while not source[end - 1].strip():
                    end -= 1
                code = [line[4:] if line.startswith("    ") else line.lstrip("\t") for line in source[i:end]]
                self.code_block(out, [line.rstrip() for line in code], "", indent, quote)
                i = end
            elif line.strip().startswith(("$$", "\\[")):
                i = self.math(out, source, i, indent, quote)
            elif _DETAILS.match(line.strip()):
                i = self.details(out, source, i, indent, quote)
            elif heading := _HEADING.match(line):
                stack.clear()
                gap()
                level = len(heading.group(1))
                self.text(out, heading.group(2) or "", indent, quote, "heading", level=level,
                          styles=HEADING_STYLES[level])
                i += 1
            elif _RULE.match(line):
                stack.clear()
                out.append(Line("", "rule", indent, quote=quote))
                i += 1
            elif item := _ITEM.match(line):
                lead = len(item.group(1).expandtabs(4))
                while stack and lead < stack[-1]:
                    stack.pop()
                if not stack or lead > stack[-1]:
                    stack.append(lead)
                level = len(stack) - 1
                mark, content = item.group(2), item.group(3)
                marker = mark if mark[0].isdigit() else BULLETS[min(level, len(BULLETS) - 1)]
                task = _TASK.match(content)
                if task:
                    marker, content = TASKS[task.group(1)], task.group(2)
                self.text(out, _hard_break(content), indent + self.step * (level + 1), quote, marker=marker)
                i += 1
            elif _QUOTE.match(line):
                stack.clear()
                inner = []
                while i < len(source) and (m := _QUOTE.match(source[i].rstrip())):
                    inner.append(m.group(1))
                    i += 1
                out.extend(self.blocks(inner, indent + self.step, quote + 1))
            elif "|" in line and i + 1 < len(source) and _TABLE_RULE.match(source[i + 1]):
                stack.clear()
                rows = [_cells(line)]
                aligns = _aligns(source[i + 1])
                i += 2
                while i < len(source) and "|" in source[i] and source[i].strip():
                    rows.append(_cells(source[i]))
                    i += 1
                out.append(self.table(rows, aligns, indent, quote))
            else:
                # A line under a list item, indented, continues that item.
                lead = len(raw) - len(raw.lstrip())
                if not (stack and lead > 0):
                    stack.clear()
                self.text(out, _hard_break(line.strip()), indent + self.step * len(stack), quote)
                i += 1
            after_blank = blank
        while out and out[-1].kind == "gap":
            out.pop()
        while out and out[0].kind == "gap":
            out.pop(0)
        return out

    def math(self, out, source, i, indent, quote) -> int:
        """A $$ … $$ (or \\[ … \\]) block as one centred line of symbols."""
        first = source[i].strip()
        close = "$$" if first.startswith("$$") else "\\]"
        body = [first[2:]]
        while close not in body[-1] and i + 1 < len(source):
            i += 1
            body.append(source[i].strip())
        text = " ".join(body)
        text = text[:text.index(close)] if close in text else text
        for line in wrap(clean(tex(text)), max(self.width - indent, self.em), self.measure):
            out.append(Line(line, "math", indent, quote=quote))
        return i + 1

    def details(self, out, source, i, indent, quote) -> int:
        """<details> up to its </details> (nested ones counted) as a
        collapsible section: its summary as the header, the rest as Lines
        laid out the same way."""
        depth, lines = 0, []
        while i < len(source):
            line = source[i]
            for tag in _DETAILS.finditer(line):
                depth += -1 if tag.group(1) else 1
            lines.append(line)
            i += 1
            if depth <= 0:
                break
        content = "\n".join(lines)
        content = content[_DETAILS.search(content).end():]
        ends = list(_DETAILS.finditer(content))
        if ends and ends[-1].group(1):
            content = content[:ends[-1].start()]
        summary = _SUMMARY.search(content)
        title = "Details"
        if summary:
            title = summary.group(1).strip() or title
            content = content[:summary.start()] + content[summary.end():]
        text = inline(" ".join(title.split()), self.notes).replace("\n", " ")
        body = self.blocks(content.strip("\n").split("\n"), indent, quote)
        out.append(Line(text, "details", indent, quote=quote, body=tuple(body)))
        return i

    def table(self, rows: list[list[str]], aligns: list[str], indent, quote) -> Line:
        """A table whose columns are as wide as their text, shared out when
        that is wider than the panel: a column narrower than its share
        keeps its width, the rest split what is left; text wraps in its
        column."""
        n = len(aligns)
        cells = [[inline(cell, self.notes, styles=("b",) if r == 0 else ()).replace("\n", " ")
                  for cell in (row + [""] * n)[:n]] for r, row in enumerate(rows)]
        pad = CELL_PAD_EMS * self.em
        room = max(self.width - indent - self.box_pad - n * pad, n * self.em)
        natural = [max(self.measure(row[j]) for row in cells) for j in range(n)]
        widths = list(natural)
        if sum(natural) > room:
            left, wide = room, list(range(n))
            while True:
                share = left / len(wide)
                narrow = [j for j in wide if natural[j] <= share]
                if not narrow:
                    break
                for j in narrow:
                    left -= natural[j]
                    wide.remove(j)
                if not wide:
                    break
            for j in wide:
                widths[j] = left / len(wide)
        widths = [max(w, self.em) for w in widths]
        wrapped = tuple(tuple(tuple(wrap(row[j], widths[j], self.measure)) for j in range(n)) for row in cells)
        table = Table(tuple(w + pad for w in widths), tuple(aligns), wrapped, sum(natural) > room)
        return Line("", "table", indent, quote=quote, table=table)

    def footnotes(self, out):
        """The footnotes referred to, in their order, after a rule: each dim,
        its number in the margin."""
        if not self.notes.order:
            return
        while out and out[-1].kind == "gap":
            out.pop()
        out.append(Line("", "gap"))
        out.append(Line("", "rule"))
        for n, name in enumerate(self.notes.order, 1):
            self.text(out, self.notes.texts[name], self.step, 0, "note", superscript(str(n)))


def plain(text: str) -> str:
    """Laid-out text without its underline and stroke marks."""
    return text.replace(STRIKE, "").replace(UNDERLINE, "")


def indent_step(measure: Measure) -> float:
    """The indentation of a list level or a quote, in pixels."""
    return INDENT_EMS * (measure("M") or 8.0)


def _hard_break(line: str) -> str:
    """A line's trailing backslash (a hard line break) goes: the source line
    break already is one."""
    if line.endswith("\\") and not line.endswith("\\\\"):
        return line[:-1].rstrip()
    return line


def layout(text: str, width: float, measure: Measure, code_width: float | None = None,
           link_room: float = 0.0, copy_room: float | None = None) -> list[Line]:
    """Markdown text as the lines to draw in width pixels (code lines and
    tables in code_width, inside their box; a line with a link leaves
    link_room for its button, and the code of a block without a language
    copy_room, link_room unless given, for its copy button). A source line break stays a line break
    (Claude writes "Done:" on a line of its own); a blank line between
    blocks is a gap."""
    box_pad = width - (width if code_width is None else code_width)
    source, notes = _footnotes(text.replace("\r\n", "\n").split("\n"))
    doc = _Layout(width, measure, box_pad, link_room, link_room if copy_room is None else copy_room)
    doc.notes.texts = notes
    out = doc.blocks(source)
    doc.footnotes(out)
    return out


def _code_pieces(code: str, width: float, measure: Measure) -> list[str]:
    """A code line as it is, broken by characters where it is too wide."""
    pieces = []
    while code:
        if measure(code) <= width:
            pieces.append(code)
            break
        n = _fitting(code, width, measure)
        pieces.append(code[:n])
        code = code[n:]
    return pieces
