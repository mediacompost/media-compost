# Importing

Bringing files in — from paths or from bytes. Both take the identical pipeline
the web upload takes: duplicate detection, metadata indexing, GPS places,
rotation, archives and sequences.

The entry points live on [`Library`][media_compost.library.Library]:
[`lib.import_file(path)`][media_compost.library.Library.import_file] /
[`lib.import_bytes(data, name)`][media_compost.library.Library.import_bytes]
for one source,
[`lib.import_all(sources)`][media_compost.library.Library.import_all] for a
list, and [`lib.importing()`][media_compost.library.Library.importing] for a
run that takes sources one at a time — a crawler, an archive reader.
Everything they answer with is on this page, along with the source and option
types they accept.

::: media_compost.library.importing

## The source and option types

What an import call takes: a source is a path or an
[`ImportBytes`][media_compost.importer.ImportBytes], and the keyword options
every entry point accepts are [`ImportOptions`][media_compost.importer.ImportOptions]'
fields.

::: media_compost.importer.ImportSource
    options:
      heading_level: 3

::: media_compost.importer.ImportBytes
    options:
      heading_level: 3

::: media_compost.importer.ImportOptions
    options:
      heading_level: 3

::: media_compost.importer.ImportStats
    options:
      heading_level: 3
