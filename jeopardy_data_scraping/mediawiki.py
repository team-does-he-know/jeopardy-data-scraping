from datetime import date
from enum import IntEnum, StrEnum
from re import IGNORECASE, MULTILINE, compile

from mwparserfromhell import parse as parse_wikitext

# Title prefix used for Wikipedia's Level 5 Vital Articles curation pages.
VITAL_ARTICLES_TITLE_PREFIX = "Wikipedia:Vital articles/Level/5"

# Link namespaces for embedded files and categories to remove during rendering.
IGNORED_LINK_PREFIXES = (
    "category:",
    "file:",
    "image:",
    "media:",
)

# Pattern matching trailing reference, bibliography, and external link sections.
TRAILING_SECTION_PATTERN = compile(
    r"^==+\s*(?:See also|Notes|References|Further reading|External links|Sources|Citations)\s*==+.*",
    IGNORECASE | MULTILINE,
)

# Date format strings indexed by number of date components (year, year-month, year-month-day).
DATE_FORMATS = ("%Y", "%B %Y", "%B %-d, %Y")


class MediaWikiNamespace(IntEnum):
    """MediaWiki integer namespace identifiers."""

    MAIN = 0
    PROJECT = 4


class MediaWikiContentModel(StrEnum):
    """MediaWiki revision content model identifiers."""

    WIKITEXT = "wikitext"


def normalize_template_name(raw_name):
    """Normalizes MediaWiki template names by replacing underscores and collapsing whitespace."""
    return " ".join(raw_name.replace("_", " ").lower().split())


def extract_parameter(template, *keys):
    """Returns the value of the first matching parameter key present in the template."""
    for key in keys:
        if template.has(key):
            return template.get(key).value

    return None


def extract_joined_parameters(template, max_params=None, separator=" ", min_count=1):
    """Joins positional template parameters up to max_params with a separator."""
    items = [
        text
        for param in template.params[:max_params]
        if not param.showkey and (text := str(param.value).strip())
    ]

    return separator.join(items) if len(items) >= min_count else None


def extract_date(template):
    """Extracts and formats year, month, and day parameters from date templates."""
    parts = [
        int(text)
        for index in (1, 2, 3)
        if template.has(index)
        and (text := str(template.get(index).value).strip()).isdigit()
    ]

    if not parts:
        return None

    try:
        return date(*(parts + [1, 1])[:3]).strftime(DATE_FORMATS[len(parts) - 1])
    except ValueError:
        return str(parts[0])


def extract_template_value(template):
    """Extracts display text or values from supported inline Wikipedia templates."""
    match normalize_template_name(str(template.name)):
        case (
            "abbr"
            | "blockquote"
            | "chem2"
            | "code"
            | "flatlist"
            | "math"
            | "mono"
            | "mvar"
            | "nihongo"
            | "nihongo2"
            | "nihongo3"
            | "nihongo foot"
            | "nihongo-foot"
            | "nihongofoot"
            | "nihongo-s"
            | "nobr"
            | "nowrap"
            | "plainlist"
            | "quote"
            | "small"
        ):
            return extract_parameter(template, 1)

        case (
            "bda"
            | "birth date"
            | "birth date and age"
            | "dda"
            | "death date"
            | "death date and age"
            | "end date"
            | "film date"
            | "release date"
            | "start date"
            | "start date and age"
        ):
            return extract_date(template)

        case "chem":
            return extract_joined_parameters(template, separator="")

        case "convert" | "cvt":
            return extract_joined_parameters(template, max_params=2, min_count=2)

        case "hlist" | "ubl" | "unbulleted list":
            return extract_joined_parameters(template, separator=", ")

        case "ill" | "interlanguage link" | "interlanguage link multi":
            return extract_parameter(template, "lt", 1)

        case "lang" | "langx" | "sort":
            return extract_parameter(template, 2)

        case "sortname":
            return extract_joined_parameters(template, max_params=2)

        case "transl":
            return extract_parameter(template, 3)

        case name if name.startswith("lang-"):
            return extract_parameter(template, 1)

        case _:
            return None


def extract_cell_text(cell_node):
    """Extracts and normalizes whitespace for text within a table cell."""
    if not cell_node.contents:
        return ""

    return " ".join(
        cell_node.contents.strip_code(normalize=True, collapse=True).split()
    )


def extract_table_text(table_node):
    """Converts a Wikitext table Tag node into pipe-delimited plain text rows."""
    if not table_node.contents:
        return ""

    rows = []
    for row_node in table_node.contents.filter_tags(
        matches=lambda node: node.tag == "tr", recursive=False
    ):
        if not row_node.contents:
            continue

        cells = [
            text
            for cell in row_node.contents.filter_tags(
                matches=lambda node: node.tag in ("th", "td"), recursive=False
            )
            if (text := extract_cell_text(cell))
        ]

        if cells:
            rows.append(" | ".join(cells))

    return f"\n{'\n'.join(rows)}\n" if rows else ""


def render_wikitext_to_plaintext(raw_wikitext):
    """Converts raw Wikitext into clean plain text with inline templates and tables preserved."""
    body_wikitext = TRAILING_SECTION_PATTERN.split(raw_wikitext, maxsplit=1)[0]
    wikicode = parse_wikitext(body_wikitext)

    for link in wikicode.filter_wikilinks():
        if str(link.title).strip().lower().startswith(IGNORED_LINK_PREFIXES):
            wikicode.remove(link)

    for template in reversed(wikicode.filter_templates()):
        replacement = extract_template_value(template)

        if replacement is not None:
            wikicode.replace(template, replacement)

    for table in reversed(
        wikicode.filter_tags(matches=lambda node: node.tag == "table")
    ):
        wikicode.replace(table, extract_table_text(table))

    plain_text = wikicode.strip_code(normalize=True, collapse=True)

    return "\n\n".join(
        stripped_line
        for line in plain_text.splitlines()
        if (stripped_line := line.strip())
    )
