from jax import config

config.update("jax_enable_x64", True)

import numpy as np
import jax.numpy as jnp
import jax.lax as lax
from jax import jit
from functools import partial

from s2fft import samples
from typing import List


def generate_precomputes(
    L: int,
    spin: int = 0,
    sampling: str = "mw",
    nside: int = None,
    forward: bool = False,
) -> List[np.ndarray]:
    r"""Compute recursion coefficients with :math:`\mathcal{O}(L^2)` memory overhead.
    In practice one could compute these on-the-fly but the memory overhead is
    negligible and well worth the acceleration.

    Args:
        L (int): Harmonic band-limit.

        spin (int, optional): Harmonic spin. Defaults to 0.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        forward (bool, optional): Whether to provide forward or inverse shift.
            Defaults to False.

    Returns:
        List[np.ndarray]: List of precomputed coefficient arrays.

    Note:
        TODO: this function should be optimised.
    """
    mm = -spin

    # Correct for mw to mwss conversion
    if forward and sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        beta = samples.thetas(2 * L, "mwss")[1:-1]
    else:
        beta = samples.thetas(L, sampling, nside)

    ntheta = len(beta)  # Number of theta samples
    el = np.arange(L)

    # Trigonometric constant adopted throughout
    c = np.cos(beta)
    s = np.sin(beta)
    cs = c / s
    t = np.tan(-beta / 2.0)
    lt = np.log(np.abs(t))
    c2 = np.cos(beta / 2.0)
    omc = 1.0 - c

    # Indexing boundaries
    half_slices = [el + mm + 1, el - mm + 1]

    # Vectors with indexing -L < m < L adopted throughout
    cpi = np.zeros((L + 1, L), dtype=np.float64)
    cp2 = np.zeros((L + 1, L), dtype=np.float64)
    log_first_row = np.zeros((2 * L + 1, ntheta, L), dtype=np.float64)

    # Populate vectors for first row
    log_first_row[0] = np.einsum("l,t->tl", 2.0 * el, np.log(np.abs(c2)))

    for i in range(2, L + abs(mm) + 2):
        ratio = (2 * el + 2 - i) / (i - 1)
        for j in range(ntheta):
            log_first_row[i - 1, j] = (
                log_first_row[i - 2, j] + np.log(ratio) / 2 + lt[j]
            )

    # Initialising coefficients cp(m)= cplus(l-m).
    cpi[0] = 2.0 / np.sqrt(2 * el)
    for m in range(2, L + 1):
        cpi[m - 1] = 2.0 / np.sqrt(m * (2 * el + 1 - m))
        cp2[m - 1] = cpi[m - 1] / cpi[m - 2]

    for k in range(L):
        cpi[:, k] = np.roll(cpi[:, k], (L - k - 1), axis=-1)
        cp2[:, k] = np.roll(cp2[:, k], (L - k - 1), axis=-1)
    # Then evaluate the negative half row and reflect using
    # Wigner-d symmetry relation.

    # Perform precomputations (these can be done offline)
    msign = np.hstack(((-1) ** (abs(np.arange(L - 1))), np.ones(L)))
    lsign = (-1) ** abs(mm + el)
    vsign = np.einsum("m,l->ml", msign, lsign)
    vsign[: L - 1] *= (-1) ** abs(mm + 1 + L)

    lrenorm = np.zeros((2, ntheta, L), dtype=np.float64)
    lamb = np.zeros((2, ntheta, L), np.float64)
    for i in range(2):
        for j in range(ntheta):
            lamb[i, j] = ((el + 1) * omc[j] - half_slices[i] + c[j]) / s[j]
            for k in range(L):
                lamb[i, j, k] -= (L - k - 1) * cs[j]
                lrenorm[i, j, k] = log_first_row[half_slices[i][k] - 1, j, k]

    indices = np.repeat(np.expand_dims(np.arange(L), 0), ntheta, axis=0)

    return [lrenorm, lamb, vsign, cpi, cp2, cs, indices]


@partial(jit, static_argnums=(0, 1, 2, 3, 4))
def generate_precomputes_jax(
    L: int,
    spin: int = 0,
    sampling: str = "mw",
    nside: int = None,
    forward: bool = False,
) -> List[jnp.ndarray]:
    mm = -spin

    # Correct for mw to mwss conversion
    if forward and sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        beta = samples.thetas(2 * L, "mwss")[1:-1]
    else:
        beta = samples.thetas(L, sampling, nside)

    ntheta = len(beta)  # Number of theta samples
    el = jnp.arange(L)

    # Trigonometric constant adopted throughout
    c = jnp.cos(beta)
    s = jnp.sin(beta)
    cs = c / s
    t = jnp.tan(-beta / 2.0)
    lt = jnp.log(jnp.abs(t))
    c2 = jnp.cos(beta / 2.0)
    omc = 1.0 - c

    # Indexing boundaries
    half_slices = [el + mm + 1, el - mm + 1]

    # Vectors with indexing -L < m < L adopted throughout
    cpi = jnp.zeros((L + 1, L), dtype=jnp.float64)
    cp2 = jnp.zeros((L + 1, L), dtype=jnp.float64)

    # Initialising coefficients cp(m)= cplus(l-m).
    cpi = cpi.at[0].add(2.0 / jnp.sqrt(2 * el))

    def cpi_cp2_loop(m, args):
        cpi, cp2 = args
        cpi = cpi.at[m - 1].add(2.0 / jnp.sqrt(m * (2 * el + 1 - m)))
        cp2 = cp2.at[m - 1].add(cpi[m - 1] / cpi[m - 2])
        return cpi, cp2

    cpi, cp2 = lax.fori_loop(2, L + 1, cpi_cp2_loop, (cpi, cp2))

    def cpi_cp2_roll_loop(m, args):
        cpi, cp2 = args
        cpi = cpi.at[:, m].set(jnp.roll(cpi[:, m], (L - m - 1), axis=-1))
        cp2 = cp2.at[:, m].set(jnp.roll(cp2[:, m], (L - m - 1), axis=-1))
        return cpi, cp2

    cpi, cp2 = lax.fori_loop(0, L, cpi_cp2_roll_loop, (cpi, cp2))

    # Then evaluate the negative half row and reflect using
    # Wigner-d symmetry relation.

    # Perform precomputations (these can be done offline)
    msign = jnp.hstack(((-1) ** (abs(jnp.arange(L - 1))), jnp.ones(L)))
    lsign = (-1) ** abs(mm + el)
    vsign = jnp.einsum("m,l->ml", msign, lsign, optimize=True)
    vsign = vsign.at[: L - 1].multiply((-1) ** abs(mm + 1 + L))

    # Populate vectors for first ro
    lrenorm = jnp.zeros((2, ntheta, L), dtype=jnp.float64)
    log_first_row_iter = jnp.einsum(
        "l,t->tl", 2.0 * el, jnp.log(jnp.abs(c2)), optimize=True
    )

    ratio_update = jnp.arange(L + abs(mm) + 2)
    ratio = jnp.repeat(jnp.expand_dims(2 * el + 2, -1), L + abs(mm) + 2, axis=-1)
    ratio -= ratio_update
    ratio /= ratio_update - 1
    ratio = jnp.log(jnp.swapaxes(ratio, 0, 1)) / 2

    for ind in range(2):
        lrenorm = lrenorm.at[ind].set(
            jnp.where(1 == half_slices[ind], log_first_row_iter, lrenorm[ind])
        )
    def renorm_m_loop(i, args):
        log_first_row_iter, lrenorm = args
        log_first_row_iter += ratio[i]
        log_first_row_iter = jnp.swapaxes(log_first_row_iter, 0, 1)
        log_first_row_iter += lt
        log_first_row_iter = jnp.swapaxes(log_first_row_iter, 0, 1)
        for ind in range(2):
            lrenorm = lrenorm.at[ind].set(
                jnp.where(i == half_slices[ind], log_first_row_iter, lrenorm[ind])
            )
        return log_first_row_iter, lrenorm

    _, lrenorm = lax.fori_loop(
        2, L + abs(mm) + 2, renorm_m_loop, (log_first_row_iter, lrenorm)
    )

    # Recursion update parameters
    lamb = jnp.zeros((2, ntheta, L), jnp.float64)
    for i in range(2):
        temp = jnp.einsum("t, l->tl", omc, el + 1, optimize=True)
        temp -= half_slices[i]
        temp = jnp.swapaxes(temp, 0, 1)
        temp += c
        temp /= s
        lamb = lamb.at[i].add(jnp.swapaxes(temp, 0, 1))
        temp = jnp.einsum("t,l->tl", cs, L - el - 1, optimize=True)
        lamb = lamb.at[i].add(-temp)

    indices = jnp.repeat(jnp.expand_dims(jnp.arange(L), 0), ntheta, axis=0)

    return [lrenorm, lamb, vsign, cpi, cp2, cs, indices]


def generate_precomputes_wigner(
    L: int,
    N: int,
    sampling: str = "mw",
    nside: int = None,
    forward: bool = False,
) -> List[List[np.ndarray]]:
    r"""Compute recursion coefficients with :math:`\mathcal{O}(L^2)` memory overhead.
    In practice one could compute these on-the-fly but the memory overhead is
    negligible and well worth the acceleration. This is a wrapped extension of
    :func:`~generate_precomputes` for the case of multiple spins, i.e. the Wigner
    transform over SO(3).

    Args:
        L (int): Harmonic band-limit.

        N (int): Azimuthal bandlimit

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        forward (bool, optional): Whether to provide forward or inverse shift.
            Defaults to False.

    Returns:
        List[List[np.ndarray]]: 2N-1 length List of Lists of precomputed coefficient arrays.

    Note:
        TODO: this function should be optimised.
    """
    precomps = []
    for n in range(-N + 1, N):
        precomps.append(generate_precomputes(L, -n, sampling, nside, forward))
    return precomps


def compute_all_slices(
    beta: np.ndarray, L: int, spin: int, precomps=None
) -> np.ndarray:
    r"""Compute a particular slice :math:`m^{\prime}`, denoted `mm`,
    of the complete Wigner-d matrix for all sampled polar angles
    :math:`\beta` and all :math:`\ell` using Price & McEwen recursion.

    The Wigner-d slice for all :math:`\ell` (`el`) and :math:`\beta` is
    computed recursively over :math:`m` labelled 'm' at a specific
    :math:`m^{\prime}`. The Price & McEwen recursion is analytically correct
    from :math:`-\ell < m < \ell` however numerically it can become unstable for
    :math:`m > 0`. To avoid this we compute :math:`d_{m,
    m^{\prime}}^{\ell}(\beta)` for negative :math:`m` and then evaluate
    :math:`d_{m, -m^{\prime}}^{\ell}(\beta) = (-1)^{m-m^{\prime}} d_{-m,
    m^{\prime}}^{\ell}(\beta)` which we can again evaluate using the same recursion.

    On-the-fly renormalisation is implemented to avoid potential over/under-flows,
    within any given iteration of the recursion the iterants are :math:`\sim \mathcal{O}(1)`.

    The Wigner-d slice :math:`d^\ell_{m, m^{\prime}}(\beta)` is indexed for
    :math:`-L < m < L` by `dl[L - 1 - m, \beta, \ell]`. This implementation has
    computational scaling :math:`\mathcal{O}(L)` and typically requires :math:`\sim 2L`
    operations.

    Args:
        beta (np.ndarray): Array of polar angles in radians.

        L (int): Harmonic band-limit.

        spin (int, optional): Harmonic spin. Defaults to 0.

        precomps (List[np.ndarray]): Precomputed recursion coefficients with memory overhead
            :math:`\mathcal{O}(L^2)`, which is minimal.

    Returns:
        np.ndarray: Wigner-d matrix mm slice of dimension :math:`[2L-1, n_{\theta}, n_{\ell}]`.
    """
    # Indexing boundaries and constants
    mm = -spin
    ntheta = len(beta)
    lims = [0, -1]

    dl_test = np.zeros((2 * L - 1, ntheta, L), dtype=np.float64)
    if precomps is None:
        lrenorm, lamb, vsign, cpi, cp2, cs, indices = generate_precomputes(beta, L, mm)
    else:
        lrenorm, lamb, vsign, cpi, cp2, cs, indices = precomps

    for i in range(2):
        lind = L - 1
        sind = lims[i]
        sgn = (-1) ** (i)
        dl_iter = np.ones((2, ntheta, L), dtype=np.float64)

        dl_iter[1, :, lind:] = np.einsum(
            "l,tl->tl",
            cpi[0, lind:],
            dl_iter[0, :, lind:] * lamb[i, :, lind:],
        )

        dl_test[sind, :, lind:] = (
            dl_iter[0, :, lind:] * vsign[sind, lind:] * np.exp(lrenorm[i, :, lind:])
        )
        dl_test[sind + sgn, :, lind - 1 :] = (
            dl_iter[1, :, lind - 1 :]
            * vsign[sind + sgn, lind - 1 :]
            * np.exp(lrenorm[i, :, lind - 1 :])
        )

        dl_entry = np.zeros((ntheta, L), dtype=np.float64)
        for m in range(2, L):
            index = indices >= L - m - 1
            lamb[i, :, np.arange(L)] += cs
            dl_entry = np.where(
                index,
                np.einsum("l,tl->tl", cpi[m - 1], dl_iter[1] * lamb[i])
                - np.einsum("l,tl->tl", cp2[m - 1], dl_iter[0]),
                dl_entry,
            )
            dl_entry[:, -(m + 1)] = 1

            dl_test[sind + sgn * m] = np.where(
                index,
                dl_entry * vsign[sind + sgn * m] * np.exp(lrenorm[i]),
                dl_test[sind + sgn * m],
            )

            bigi = 1.0 / abs(dl_entry)
            lbig = np.log(abs(dl_entry))

            dl_iter[0] = np.where(index, bigi * dl_iter[1], dl_iter[0])
            dl_iter[1] = np.where(index, bigi * dl_entry, dl_iter[1])
            lrenorm[i] = np.where(index, lrenorm[i] + lbig, lrenorm[i])

    return dl_test


@partial(jit, static_argnums=(1, 2))
def compute_all_slices_jax(
    beta: jnp.ndarray, L: int, spin: int, precomps=None
) -> jnp.ndarray:
    r"""Compute a particular slice :math:`m^{\prime}`, denoted `mm`,
    of the complete Wigner-d matrix for all sampled polar angles
    :math:`\beta` and all :math:`\ell` using Price & McEwen recursion.

    The Wigner-d slice for all :math:`\ell` (`el`) and :math:`\beta` is
    computed recursively over :math:`m` labelled 'm' at a specific
    :math:`m^{\prime}`. The Price & McEwen recursion is analytically correct
    from :math:`-\ell < m < \ell` however numerically it can become unstable for
    :math:`m > 0`. To avoid this we compute :math:`d_{m,
    m^{\prime}}^{\ell}(\beta)` for negative :math:`m` and then evaluate
    :math:`d_{m, -m^{\prime}}^{\ell}(\beta) = (-1)^{m-m^{\prime}} d_{-m,
    m^{\prime}}^{\ell}(\beta)` which we can again evaluate using the same recursion.

    On-the-fly renormalisation is implemented to avoid potential over/under-flows,
    within any given iteration of the recursion the iterants are :math:`\sim \mathcal{O}(1)`.

    The Wigner-d slice :math:`d^\ell_{m, m^{\prime}}(\beta)` is indexed for
    :math:`-L < m < L` by `dl[L - 1 - m, \beta, \ell]`. This implementation has
    computational scaling :math:`\mathcal{O}(L)` and typically requires :math:`\sim 2L`
    operations.

    Args:
        beta (jnp.ndarray): Array of polar angles in radians.

        L (int): Harmonic band-limit.

        spin (int, optional): Harmonic spin. Defaults to 0.

        precomps (List[np.ndarray]): Precomputed recursion coefficients with memory overhead
            :math:`\mathcal{O}(L^2)`, which is minimal.

    Returns:
        jnp.ndarray: Wigner-d matrix mm slice of dimension :math:`[2L-1, n_{\theta}, n_{\ell}]`.
    """
    # Indexing boundaries and constants
    mm = -spin
    ntheta = len(beta)
    lims = [0, -1]

    dl_test = jnp.zeros((2 * L - 1, ntheta, L), dtype=jnp.float64)
    if precomps is None:
        lrenorm, lamb, vsign, cpi, cp2, cs, indices = generate_precomputes(beta, L, mm)
    else:
        lrenorm, lamb, vsign, cpi, cp2, cs, indices = precomps

    for i in range(2):
        lind = L - 1
        sind = lims[i]
        sgn = (-1) ** (i)
        dl_iter = jnp.ones((2, ntheta, L), dtype=jnp.float64)

        dl_iter = dl_iter.at[1, :, lind:].set(
            jnp.einsum(
                "l,tl->tl",
                cpi[0, lind:],
                dl_iter[0, :, lind:] * lamb[i, :, lind:],
            )
        )

        dl_test = dl_test.at[sind, :, lind:].set(
            dl_iter[0, :, lind:] * vsign[sind, lind:] * jnp.exp(lrenorm[i, :, lind:])
        )

        dl_test = dl_test.at[sind + sgn, :, lind - 1 :].set(
            dl_iter[1, :, lind - 1 :]
            * vsign[sind + sgn, lind - 1 :]
            * jnp.exp(lrenorm[i, :, lind - 1 :])
        )

        dl_entry = jnp.zeros((ntheta, L), dtype=jnp.float64)

        def pm_recursion_step(m, args):
            dl_test, dl_entry, dl_iter, lamb, lrenorm = args
            index = indices >= L - m - 1
            lamb = lamb.at[i, :, jnp.arange(L)].add(cs)
            dl_entry = jnp.where(
                index,
                jnp.einsum("l,tl->tl", cpi[m - 1], dl_iter[1] * lamb[i])
                - jnp.einsum("l,tl->tl", cp2[m - 1], dl_iter[0]),
                dl_entry,
            )
            dl_entry = dl_entry.at[:, -(m + 1)].set(1)

            dl_test = dl_test.at[sind + sgn * m].set(
                jnp.where(
                    index,
                    dl_entry * vsign[sind + sgn * m] * jnp.exp(lrenorm[i]),
                    dl_test[sind + sgn * m],
                )
            )

            bigi = 1.0 / abs(dl_entry)
            lbig = jnp.log(abs(dl_entry))

            dl_iter = dl_iter.at[0].set(jnp.where(index, bigi * dl_iter[1], dl_iter[0]))
            dl_iter = dl_iter.at[1].set(jnp.where(index, bigi * dl_entry, dl_iter[1]))
            lrenorm = lrenorm.at[i].set(jnp.where(index, lrenorm[i] + lbig, lrenorm[i]))
            return dl_test, dl_entry, dl_iter, lamb, lrenorm

        dl_test, dl_entry, dl_iter, lamb, lrenorm = lax.fori_loop(
            2, L, pm_recursion_step, (dl_test, dl_entry, dl_iter, lamb, lrenorm)
        )
    return dl_test


if __name__ == "__main__":
    import os

    # os.environ['CUDA_VISIBLE_DEVICES'] = ""
    os.environ["CUDA_VISIBLE_DEVICES"] = "2"
    import warnings

    warnings.simplefilter("ignore")
    L = 4
    spin = -2
    sampling = "mw"

    precomps_pre = generate_precomputes(L, spin, sampling)
    precomps_post = generate_precomputes_jax(L, spin, sampling)

    for i in range(len(precomps_pre)):
        print(i)
        a = precomps_pre[i]
        b = precomps_post[i]
        # if i == 0:
        #     for ind in range(2):
        #         for t in range(L):
        #             for l in range(L):
        #                 print(ind, t, l, a[ind, t, l], b[ind, t, l], abs(a[ind, t, l]-b[ind, t, l]))
        np.testing.assert_allclose(precomps_pre[i], precomps_post[i])
