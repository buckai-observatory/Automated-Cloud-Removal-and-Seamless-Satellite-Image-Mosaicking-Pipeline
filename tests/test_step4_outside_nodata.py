"""Step 4 leaves the mosaic's no-data outside every scene as no-data."""

import numpy as np


def test_multiband_pixels_outside_every_scene_stay_zero(step4):
    mosaic = np.array([[[0, 5, 5]], [[0, 0, 6]]])        # pixel 0: 0 in every band
    blended = np.array([[[7, 8, 9]], [[7, 8, 9]]])
    step4.keep_outside_nodata(blended, mosaic)
    np.testing.assert_array_equal(blended, [[[0, 8, 9]], [[0, 8, 9]]])


def test_pixel_with_data_in_some_band_is_kept(step4):
    # Only pixels with 0 in every band are outside the scenes.
    mosaic = np.array([[[0]], [[3]]])
    blended = np.array([[[7]], [[7]]])
    step4.keep_outside_nodata(blended, mosaic)
    np.testing.assert_array_equal(blended, [[[7]], [[7]]])


def test_single_band_pan(step4):
    bigpan = np.array([[0, 100], [100, 0]])
    blended = np.array([[50, 60], [70, 80]])
    out = step4.keep_outside_nodata(blended, bigpan)
    assert out is blended
    np.testing.assert_array_equal(blended, [[0, 60], [70, 0]])
