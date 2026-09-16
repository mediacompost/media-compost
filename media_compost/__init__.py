"""Media Compost — deduplicating media library and dataset builder."""

__version__ = "1.0.2.dev0"

# The public scripting API. Open a library, query it, read and edit everything
# the app can, import files — see `media_compost.library` for the tour.
from .library import (  # noqa: E402
    NEVER,
    AmbiguousName,
    Appearance,
    Artifact,
    Box,
    Caption,
    ConflictError,
    DuplicateName,
    Event,
    Face,
    File,
    FileSource,
    Group,
    GroupCycleError,
    GroupedTags,
    ImportFailed,
    ImportEntry,
    ImportResult,
    ImportStatus,
    ImportRun,
    InvalidDate,
    InvalidLink,
    InvalidTagName,
    Item,
    ItemSet,
    ItemTagGroup,
    Library,
    LibraryError,
    LibraryVersionError,
    Link,
    MediaCompostError,
    MediaUnreadable,
    MetaTag,
    NotFound,
    ObjectDeleted,
    PartialDate,
    Phash,
    Place,
    ReadOnlyError,
    Rect,
    Sequence,
    Subject,
    Tag,
    TextRegion,
    TimeRange,
    UnsupportedOperation,
    ValidationError,
    codec_roundtrip,
    default_data_dir,
    encoder_available,
    open_library,
)

# The condition models a query tree is made of. A query STRING is the short
# way in, but these stay exported: they are the wire format, and a caller
# generating conditions programmatically wants them — with no escaping to get
# right, which is the one thing a string cannot offer.
from .query import (  # noqa: E402
    CaptionCond, EventCond, Group as QueryGroup, GroupCond, LinkCond,
    LinkTagRef, MetaCond, PlaceCond, prune_unknown as prune_query,
    SimilarCond, SubjectCond, TagCond, TakenCond, ValueCond,
)
# The `<name>:<number><unit>` value-tag convention, exported here because the
# trainer's manifest builder resolves value RULES to a finished tag→text map
# and `media_compost.train` may import only `media_compost` (the import
# contract) — the same door `prune_query` goes through.
from .tagvalue import matches as tag_value_matches  # noqa: E402
from .importer import ImportBytes, ImportOptions, ImportStats  # noqa: E402
from .instance import (  # noqa: E402
    JOBS_LOCK_NAME,
    TRAINING_LOCK_NAME,
    LockBusy,
    scheduler_lease,
    write_lease,
)
from .querystring import parse as parse_query, serialize as serialize_query  # noqa: E402
from .tagname import normalize as normalize_tag  # noqa: E402

__all__ = [
    # opening and querying
    "open_library", "Library", "ItemSet",
    "parse_query", "serialize_query",
    # handles
    "Item", "File", "FileSource", "Artifact", "Tag", "MetaTag", "Group",
    "Subject", "Place", "Event", "Face", "Appearance", "Caption", "Link",
    "Sequence", "ItemTagGroup", "Box", "TextRegion",
    # values
    "NEVER", "PartialDate", "Phash", "Rect", "TimeRange", "GroupedTags",
    "normalize_tag",
    # pixels, without the library
    "codec_roundtrip", "encoder_available", "default_data_dir",
    # importing
    "ImportEntry", "ImportResult", "ImportRun", "ImportStatus", "ImportBytes", "ImportOptions",
    "ImportStats",
    # condition models
    "QueryGroup", "TagCond", "LinkCond", "LinkTagRef", "MetaCond",
    "SubjectCond", "PlaceCond", "GroupCond", "CaptionCond", "EventCond",
    "TakenCond", "SimilarCond", "ValueCond", "prune_query",
    "tag_value_matches",
    # errors
    "MediaCompostError", "LibraryError", "LibraryVersionError",
    "ReadOnlyError", "NotFound", "ObjectDeleted",
    "AmbiguousName", "ValidationError", "InvalidTagName", "InvalidDate",
    "ConflictError", "DuplicateName", "GroupCycleError", "InvalidLink",
    "ImportFailed", "UnsupportedOperation", "MediaUnreadable",
]
