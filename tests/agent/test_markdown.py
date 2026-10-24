# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from whittle import markdown as md
from whittle.markdown import Line

S = md.STRIKE


def code_line(text: str) -> str:
    return md.styled(text, "m").replace(" ", md.CODE_SPACE)


def measure(text: str) -> float:
    # An underline mark takes no room, as in Blender.
    return 6.0 * len(text.replace(md.UNDERLINE, ""))


def ul(text: str) -> str:
    """text underlined as link text is: every letter but the last, since the
    mark reaches under the next one (a one-letter link keeps it)."""
    last = len(text) - 1 if len(text) > 1 else len(text)
    return "".join(ch if ch.isspace() or k >= last else ch + md.UNDERLINE for k, ch in enumerate(text))


def kinds(lines):
    return [line.kind for line in lines]


def texts(lines):
    return [line.text for line in lines]


class InlineTest(unittest.TestCase):
    def test_bold_and_italic_become_styled_letters(self):
        self.assertEqual(md.inline("a **bold** word"), "a 𝗯𝗼𝗹𝗱 word")
        self.assertEqual(md.inline("a __bold__ word"), "a 𝗯𝗼𝗹𝗱 word")
        self.assertEqual(md.inline("a *soft* word"), "a 𝘴𝘰𝘧𝘵 word")
        self.assertEqual(md.inline("a _soft_ word"), "a 𝘴𝘰𝘧𝘵 word")
        self.assertEqual(md.inline("***Both*** 42"), "𝘽𝙤𝙩𝙝 42")
        self.assertEqual(md.inline("**2 horns**"), "𝟮 𝗵𝗼𝗿𝗻𝘀", "bold has digits")
        self.assertEqual(md.inline("**bold *and italic***"), "𝗯𝗼𝗹𝗱 𝙖𝙣𝙙 𝙞𝙩𝙖𝙡𝙞𝙘", "nested styles combine")

    def test_what_is_not_emphasis_stays(self):
        self.assertEqual(md.inline("whittle.mesh_report and snake_case_name"),
                         "whittle.mesh_report and snake_case_name")
        self.assertEqual(md.inline("2 * 3 * 4"), "2 * 3 * 4", "spaced asterisks are maths")
        self.assertEqual(md.inline(r"\*not italic\*"), "*not italic*")
        self.assertEqual(md.inline("** not bold **"), "** not bold **")
        self.assertEqual(md.inline("non-ASCII **é**"), "non-ASCII é", "letters without a styled form stay")

    def test_strikethrough_draws_a_stroke_between_its_letters(self):
        self.assertEqual(md.inline("~~old~~ new"), f"o{S}l{S}d new")
        self.assertEqual(md.inline("~~a b~~"), f"a{S} {S}b", "the stroke crosses the space too")
        self.assertEqual(md.inline("<s>x</s> <del>y</del>"), "x y", "one letter alone has no neighbour")
        self.assertEqual(md.inline("~~ not struck ~~"), "~~ not struck ~~")
        self.assertEqual(md.wrap(md.inline("~~old text~~"), 1000, measure), [f"o{S}l{S}d{S} {S}t{S}e{S}x{S}t"],
                         "a hair space does not break the line")

    def test_inline_code_is_monospace_and_literal(self):
        self.assertEqual(md.inline("run `mesh_report(**obj**)` now"), "run 𝚖𝚎𝚜𝚑_𝚛𝚎𝚙𝚘𝚛𝚝(**𝚘𝚋𝚓**) now",
                         "nothing inside a code span is styled")
        self.assertEqual(md.inline("`Size 42`"), "𝚂𝚒𝚣𝚎 𝟺𝟸", "digits have monospace forms")
        self.assertEqual(md.inline("``a ` b``"), "𝚊 ` 𝚋", "a longer run holds a backtick")
        self.assertEqual(md.inline("`` `x` ``"), "`𝚡`", "one space inside each end goes")
        self.assertEqual(md.inline("an ` alone"), "an ` alone")
        self.assertEqual(md.inline("`a\\`"), "𝚊\\", "no escapes inside code")
        self.assertEqual(md.inline("`<b>&amp;`"), "<𝚋>&𝚊𝚖𝚙;", "no HTML inside code")

    def test_every_ascii_punctuation_escape(self):
        punctuation = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
        escaped = "".join("\\" + ch for ch in punctuation)
        self.assertEqual(md.inline(escaped), punctuation)
        self.assertEqual(md.inline(r"\`not code\` and \<b\>"), "`not code` and <b>",
                         "escapes come before code spans and tags")
        self.assertEqual(md.inline(r"\a \1"), r"\a \1", "a backslash before anything else stays")
        self.assertEqual(md.inline(r"**a\*b**"), "𝗮*𝗯")

    def test_links(self):
        text, links = md.inline_links("see [the docs](https://x.org) or <https://y.org>")
        self.assertEqual(text, f"see {ul('the docs')} or {ul('https://y.org')}", "link text is underlined")
        self.assertEqual([(md.plain(text[a:b]), url) for a, b, url in links],
                         [("the docs", "https://x.org"), ("https://y.org", "https://y.org")])
        text, links = md.inline_links("visit www.blender.org/a_b_c, then https://z.io/x.")
        self.assertEqual(md.plain(text), "visit www.blender.org/a_b_c, then https://z.io/x.", "underscores stay")
        self.assertEqual([url for _a, _b, url in links], ["https://www.blender.org/a_b_c", "https://z.io/x"])
        self.assertEqual(md.inline_links('<a href="https://a.b">**x**</a>'), (ul("𝘅"), [(0, 2, "https://a.b")]))
        self.assertEqual(md.plain(md.inline("![alt text](pic.png)")), "alt text")
        self.assertEqual(md.plain(md.inline("[](https://e.f)")), "https://e.f",
                         "a link without text shows its address")
        self.assertEqual(md.inline_links("<me@x.org>")[1], [(0, 15, "mailto:me@x.org")],
                         "8 letters, 7 underline marks")
        text, links = md.inline_links("~~[a](https://u.x)~~ b")
        self.assertEqual(links, [(0, 2, "https://u.x")], "the stroke after a link is not in it")

    def test_only_web_and_mail_links_open(self):
        for url in ("file:///home/u/x.desktop", "steam://run/1", "notes.md"):
            with self.subTest(url=url):
                text, links = md.inline_links(f"[docs]({url}) and <a href='{url}'>more</a>")
                self.assertEqual(links, [], "shown as plain text")
                self.assertEqual(md.plain(text), "docs and more")
        self.assertTrue(md.openable("HTTPS://x.org"))
        self.assertTrue(md.openable("mailto:me@x.org"))
        self.assertFalse(md.openable("ftp://x.org"))

    def test_addresses_keep_balanced_parentheses(self):
        wiki = "https://en.wikipedia.org/wiki/Foo_(bar)"
        text, links = md.inline_links(f"See {wiki} and (also https://x.com/a).")
        self.assertEqual([url for _a, _b, url in links], [wiki, "https://x.com/a"])
        self.assertEqual(md.plain(text), f"See {wiki} and (also https://x.com/a).")
        self.assertEqual(md.inline_links(f"[w]({wiki})")[1], [(0, 2, wiki)])
        self.assertEqual(md.inline_links("[w](https://a.b/c)d)")[0], ul("w") + "d)")

    def test_html(self):
        self.assertEqual(md.inline("<b>bold</b> <strong>b</strong> <i>it</i> <em>e</em>"), "𝗯𝗼𝗹𝗱 𝗯 𝘪𝘵 𝘦")
        self.assertEqual(md.inline("<code>x = 1</code> <kbd>Ctrl</kbd>"), "𝚡 = 𝟷 𝙲𝚝𝚛𝚕")
        self.assertEqual(md.inline("a<br>b<br/>c"), "a\nb\nc")
        self.assertEqual(md.inline('<span class="x">kept</span> <div>too</div> <u>u</u>'), "kept too u")
        self.assertEqual(md.inline("H<sub>2</sub>O and x<sup>2</sup>"), "H₂O and x²")
        self.assertEqual(md.inline("List<String> and a < b > c"), "List<String> and a < b > c",
                         "only HTML's own tags are tags")
        self.assertEqual(md.inline("a<!-- hidden -->b"), "ab")
        self.assertEqual(md.inline("&lt;b&gt; &amp; &quot;q&quot; &#39;s&#39; a&nbsp;b"), "<b> & \"q\" 's' a b")
        self.assertEqual(md.inline("&lt;b&gt;x&lt;/b&gt;"), "<b>x</b>", "decoded entities are text, not tags")
        self.assertEqual(md.inline("unclosed <b>bold"), "unclosed 𝗯𝗼𝗹𝗱")

    def test_maths(self):
        self.assertEqual(md.inline("so $E = mc^2$ holds"), "so E = mc² holds")
        self.assertEqual(md.inline("$x_1$ and $$y^2$$"), "x₁ and y²")
        self.assertEqual(md.inline("costs $5 and $10"), "costs $5 and $10", "prices are not maths")
        self.assertEqual(md.inline("$ x $"), "$ x $")
        self.assertEqual(md.inline(r"\$x\$"), "$x$")
        self.assertEqual(md.inline("$a_n$ and snake_case_name"), "aₙ and snake_case_name")
        self.assertEqual(md.inline("`$x$` $`y`$"), "$𝚡$ `y`", "code spans and maths each keep theirs")

    def test_emoji_draw_or_go(self):
        self.assertEqual(md.inline("🎲 🧊 ✅"), "🎲 🧊 ✅", "Blender's Noto Emoji has them")
        self.assertEqual(md.inline("❤️ 👍🏽 1️⃣"), "❤ 👍 1", "selectors, skin tones and keycaps go")
        self.assertEqual(md.inline("👨‍👩‍👧 family"), "👨 family", "a joined emoji is its first part")
        self.assertEqual(md.inline("new 🫩 face"), "new  face", "an emoji no font has goes")
        self.assertEqual(md.clean("plain"), "plain")


class TexTest(unittest.TestCase):
    def test_symbols_scripts_and_fractions(self):
        cases = {
            r"\alpha + \beta \leq \Gamma": "α + β ≤ Γ",
            r"a \cdot b \times c \neq d \geq e \approx f": "a · b × c ≠ d ≥ e ≈ f",
            r"x^2 + y_{12} = z^{n+1}": "x² + y₁₂ = zⁿ⁺¹",
            r"\frac{a}{b} + \tfrac{1}{2} + \dfrac{x+1}{y}": "a⁄b + 1⁄2 + (x+1)⁄y",
            r"\frac12": "1⁄2",
            r"\sqrt{2} \sqrt{x+1} \sqrt[3]{8}": "√2 √(x+1) ∛8",
            r"\int_0^1 x\,dx": "∫₀¹ x\u2009dx",
            r"x^2 \, dx \; y \: z": "x²\u2009dx\u2005y\u2005z",
            r"\sum_{i=1}^{n} i": "∑ᵢ₌₁ⁿ i",
            r"\infty \partial \nabla \in \forall \pi": "∞ ∂ ∇ ∈ ∀ π",
            r"\mathbb{R}^3 \to \mathbb{R}": "ℝ³ → ℝ",
            r"\left( x \right)": "( x )",
            r"x^{\circ} f^\prime": "x° f′",
            r"\text{if } x": "if  x",
            r"\mathbf{F} = m\mathbf{a}": "𝗙 = m𝗮",
            r"\foo{bar} \unknown": "foobar unknown",
            r"\sin x + \log_2 y": "sin x + log₂ y",
            r"e^{i\pi}": "e^(iπ)",
            r"\{1, 2\} \quad x": "{1, 2}  x",
            r"\vec{v}": "v⃗",
        }
        for source, want in cases.items():
            with self.subTest(source):
                self.assertEqual(md.tex(source), want)


class LayoutTest(unittest.TestCase):
    def test_plain_lines_wrap_and_line_breaks_stay(self):
        lines = md.layout("Plan: add a lid.\nDone.", 1000, measure)
        self.assertEqual(lines, [Line("Plan: add a lid."), Line("Done.")])
        lines = md.layout("one two three four", 60, measure)
        self.assertEqual(texts(lines), ["one two", "three four"])

    def test_hard_line_breaks(self):
        lines = md.layout("two spaces  \nbackslash\\\nend\\\\", 1000, measure)
        self.assertEqual(texts(lines), ["two spaces", "backslash", "end\\"])
        self.assertEqual(texts(md.layout("a<br>b", 1000, measure)), ["a", "b"])

    def test_paragraphs_are_separated_by_one_gap(self):
        lines = md.layout("First.\n\n\n\nSecond.\n\n", 1000, measure)
        self.assertEqual(kinds(lines), ["text", "gap", "text"], "no gap at the end")

    def test_headings_by_level(self):
        lines = md.layout("Intro.\n## What I changed ##\nBody.", 1000, measure)
        self.assertEqual(kinds(lines), ["text", "gap", "heading", "text"])
        self.assertEqual((lines[2].text, lines[2].level), ("𝗪𝗵𝗮𝘁 𝗜 𝗰𝗵𝗮𝗻𝗴𝗲𝗱", 2))
        source = "\n".join(f"{'#' * n} Head" for n in range(1, 7))
        headings = [line for line in md.layout(source, 1000, measure) if line.kind == "heading"]
        self.assertEqual([(line.level, line.text) for line in headings],
                         [(1, "𝗛𝗲𝗮𝗱"), (2, "𝗛𝗲𝗮𝗱"), (3, "𝗛𝗲𝗮𝗱"), (4, "𝗛𝗲𝗮𝗱"), (5, "𝗛𝗲𝗮𝗱"), (6, "𝘏𝘦𝘢𝘥")])
        self.assertEqual(md.layout("## C#", 1000, measure)[0].text, "𝗖#", "a # in the text stays")

    def test_list_items_hang_beside_their_marker(self):
        em = measure("M")
        lines = md.layout("- first item that wraps\n- second\n  - nested\n1. one\n2) two", 120, measure)
        step = md.INDENT_EMS * em
        self.assertEqual([(line.marker, line.indent) for line in lines],
                         [("•", step), ("", step), ("•", step), ("◦", 2 * step), ("1.", step), ("2)", step)])
        self.assertEqual(lines[0].text + " " + lines[1].text, "first item that wraps")
        self.assertTrue(all(measure(line.text) <= 120 - line.indent for line in lines))

    def test_task_lists_have_boxes(self):
        lines = md.layout("- [x] done\n- [ ] todo\n* [X] also\n- [y] not a task", 1000, measure)
        self.assertEqual([(line.marker, line.text) for line in lines],
                         [("🗹", "done"), ("☐", "todo"), ("🗹", "also"), ("•", "[y] not a task")])

    def test_a_list_after_a_paragraph_and_its_continuation(self):
        lines = md.layout("Done:\n* a lid\n  with hinges\nThat is all.", 1000, measure)
        self.assertEqual([(line.text, line.marker, bool(line.indent)) for line in lines],
                         [("Done:", "", False), ("a lid", "•", True), ("with hinges", "", True),
                          ("That is all.", "", False)])

    def test_code_blocks_keep_their_text(self):
        lines = md.layout("Ran:\n```python\nx = **1**\n\n  y = 2\n```\nok", 1000, measure)
        self.assertEqual([(line.kind, line.text) for line in lines],
                         [("text", "Ran:"), ("codehead", "python"), ("code", code_line("x = **1**")), ("code", ""),
                          ("code", code_line("  y = 2")), ("text", "ok")])
        self.assertEqual(lines[1].copy, "x = **1**\n\n  y = 2", "the head holds the code to copy, as written")
        self.assertEqual(md.layout("~~~ {.js}\nf()\n~~~", 1000, measure)[0].text, "js")
        long = md.layout("```\n" + "x" * 30 + "\n```", 1000, measure, code_width=60)
        self.assertEqual(texts(long), ["", *[code_line("x" * 10)] * 3], "a long code line is broken where its box ends")
        roomy = md.layout("```\n" + "x" * 30 + "\n```", 1000, measure, code_width=60, link_room=6, copy_room=12)
        self.assertEqual(texts(roomy)[1], code_line("x" * 8),
                         "without a language row, the code leaves copy_room for the copy button on its row")
        named = md.layout("```sh\n" + "x" * 30 + "\n```", 1000, measure, code_width=60, copy_room=12)
        self.assertEqual(texts(named)[1], code_line("x" * 10), "the button is on the language row")

    def test_indented_code_blocks(self):
        lines = md.layout("Run:\n\n    x = 1\n\n      y = *2*\nafter", 1000, measure)
        self.assertEqual([(line.kind, line.text) for line in lines],
                         [("text", "Run:"), ("gap", ""), ("codehead", ""), ("code", code_line("x = 1")), ("code", ""),
                          ("code", code_line("  y = *2*")), ("text", "after")])
        self.assertEqual(lines[2].copy, "x = 1\n\n  y = *2*")
        self.assertEqual(kinds(md.layout("    first", 1000, measure)), ["codehead", "code"], "at the start too")
        lines = md.layout("Para\n    still para", 1000, measure)
        self.assertEqual(kinds(lines), ["text", "text"], "not straight after a paragraph line")
        lines = md.layout("- item\n\n    more of the item", 1000, measure)
        self.assertEqual([(line.kind, bool(line.indent)) for line in lines],
                         [("text", True), ("gap", False), ("text", True)], "nor in a list")

    def test_quotes_nest_and_hold_blocks(self):
        step = md.INDENT_EMS * measure("M")
        lines = md.layout("> careful\n> - a list\n>> nested **bold**\n>>> deeper\n> ```\n> code\n> ```", 1000,
                          measure)
        self.assertEqual([(line.kind, line.text, line.marker, line.quote, line.indent) for line in lines],
                         [("text", "careful", "", 1, step), ("text", "a list", "•", 1, 2 * step),
                          ("text", "nested 𝗯𝗼𝗹𝗱", "", 2, 2 * step), ("text", "deeper", "", 3, 3 * step),
                          ("codehead", "", "", 1, step), ("code", code_line("code"), "", 1, step)])
        self.assertEqual(md.indent_step(measure), step)
        lines = md.layout("> # Title\n>\n> 1. one", 1000, measure)
        self.assertEqual([(line.kind, line.marker) for line in lines],
                         [("heading", ""), ("gap", ""), ("text", "1.")])
        self.assertNotIn(">", "".join(texts(lines)))

    def test_rules(self):
        lines = md.layout("a\n\n---\n***\nb", 1000, measure)
        self.assertEqual(kinds(lines), ["text", "gap", "rule", "rule", "text"])

    def test_tables_are_columns_of_cells(self):
        lines = md.layout("| a | b | c |\n|:--|:-:|--:|\n| 1 | **2** | `3` |\n| only |", 1000, measure,
                          code_width=990)
        self.assertEqual(kinds(lines), ["table"])
        table = lines[0].table
        self.assertEqual(table.aligns, ("LEFT", "CENTER", "RIGHT"))
        self.assertEqual(table.rows, ((("𝗮",), ("𝗯",), ("𝗰",)), (("1",), ("𝟮",), ("𝟹",)),
                                      (("only",), ("",), ("",))), "the header bold, a short row filled")
        pad = md.CELL_PAD_EMS * 6
        self.assertEqual(table.widths, (24 + pad, 6 + pad, 6 + pad), "columns as wide as their text")
        self.assertEqual(lines[0].height, 3)

    def test_a_wide_table_shares_the_width_and_wraps_its_cells(self):
        source = ("| id | description |\n|---|---|\n| 1 | " + "word " * 40 + "|\n"
                  "| x \\| y | `a|b` |")
        lines = md.layout(source, 300, measure, code_width=290)
        table = lines[0].table
        self.assertLessEqual(sum(table.widths), 290 + 0.01, "the table fits its box")
        self.assertEqual(table.widths[0], 5 * 6 + md.CELL_PAD_EMS * 6, "a narrow column keeps its width")
        description = table.rows[1][1]
        self.assertGreater(len(description), 1, "a long cell wraps in its column")
        self.assertTrue(all(measure(text) <= table.widths[1] for text in description))
        self.assertEqual(table.rows[2], (("x | y",), ("𝚊|𝚋",)), "escaped and code pipes are not cell edges")
        self.assertEqual(lines[0].height, 1 + len(description) + 1)
        self.assertTrue(table.fills, "a table that had to wrap takes the whole width")
        self.assertFalse(md.layout("| a | b |\n|---|---|\n| 1 | 2 |", 300, measure)[0].table.fills)

    def test_maths_blocks(self):
        lines = md.layout("Area:\n$$\\pi r^2$$\nand\n$$\n\\frac{1}{2}\n$$\n\\[ x_1 \\]", 1000, measure)
        self.assertEqual([(line.kind, line.text) for line in lines],
                         [("text", "Area:"), ("math", "π r²"), ("text", "and"), ("math", "1⁄2"), ("math", "x₁")])

    def test_details_become_a_section(self):
        source = ("Before\n<details><summary>More <b>info</b></summary>\n\nHidden **body**\n- item\n"
                  "<details><summary>Inner</summary>deep</details>\n</details>\nAfter")
        lines = md.layout(source, 1000, measure)
        self.assertEqual(kinds(lines), ["text", "details", "text"])
        section = lines[1]
        self.assertEqual(section.text, "More 𝗶𝗻𝗳𝗼")
        self.assertEqual([(line.kind, line.text) for line in section.body],
                         [("text", "Hidden 𝗯𝗼𝗱𝘆"), ("text", "item"), ("details", "Inner")])
        self.assertEqual(texts(section.body[2].body), ["deep"])
        self.assertEqual(md.layout("<details>\nno summary\n</details>", 1000, measure)[0].text, "Details")

    def test_footnotes(self):
        source = "Claim[^b] and another[^a], again[^b], unknown[^x].\n\n[^a]: First *note*\n  continued\n[^b]: Second"
        lines = md.layout(source, 1000, measure)
        self.assertEqual(lines[0].text, "Claim¹ and another², again¹, unknown[^x].",
                         "numbered by first reference")
        self.assertEqual([(line.kind, line.marker, line.text) for line in lines[1:]],
                         [("gap", "", ""), ("rule", "", ""), ("note", "¹", "Second"),
                          ("note", "²", "First 𝘯𝘰𝘵𝘦 continued")])
        self.assertEqual(texts(md.layout("```\n[^a]: code\n```", 1000, measure)), ["", code_line("[^a]: code")])

    def test_links_on_their_lines(self):
        lines = md.layout("one [two](https://t.wo) three four five [six](https://s.ix)", 70, measure,
                          link_room=10)
        self.assertEqual([(md.plain(line.text), line.link) for line in lines],
                         [("one two", "https://t.wo"), ("three four", ""), ("five six", "https://s.ix")])
        self.assertTrue(all(measure(line.text) <= 60 for line in lines), "room left for the button")
        lines = md.layout("Read [a](https://a.com) and [b c](https://b.com) now.", 1000, measure, link_room=10)
        self.assertEqual(lines[0].links, (("a", "https://a.com"), ("b c", "https://b.com")), "every link on a line")
        self.assertEqual(md.layout("no links here at all", 80, measure, link_room=10)[0].text,
                         "no links here", "no room taken without a link")
        wrapped = md.layout("see https://en.wikipedia.org/wiki/Some_long_article_name_here now", 120, measure,
                            link_room=10)
        self.assertGreater(len(wrapped), 1)
        self.assertEqual([bool(line.links) for line in wrapped].count(True), 1,
                         "a link that wraps has one button, on the line where it starts")

    def test_html_blocks_and_emoji_in_code(self):
        lines = md.layout('<div align="center">\n\nText\n\n</div>', 1000, measure)
        self.assertEqual(kinds(lines), ["text"], "a line that is only a tag is no line")
        self.assertEqual(texts(md.layout("```\nok ✅️\n```", 1000, measure)), ["", code_line("ok ✅")],
                         "monospace, emoji cleaned")

    def test_an_empty_text(self):
        self.assertEqual(md.layout("", 100, measure), [], "nothing to draw")


if __name__ == "__main__":
    unittest.main()
