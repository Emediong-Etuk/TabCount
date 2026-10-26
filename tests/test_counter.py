import cv2
import numpy as np
import pytest

from app.baseline import baseline_count
from app.counter import CountParams, InvalidImageError, count_tablets
from tools.synthetic import Scene, Tablet, encode, grid_scene, pairs_scene, render_scene

STAGES = {"decode", "preprocess", "segment", "watershed", "postprocess", "annotate", "total"}


def _png(scene, seed=1, degrade=True):
    return encode(render_scene(scene, np.random.default_rng(seed), degrade=degrade))


def test_opencv_is_version_5():
    assert cv2.__version__.startswith("5")


@pytest.mark.parametrize("background,polarity", [("dark", "light_on_dark"), ("light", "dark_on_light")])
def test_separated_tablets_exact(background, polarity):
    res = count_tablets(_png(grid_scene(12, background)))
    assert res.count == 12
    assert res.segments == 12
    assert res.polarity == polarity
    assert res.confidence == "high"


@pytest.mark.parametrize("background", ["dark", "light"])
def test_touching_pairs_split_by_watershed(background):
    data = _png(pairs_scene(5, background, overlap=0.05))
    res = count_tablets(data)
    assert res.count == 10
    assert res.clusters_flagged == 0
    # the naive contour counter merges each touching pair
    assert baseline_count(data) < 10


def _scene_with_cluster():
    sc = grid_scene(9, "dark", r=26)
    t = sc.tablets[4]
    # Replace the centre tablet by two heavily overlapping tablets (one blob ~2x area).
    sc.tablets[4] = Tablet(t.cx - 20, t.cy, 26, 26, 0, t.color)
    sc.tablets.append(Tablet(t.cx + 20, t.cy, 26, 26, 0, t.color))
    return sc


def test_cluster_is_flagged_and_corrected():
    res = count_tablets(_png(_scene_with_cluster()))
    flagged = [o for o in res.objects if o["flagged"]]
    assert len(flagged) == 1
    assert flagged[0]["est_units"] == 2
    assert res.segments == 9
    assert res.count == 10
    assert res.confidence in ("medium", "low")
    off = count_tablets(_png(_scene_with_cluster()), CountParams(cluster_correction=False))
    assert off.count == 9


def test_debris_removed():
    sc = grid_scene(12, "dark", r=28)
    col = sc.tablets[0].color
    # crumbs: small fragments well below 25% of the median tablet area
    for i, (x, y) in enumerate([(60, 40), (1150, 860), (600, 880), (30, 450)]):
        sc.tablets.append(Tablet(x, y, 7, 6, i * 30, col))
    res = count_tablets(_png(sc))
    assert res.count == 12
    assert res.debris_removed > 0


def test_blank_image_no_tablets():
    img = np.full((900, 1200, 3), 40, np.uint8)
    res = count_tablets(encode(img))
    assert res.count == 0
    assert "no_tablets_found" in res.warnings
    assert res.confidence == "low"


def test_undecodable_bytes_raise():
    with pytest.raises(InvalidImageError):
        count_tablets(b"this is definitely not an image")
    with pytest.raises(InvalidImageError):
        count_tablets(b"")


def test_result_contents(grid12_png):
    res = count_tablets(grid12_png, debug=True)
    assert STAGES <= set(res.timings_ms)
    img = cv2.imdecode(np.frombuffer(res.annotated_jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[1] == res.image["proc_w"]
    assert {"mask", "distance", "seeds", "labels", "annotated"} <= set(res.debug_images)
    d = res.to_dict()
    assert d["opencv_version"].startswith("5")
    assert "annotated_jpeg" not in d
    assert len(d["objects"]) == 12
    o = d["objects"][0]
    assert {"id", "area", "centroid", "bbox", "flagged", "est_units"} <= set(o)


def test_resize_never_upscales():
    small = encode(render_scene(Scene([], "dark", (40, 40, 40), 400, 300), degrade=False))
    res = count_tablets(small)
    assert res.image["proc_w"] == 400 and res.image["scale"] == 1.0


def test_12mp_photo_under_one_second():
    from tools.synthetic import random_scene
    rng = np.random.default_rng(5)
    scene = random_scene(rng, 40, "dark", "mixed", width=4000, height=3000)
    data = encode(render_scene(scene, rng, degrade=False), ".jpg", 92)
    count_tablets(data)  # warm-up
    res = count_tablets(data)
    assert res.image["orig_w"] == 4000 and res.image["proc_w"] == 1200
    assert res.timings_ms["total"] < 1000
    assert res.count == len(scene.tablets)
