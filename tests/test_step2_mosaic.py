"""Unit tests for the seamline and blending helpers in Step 2."""
import numpy as np
import pytest


def test_add_at_pos_inside(step2):
    canvas = np.zeros((5, 5))
    step2.add_at_pos(canvas, np.ones((2, 3)), (1, 2))
    assert canvas.sum() == 6
    assert canvas[2:4, 1:4].all()


def test_add_at_pos_clips_off_edges(step2):
    canvas = np.zeros((4, 4))
    out = step2.add_at_pos(canvas, np.ones((3, 3)), (-1, 2), inPlace=False)
    assert canvas.sum() == 0  # original untouched
    assert out.sum() == 4     # only the 2x2 overlap is added
    assert out[2:4, 0:2].all()


@pytest.mark.parametrize("position", [
    (5, 0), (6, 0), (0, 5), (0, 6), (6, 6),
    (-3, 0), (-4, 0), (0, -3), (0, -4), (-4, -4),
])
@pytest.mark.parametrize("in_place", [True, False])
def test_add_at_pos_without_overlap(step2, position, in_place):
    """An entirely off-canvas source leaves the destination unchanged."""
    original = np.arange(25).reshape(5, 5)
    canvas = original.copy()
    source = np.ones((3, 3), dtype=canvas.dtype)

    result = step2.add_at_pos(canvas, source, position, inPlace=in_place)

    np.testing.assert_array_equal(canvas, original)
    np.testing.assert_array_equal(source, 1)
    if in_place:
        assert result is None
    else:
        assert not np.shares_memory(result, canvas)
        np.testing.assert_array_equal(result, original)


def test_spiral_starts_at_origin_and_is_unique(step2):
    pts = step2.spiral(5, 5)
    assert pts[0] == [0, 0]
    assert len(pts) == 25
    assert len({tuple(p) for p in pts}) == 25
    # neighbours of the origin come before anything farther away
    assert {tuple(p) for p in pts[1:9]} == {
        (dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)
    }


def test_bfs_finds_shortest_path_around_wall(step2):
    grid = [
        [0, 0, 0, 0],
        [9, 9, 9, 0],
        [2, 0, 0, 0],
    ]
    path = step2.bfs(grid, (0, 0), wall=9, clear=0, goal=2, width=4, height=3)
    assert path[0] == (0, 0)
    assert path[-1] == (0, 2)
    assert len(path) == 9  # 3 right, 2 down, 3 left
    assert all(grid[y][x] != 9 for x, y in path)


def test_bfs_returns_none_when_unreachable(step2):
    grid = [[0, 9, 2]]
    assert step2.bfs(grid, (0, 0), 9, 0, 2, 3, 1) is None


def test_blend_mask_is_feathered(step2):
    mask = np.zeros((41, 41), dtype=np.uint8)
    mask[:, 20:] = 1
    blended = step2.blendMask(11, mask)
    assert blended.dtype == np.float32
    assert blended.min() >= 0 and blended.max() <= 1
    row = blended[20]
    assert row[0] == 0 and row[-1] == 1
    assert 0 < row[20] < 1          # soft transition across the seam
    assert np.all(np.diff(row) >= 0)


def test_build_graph_seamline_follows_low_cost_edge(step2):
    """The seamline should run along the column where the two images differ least.

    Edge weights are inverse image gradients, so the cheapest path lies along
    strong gradients in both images; here a vertical edge at column 4.
    """
    h, w = 9, 9
    img = np.full((h, w), 10, dtype=np.uint8)
    img[:, 5:] = 200
    source = 0 * w + 4 + 1          # node ids are 1-based, row-major
    target = (h - 2) * w + 4 + 1
    seam = step2.buildGraph(img, img.copy(), h, w, "a7c", (source, target))
    assert seam.shape == (h, w)
    rows, cols = np.nonzero(seam)
    assert seam[0, 4] == 1 and seam[h - 2, 4] == 1
    assert set(cols) <= {4, 5}
    assert set(range(h - 1)) <= set(rows)


def test_build_graph_links_every_pixel_to_its_right_and_down_neighbours(step2, monkeypatch):
    """Every valid pixel gets an edge to its right and lower neighbour.

    Node ids are 1-based and row-major with ``width`` columns, so only the last
    column (x % width == 0) and the last row lack a right or down neighbour.
    A height that does not divide the width checks that no other nodes are
    skipped (issue #3: an extra ``x % height != 0`` condition dropped them).
    """
    graphs = []
    astar_path = step2.nx.astar_path

    def spy(G, *args, **kwargs):
        graphs.append(G)
        return astar_path(G, *args, **kwargs)

    monkeypatch.setattr(step2.nx, "astar_path", spy)
    h, w = 3, 4
    img = np.arange(1, h * w + 1, dtype=np.uint8).reshape(h, w)
    step2.buildGraph(img, img.copy(), h, w, "a7", (1, h * w))

    expected = set()
    for x in range(1, h * w + 1):
        if x % w != 0:
            expected.add(frozenset((x, x + 1)))
        if x <= (h - 1) * w:
            expected.add(frozenset((x, x + w)))
    assert {frozenset(e) for e in graphs[0].edges()} == expected


@pytest.mark.parametrize("point_wkt, expected", [
    ("POINT (213456 2650000)", (213456, 2650000)),
    ("POINT (213456.5 2650003.25)", (213456.5, 2650003.25)),   # fractional (#27)
    ("POINT (1213456 2650000)", (1213456, 2650000)),           # 7-digit x (#27)
    ("POINT (98765 2650000)", (98765, 2650000)),               # 5-digit x (#27)
    ("LINESTRING (213456 2650000, 213460 2650010)", (213456, 2650000)),
    ("POINT EMPTY", None),
    ("MULTIPOINT ((1 2), (3 4))", None),
])
def test_wkt_point_xy(step2, point_wkt, expected):
    assert step2.wkt_point_xy(point_wkt) == expected


def test_make_true_id_with_fractional_seven_digit_coordinates(step2):
    """Endpoints with decimals and a 7-digit x map to the right pixels (#27)."""
    img = np.ones((20, 20), dtype=np.uint8)
    res, x0, y0 = 6.0, 1213450.0, 2650060.0
    gt = (res, 0.0, x0, 0.0, -res, y0)
    points = ["POINT (1213456.5 2650003.25)", "POINT (1213500 2650000)"]
    fc, fr, ids = step2.MakeTrueID(points, img, img.copy(), gt, res, 1)
    assert fc == [1, 8]                       # round((x - x0) / res)
    assert fr == [9, 10]                      # round((y0 - y) / res)
    assert ids == [9 * 20 + 1 + 1, 10 * 20 + 8 + 1]


def test_polygonize_valid_area_outlines_footprint(step2, tmp_path):
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin

    data = np.zeros((2, 50, 60), np.uint16)
    data[:, 10:40, 5:45] = 500
    tif = tmp_path / "scene.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=60, height=50, count=2, dtype="uint16",
                       crs="EPSG:3826", transform=from_origin(1000, 2000, 10, 10)) as dst:
        dst.write(data)
    step2.polygonize_valid_area(str(tif))
    shp = gpd.read_file(tmp_path / "scene.temp.shp")
    assert len(shp) == 1
    assert shp.area.iloc[0] == 30 * 40 * 10 * 10
    assert shp.total_bounds.tolist() == [1050, 1600, 1450, 1900]


def test_blend_region_must_exist(step2):
    # A seamline that does not split the overlap leaves the flood fill empty.
    # Blending with that empty mask would silently keep only one image, so
    # Step 2 stops with a message naming both images (follow-up to #91).
    with pytest.raises(ValueError, match="a0000003.img and mosaic_xs.tif"):
        step2.require_blend_region(np.zeros((5, 5), np.uint8), "a0000003.img", "mosaic_xs.tif")
    step2.require_blend_region(np.eye(5, dtype=np.uint8), "a0000001.img", "a0000003.img")


def test_both_blend_mask_builders_check_for_a_blend_region(step2):
    import inspect
    source = inspect.getsource(step2.main)
    assert source.count("require_blend_region(im_floodfill, image1_ds, image2_ds)") == 2


def _boundary_tool(directory, with_bin):
    tool = directory / "NSPO_GRID_vectorization"
    tool.mkdir()
    (tool / "GetBoundaryMask.exe").write_bytes(b"")
    (tool / "BndPolygonize_v.bat").write_text("")
    if with_bin:
        (tool / "bin").mkdir()
        (tool / "bin" / "gdalinfo.exe").write_bytes(b"")
    return tool


def test_shipped_boundary_tool_alone_falls_back_to_python(step2, tmp_path, monkeypatch):
    # The repository ships only GetBoundaryMask.exe and the .bat. On Windows
    # without the batch file's bin\ toolkit, Step 2 must use its Python
    # polygonizer rather than run a .bat that cannot work.
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin

    data = np.zeros((1, 20, 30), np.uint16)
    data[:, 5:15, 5:25] = 500
    tif = tmp_path / "scene.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=30, height=20, count=1, dtype="uint16",
                       crs="EPSG:3826", transform=from_origin(1000, 2000, 10, 10)) as dst:
        dst.write(data)
    _boundary_tool(tmp_path, with_bin=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(step2, "MATLAB_RUNTIMES", [str(runtime)])
    monkeypatch.setattr(step2, "on_windows", lambda: True)
    monkeypatch.setattr(step2, "run_tool", lambda args: pytest.fail(f"ran {args}"))
    step2.polygonize_valid_area(str(tif))
    assert gpd.read_file(tmp_path / "scene.temp.shp").area.iloc[0] == 10 * 20 * 10 * 10


def test_complete_boundary_tool_is_used_only_on_windows_with_matlab(step2, tmp_path, monkeypatch):
    tool = _boundary_tool(tmp_path, with_bin=True)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(step2, "MATLAB_RUNTIMES", [str(runtime)])
    monkeypatch.setattr(step2, "on_windows", lambda: True)
    assert step2.original_boundary_tool_available(tool)
    monkeypatch.setattr(step2, "MATLAB_RUNTIMES", [str(tmp_path / "no-matlab")])
    assert not step2.original_boundary_tool_available(tool)
    monkeypatch.setattr(step2, "MATLAB_RUNTIMES", [str(runtime)])
    monkeypatch.setattr(step2, "on_windows", lambda: False)
    assert not step2.original_boundary_tool_available(tool)
