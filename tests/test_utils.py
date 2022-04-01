import pytest
import numpy as np
import s2fft as s2f
import pyssht as ssht

from .utils import *


def test_flm_reindexing_functions(flm_generator):

    L = 16
    flm_1d = flm_generator(L=L, spin=0, reality=False)

    flm_2d = s2f.utils.flm_1d_to_2d(flm_1d, L)

    assert len(flm_2d.shape) == 2

    flm_1d_check = s2f.utils.flm_2d_to_1d(flm_2d, L)

    assert len(flm_1d_check.shape) == 1
    np.testing.assert_allclose(flm_1d, flm_1d_check, atol=1e-14)


def test_flm_reindexing_functions_healpix(flm_generator, reindex_lm_to_hp):

    L = 16
    flm_1d = flm_generator(L=L, spin=0, reality=True)
    flm_hp = reindex_lm_to_hp(flm_1d, L)

    flm_2d_hp = s2f.utils.flm_hp_to_2d(flm_hp, L)
    flm_2d = s2f.utils.flm_1d_to_2d(flm_1d, L)
    assert len(flm_2d_hp.shape) == 2
    np.testing.assert_allclose(flm_2d, flm_2d_hp, atol=1e-14)

    flm_hp_check = s2f.utils.flm_2d_to_hp(flm_2d_hp, L)
    np.testing.assert_allclose(flm_hp, flm_hp_check, atol=1e-14)


def test_flm_reindexing_exceptions(flm_generator):
    L = 16
    spin = 0

    flm_1d = flm_generator(L=L, spin=spin, reality=False)
    flm_2d = s2f.utils.flm_1d_to_2d(flm_1d, L)
    flm_3d = np.zeros((1, 1, 1))

    with pytest.raises(ValueError) as e:
        s2f.utils.flm_1d_to_2d(flm_2d, L)

    with pytest.raises(ValueError) as e:
        s2f.utils.flm_1d_to_2d(flm_3d, L)

    with pytest.raises(ValueError) as e:
        s2f.utils.flm_2d_to_1d(flm_1d, L)

    with pytest.raises(ValueError) as e:
        s2f.utils.flm_2d_to_1d(flm_3d, L)
