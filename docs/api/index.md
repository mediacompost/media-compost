# API reference

This reference is **generated from the source** by
[mkdocstrings](https://mkdocstrings.github.io/) every time the site is built, so
it describes the code as it actually is rather than as somebody last remembered
to write it down. Every class, method and property below is read out of
`media_compost/library/` and its docstrings.

It is the exhaustive half. The other half is [Python API](../python-api.md) —
the guide: what to reach for first, what the three or four calls you actually
need are, and why the API is shaped the way it is. Start there; come here for
the signature of the thing you already know you want.

## The map

| page | what is in it |
|---|---|
| [Opening a library](library.md) | `open_library`, `Library` — the way in |
| [Items and tag set](handles.md) | `Item`, `File`, `Tag`, `Group`, `Subject`, `Place`, `Event`, `Face`, `Caption`, … |
| [Collections](collections.md) | what `item.tags` and `lib.groups` hand back |
| [Querying](query.md) | `ItemSet` — lazy, composable, the app's own search |
| [Building conditions](conditions.md) | the condition models, for when the query comes from variables |
| [Importing](importing.md) | paths and bytes, through the app's own pipeline |
| [History](history.md) | the log, and the way back from a mistake |
| [Settings](settings.md) | what shapes the library rather than a view of it |
| [Value types](values.md) | `PartialDate`, `Rect`, `TimeRange`, `Phash`, … |
| [Errors](errors.md) | everything the API raises |

## A note on what is public

`media_compost` re-exports the names you construct or catch — the handles,
the value types, the condition models, the errors — at the top level, and that
is the import path to use:

```python
from media_compost import open_library, TagCond, PartialDate
```

The classes you only ever *receive* (a history `Change`, the `Settings`
bundle, the collection types) live under `media_compost.library`; you never
need to import them to use them.

Anything not listed here is internal, whatever its import path looks like. The
service layer (`media_compost.ops`) and the ORM (`media_compost.db`) are not
part of the public API and change without notice — see
[Compatibility](../compatibility.md) for what is a promise and what is not.
