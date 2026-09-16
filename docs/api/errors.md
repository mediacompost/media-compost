# Errors

Everything the API raises descends from
[`MediaCompostError`][media_compost.library.errors.MediaCompostError] — with
the exceptions ordinary Python has claims on: a malformed query *string*
raises `ValueError` from the parser, a malformed condition *model* raises
pydantic's `ValidationError`, and a wrong argument type raises `TypeError`,
as everywhere in Python.

::: media_compost.library.errors
