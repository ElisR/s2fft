import pytest
from pytest import fixture
import numpy as np
import s2fft as s2f
import healpy as hp


@fixture
def flm_generator():
    return s2f.utils.generate_flm


@fixture
def reindex_lm_to_hp():
    def lm2lm_hp(flm: np.ndarray, L: int) -> np.ndarray:
        flm_hp = np.zeros(int(L * (L + 1) / 2 + L + 1), dtype=np.complex128)

        for el in range(0, L):
            for m in range(0, el + 1):
                flm_hp[s2f.samples.hp_getidx(L, el, m)] = flm[s2f.samples.elm2ind(el, m)]

        return flm_hp

    return lm2lm_hp
