"""Step 2 must add scenes in the same order on every file system."""
import itertools

import pytest

# Upper-left corners of three overlapping strips (EPSG:3826).
DEMO = {
    "a0000001.img": (200500.0, 2681000.0),
    "a0000003.img": (205500.0, 2680500.0),
    "a0000005.img": (210500.0, 2680000.0),
}


@pytest.mark.parametrize("listing", list(itertools.permutations(DEMO)))
def test_order_does_not_depend_on_listing(step2, listing):
    coords = [DEMO[n] for n in listing]
    assert step2.scene_read_order(listing, coords) == [
        "a0000001.img", "a0000003.img", "a0000005.img"]


@pytest.mark.parametrize("listing", list(itertools.permutations(DEMO)))
@pytest.mark.parametrize("start", ["a0000003", "a0000003.img"])
def test_start_scene(step2, listing, start):
    coords = [DEMO[n] for n in listing]
    order = step2.scene_read_order(listing, coords, start)
    assert order[0] == "a0000003.img"
    assert sorted(order) == sorted(DEMO)


def test_ties_keep_alphabetical_order(step2):
    names = ["c.img", "b.img", "a.img"]
    coords = [(10.0, 0.0), (-10.0, 0.0), (0.0, 0.0)]
    assert step2.scene_read_order(names, coords) == ["a.img", "b.img", "c.img"]
    assert step2.scene_read_order(names, coords, "c") == ["c.img", "a.img", "b.img"]


def test_start_scene_keeps_first_place_on_shared_corner(step2):
    names = ["a.img", "b.img"]
    coords = [(0.0, 0.0), (0.0, 0.0)]
    assert step2.scene_read_order(names, coords, "b") == ["b.img", "a.img"]


def test_unknown_start_scene(step2):
    with pytest.raises(ValueError, match="startScene"):
        step2.scene_read_order(["a.img", "b.img"], [(0, 0), (1, 1)], "z")
