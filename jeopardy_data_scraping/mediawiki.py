from enum import IntEnum, StrEnum

# Title prefix identifying Vital Articles index and sub-list pages.
VITAL_ARTICLES_TITLE_PREFIX = "Wikipedia:Vital articles/"


class MediaWikiNamespace(IntEnum):
    """MediaWiki namespace IDs used during extraction."""

    MAIN = 0
    PROJECT = 4


class MediaWikiContentModel(StrEnum):
    """MediaWiki revision content models."""

    WIKITEXT = "wikitext"
