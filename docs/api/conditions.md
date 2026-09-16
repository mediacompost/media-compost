# Building conditions

The condition models a query tree is made of — what `parse_query` returns and
what `lib.query()` takes when the conditions come from variables rather than
from a string. Building them directly means no escaping to get right:

```python
from media_compost import QueryGroup, TagCond, MetaCond

lib.query(QueryGroup(op="and", children=[
    TagCond(name="portrait"),
    MetaCond(name="width", op=">=", value=1024),
]))
```

The trees are Pydantic models and are the same wire format the app itself
speaks, so a tree that works here works in a saved search and vice versa.
(`Group` is exported as `QueryGroup` — the top level already has a `Group`
handle for the library's groups.)

::: media_compost.query
