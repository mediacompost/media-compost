# Items and tag set

Every object here is a **live handle**: it holds a library and a primary key,
re-reads when the library changes underneath it, and raises
[`ObjectDeleted`][media_compost.library.errors.ObjectDeleted] rather than
answering with stale data. Assigning to a property is the edit.

::: media_compost.library.handles
