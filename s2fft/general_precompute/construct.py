import numpy as np
from s2fft import wigner, samples, quadrature


def spin_spherical_kernel(
    L: int,
    spin: int = 0,
    reality: bool = False,
    sampling: str = "mw",
    nside: int = None,
    forward: bool = False,
):
    if forward and sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        thetas = samples.thetas(2 * L, "mwss")
    else:
        thetas = samples.thetas(L, sampling, nside)

    dl = np.zeros((len(thetas), L, 2 * L - 1), dtype=np.float64)
    for t, theta in enumerate(thetas):
        for el in range(abs(spin), L):
            dl[t, el] = wigner.turok.compute_slice(theta, el, L, -spin, reality)
            dl[t, el] *= np.sqrt((2 * el + 1) / (4 * np.pi))

    if forward:
        weights = quadrature.quad_weights_transform(L, sampling, 0, nside)
        dl = np.einsum("...tlm, ...t->...tlm", dl, weights)

    if sampling.lower() == "healpix":
        dl = np.einsum(
            "...tlm,...tm->...tlm", dl, healpix_phase_shifts(L, nside, forward)
        )
    return dl


def wigner_kernel(
    L: int,
    N: int,
    reality: bool = False,
    sampling: str = "mw",
    nside: int = None,
    forward: bool = False,
):
    if forward and sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        thetas = samples.thetas(2 * L, "mwss")
    else:
        thetas = samples.thetas(L, sampling, nside)

    dl = np.zeros((2 * N - 1, len(thetas), L, 2 * L - 1), dtype=np.float64)
    for n in range(-N + 1, N):
        for t, theta in enumerate(thetas):
            for el in range(abs(n), L):
                dl[N - 1 + n, t, el] = wigner.turok.compute_slice(
                    theta, el, L, n, reality
                )

    if forward:
        weights = quadrature.quad_weights_transform(L, sampling, 0, nside)
        dl = np.einsum("...ntlm, ...t->...ntlm", dl, weights)
        dl *= 2 * np.pi / (2 * N - 1)

    else:
        dl = np.einsum(
            "...ntlm,...l->...ntlm",
            dl,
            (2 * np.arange(L) + 1) / (8 * np.pi**2),
        )

    if sampling.lower() == "healpix":
        dl = np.einsum(
            "...ntlm,...tm->...ntlm",
            dl,
            healpix_phase_shifts(L, nside, forward),
        )

    return dl


def healpix_phase_shifts(
    L: int, nside: int, forward: bool = False
) -> np.ndarray:
    r"""Generates a phase shift vector for HEALPix for all :math:`\theta` rings.

    Args:
        L (int, optional): Harmonic band-limit.

        nside (int): HEALPix Nside resolution parameter.

        forward (bool, optional): Whether to provide forward or inverse shift.
            Defaults to False.

    Returns:
        np.ndarray: Vector of phase shifts with shape :math:`[thetas, 2L-1]`.
    """
    thetas = samples.thetas(L, "healpix", nside)
    phase_array = np.zeros((len(thetas), 2 * L - 1), dtype=np.complex128)
    for t, theta in enumerate(thetas):
        phase_array[t] = samples.ring_phase_shift_hp(L, t, nside, forward)

    return phase_array
