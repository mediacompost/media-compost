"""The group-path rule, stated as cases."""
from __future__ import annotations

from media_compost import grouppath as gp

# Trips/2024, Work/2024, a group actually called "a/b", a root "2024" and a
# loose Paris under Trips/2024.
NAMES = {1: "Trips", 2: "2024", 3: "Work", 4: "2024", 5: "a/b", 6: "Paris",
         7: "2024"}
PARENT = {2: 1, 4: 3, 6: 2}


def test_a_path_reads_coarsest_first_and_lowercased():
    assert gp.path_of(6, NAMES, PARENT) == ["trips", "2024", "paris"]
    assert gp.path_of(1, NAMES, PARENT) == ["trips"]


def test_a_bare_name_is_the_root_level_group_of_that_name():
    """Owner 2026-09: a group is identified by its whole path, so a bare
    name means the group at the ROOT and never the ones sharing the name
    deeper down — `GROUP:abc` beside a `foo/abc` used to find both."""
    assert gp.matching_ids("2024", NAMES, PARENT) == {7}
    assert gp.matching_ids("trips", NAMES, PARENT) == {1}
    assert gp.matching_ids("paris", NAMES, PARENT) == set()
    assert gp.matching_ids("nothing", NAMES, PARENT) == set()


def test_a_path_is_the_whole_address():
    assert gp.matching_ids("Trips/2024", NAMES, PARENT) == {2}
    assert gp.matching_ids("Work/2024", NAMES, PARENT) == {4}
    assert gp.matching_ids("Trips/2024/Paris", NAMES, PARENT) == {6}
    # A TAIL is not enough any more: the address is the path from the root.
    assert gp.matching_ids("2024/Paris", NAMES, PARENT) == set()
    # ... and a path nothing carries finds nothing rather than falling back.
    assert gp.matching_ids("Work/2024/Paris", NAMES, PARENT) == set()
    assert gp.matching_ids("Holidays/2024", NAMES, PARENT) == set()


def test_case_and_stray_separators_are_ignored():
    assert gp.split(" Trips / 2024 ") == ["trips", "2024"]
    assert gp.split("/Trips//2024/") == ["trips", "2024"]
    assert gp.split("") == []
    assert gp.matching_ids(" TRIPS / 2024 ", NAMES, PARENT) == {2}


def test_the_whole_value_is_tried_as_a_path_too():
    """There is no escape syntax for a "/" in a name, deliberately — so a
    root group really called "a/b" goes on matching `GROUP:a/b`."""
    assert gp.matching_ids("a/b", NAMES, PARENT) == {5}


def test_hit_reads_the_same_rule_off_a_set_of_paths():
    paths = frozenset({"trips/2024", "a/b", "2024"})
    assert gp.hit("Trips/2024", paths)
    assert gp.hit("2024", paths)
    assert gp.hit("a/b", paths)
    assert not gp.hit("2024/paris", paths)
    assert not gp.hit("", paths)


def test_a_cycle_stops_rather_than_hanging():
    """The API refuses one; a restored folder need not."""
    names = {1: "A", 2: "B"}
    parent = {1: 2, 2: 1}
    assert gp.path_of(1, names, parent) in (["b", "a"], ["a", "b"])
