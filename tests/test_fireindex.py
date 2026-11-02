import numpy as np
from ilpi import fireindex as fi


def test_ffmc_van_wagner_reference():
    f, _ = fi.ffmc_step(85, 17, 42, 25, 0)
    assert abs(float(f) - 87.69) < 0.1


def test_ffmc_rain_and_dry():
    f_dry, _ = fi.ffmc_step(85, 30, 20, 20, 0)
    assert f_dry > 85
    f_nr, _ = fi.ffmc_step(85, 15, 80, 5, 0)
    f_r, _ = fi.ffmc_step(85, 15, 80, 5, 10)
    assert f_r < f_nr and f_r < 85


def test_downscale_altitude():
    t, rh = fi.downscale(30, 30, 1000, 2000)
    assert 23 < float(t) < 24 and float(rh) > 30


def test_aspect_and_spread():
    assert fi.dryness(12, 0) > fi.dryness(12, 180)
    assert fi.spread(40, 0, 10, 180) > fi.spread(5, 0, 10, 180)
    assert fi.spread(30, 180, 25, 180) > fi.spread(30, 0, 25, 180)


def test_index_monotonic_masks():
    base = fi.raw_index(0.5, 0.5, 0.5)
    assert fi.raw_index(0.9, 0.5, 0.5) > base
    assert fi.raw_index(0.5, 0.0, 0.5) < 0.05 * base
    assert fi.raw_index(0.9, 0.9, 0.9, snow_m=0.3) == 0.0


def test_score_and_classes():
    ref = np.linspace(0, 1, 1000)
    s = fi.to_score(np.array([0.1, 0.8, 0.99]), ref)
    assert list(fi.to_class(s)) == ["Bajo", "Alto", "Extremo"]
    assert list(fi.to_class(fi.score_provisional(np.array([0.1, 0.4, 0.55, 0.7, 0.9])), fi.PROV_BREAKS)) == \
        ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]
