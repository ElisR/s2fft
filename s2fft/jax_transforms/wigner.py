from jax import jit, config

config.update("jax_enable_x64", True)

import numpy as np
import jax.numpy as jnp
from functools import partial
from typing import List
from s2fft.wigner import samples
from s2fft.jax_transforms import spin_spherical


def inverse(
    flmn: np.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    method: str = "numpy",
    reality: bool = False,
    precomps: List = None,
    spmd: bool = False,
    L_lower: int = 0,
) -> np.ndarray:
    r"""Wrapper for the inverse Wigner transform, i.e. inverse Fourier transform on
    :math:`SO(3)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        flmn (np.ndarray): Wigner coefficients with shape :math:`[2N-1, L, 2L-1]`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[np.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        spmd (bool, optional): Whether to map compute over multiple devices. Currently this
            only maps over all available devices, and is only valid for JAX implementations.
            Defaults to False.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Raises:
        ValueError: Transform method not recognised.

    Returns:
        np.ndarray:  Signal on the on :math:`SO(3)` with shape :math:`[n_{\gamma},
        n_{\beta}, n_{\alpha}]`, where :math:`n_\xi` denotes the number of samples for
        angle :math:`\xi`.

    Note:
        The single-program multiple-data (SPMD) optional variable determines whether
        the transform is run over a single device or all available devices. For very low
        harmonic bandlimits L this is inefficient as the I/O overhead for communication
        between devices is noticable, however as L increases one will asymptotically
        recover acceleration by the number of devices.
    """
    if method == "numpy":
        return inverse_numpy(
            flmn, L, N, nside, sampling, reality, precomps, L_lower
        )
    elif method == "jax":
        return inverse_jax(
            flmn, L, N, nside, sampling, reality, precomps, spmd, L_lower
        )
    else:
        raise ValueError(
            f"Implementation {method} not recognised. Should be either numpy or jax."
        )


def inverse_numpy(
    flmn: np.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    reality: bool = False,
    precomps: List = None,
    L_lower: int = 0,
) -> np.ndarray:
    r"""Compute the inverse Wigner transform (numpy).

    Uses separation of variables and exploits the Price & McEwen recursion for accelerated
    and numerically stable Wiger-d on-the-fly recursions. The memory overhead for this
    function is theoretically :math:`\mathcal{O}(NL^2)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        flmn (np.ndarray): Wigner coefficients with shape :math:`[2N-1, L, 2L-1]`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[np.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Returns:
        np.ndarray: Signal on the sphere.
    """
    fban = np.zeros(samples.f_shape(L, N, sampling, nside), dtype=np.complex128)

    flmn[:, L_lower:] = np.einsum(
        "...nlm,...l->...nlm",
        flmn[:, L_lower:],
        np.sqrt((2 * np.arange(L_lower, L) + 1) / (16 * np.pi**3)),
    )

    n_start_ind = 0 if reality else -N + 1
    for n in range(n_start_ind, N):
        fban[N - 1 + n] = (-1) ** n * spin_spherical.inverse_numpy(
            flmn[N - 1 + n],
            L,
            -n,
            nside,
            sampling,
            reality if n == 0 else False,
            precomps[n - n_start_ind],
            L_lower,
        )

    ax = -2 if sampling.lower() == "healpix" else -3
    if reality:
        f = np.fft.irfft(fban[N - 1 :], 2 * N - 1, axis=ax, norm="forward")
    else:
        f = np.fft.ifft(
            np.fft.ifftshift(fban, axes=ax), axis=ax, norm="forward"
        )

    return f


@partial(jit, static_argnums=(1, 2, 3, 4, 5, 7, 8))
def inverse_jax(
    flmn: np.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    reality: bool = False,
    precomps: List = None,
    spmd: bool = False,
    L_lower: int = 0,
) -> jnp.ndarray:
    r"""Compute the inverse Wigner transform (numpy).

    Uses separation of variables and exploits the Price & McEwen recursion for accelerated
    and numerically stable Wiger-d on-the-fly recursions. The memory overhead for this
    function is theoretically :math:`\mathcal{O}(NL^2)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        flmn (np.ndarray): Wigner coefficients with shape :math:`[2N-1, L, 2L-1]`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[jnp.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        spmd (bool, optional): Whether to map compute over multiple devices. Currently this
            only maps over all available devices. Defaults to False.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Returns:
        jnp.ndarray: Signal on the sphere.

    Note:
        The single-program multiple-data (SPMD) optional variable determines whether
        the transform is run over a single device or all available devices. For very low
        harmonic bandlimits L this is inefficient as the I/O overhead for communication
        between devices is noticable, however as L increases one will asymptotically
        recover acceleration by the number of devices.
    """
    fban = jnp.zeros(
        samples.f_shape(L, N, sampling, nside), dtype=jnp.complex128
    )

    flmn = flmn.at[:, L_lower:].set(
        jnp.einsum(
            "...nlm,...l->...nlm",
            flmn[:, L_lower:],
            jnp.sqrt((2 * jnp.arange(L_lower, L) + 1) / (16 * jnp.pi**3)),
            optimize=True,
        )
    )

    n_start_ind = 0 if reality else -N + 1
    for n in range(n_start_ind, N):
        fban = fban.at[N - 1 + n].add(
            (-1) ** n
            * spin_spherical.inverse_jax(
                flmn[N - 1 + n],
                L,
                -n,
                nside,
                sampling,
                reality if n == 0 else False,
                precomps[n - n_start_ind],
                spmd,
                L_lower=L_lower,
            )
        )

    if reality:
        fban = fban.at[: N - 1].set(jnp.flip(jnp.conj(fban[N:]), axis=0))
    ax = -2 if sampling.lower() == "healpix" else -3
    fban = jnp.conj(jnp.fft.ifftshift(fban, axes=ax))
    f = jnp.conj(jnp.fft.fft(fban, axis=ax, norm="backward"))

    return f


def forward(
    f: np.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    method: str = "numpy",
    reality: bool = False,
    precomps: List = None,
    spmd: bool = False,
    L_lower: int = 0,
) -> np.ndarray:
    r"""Wrapper for the forward Wigner transform, i.e. Fourier transform on
    :math:`SO(3)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        f (np.ndarray): Signal on the on :math:`SO(3)` with shape
            :math:`[n_{\gamma}, n_{\beta}, n_{\alpha}]`, where :math:`n_\xi` denotes the
            number of samples for angle :math:`\xi`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[np.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        spmd (bool, optional): Whether to map compute over multiple devices. Currently this
            only maps over all available devices, and is only valid for JAX implementations.
            Defaults to False.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Raises:
        ValueError: Transform method not recognised.

    Returns:
        np.ndarray: Wigner coefficients `flmn` with shape :math:`[2N-1, L, 2L-1]`.

    Note:
        The single-program multiple-data (SPMD) optional variable determines whether
        the transform is run over a single device or all available devices. For very low
        harmonic bandlimits L this is inefficient as the I/O overhead for communication
        between devices is noticable, however as L increases one will asymptotically
        recover acceleration by the number of devices.
    """
    if method == "numpy":
        return forward_numpy(
            f, L, N, nside, sampling, reality, precomps, L_lower
        )
    elif method == "jax":
        return forward_jax(
            f, L, N, nside, sampling, reality, precomps, spmd, L_lower
        )
    else:
        raise ValueError(
            f"Implementation {method} not recognised. Should be either numpy or jax."
        )


def forward_numpy(
    f: np.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    reality: bool = False,
    precomps: List = None,
    L_lower: int = 0,
) -> np.ndarray:
    r"""Compute the forward Wigner transform (numpy).

    Uses separation of variables and exploits the Price & McEwen recursion for accelerated
    and numerically stable Wiger-d on-the-fly recursions. The memory overhead for this
    function is theoretically :math:`\mathcal{O}(NL^2)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        f (np.ndarray): Signal on the on :math:`SO(3)` with shape
            :math:`[n_{\gamma}, n_{\beta}, n_{\alpha}]`, where :math:`n_\xi` denotes the
            number of samples for angle :math:`\xi`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[np.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Returns:
        np.ndarray: Wigner coefficients `flmn` with shape :math:`[2N-1, L, 2L-1]`.
    """
    flmn = np.zeros(samples.flmn_shape(L, N), dtype=np.complex128)

    ax = -2 if sampling.lower() == "healpix" else -3
    if reality:
        fban = np.fft.rfft(np.real(f), axis=ax, norm="backward")
    else:
        fban = np.fft.fftshift(np.fft.fft(f, axis=ax, norm="backward"), axes=ax)

    fban *= 2 * np.pi / (2 * N - 1)

    if reality:
        sgn = (-1) ** abs(np.arange(-L + 1, L))

    n_start_ind = 0 if reality else -N + 1
    for n in range(n_start_ind, N):
        flmn[N - 1 + n] = (-1) ** n * spin_spherical.forward_numpy(
            fban[n - n_start_ind],
            L,
            -n,
            nside,
            sampling,
            reality if n == 0 else False,
            precomps[n - n_start_ind],
            L_lower,
        )
        if reality and n != 0:
            flmn[N - 1 - n] = np.conj(
                np.flip(flmn[N - 1 + n] * sgn * (-1) ** n, axis=-1)
            )
    flmn[:, L_lower:] = np.einsum(
        "...nlm,...l->...nlm",
        flmn[:, L_lower:],
        np.sqrt(4 * np.pi / (2 * np.arange(L_lower, L) + 1)),
    )
    return flmn


@partial(jit, static_argnums=(1, 2, 3, 4, 5, 7, 8))
def forward_jax(
    f: jnp.ndarray,
    L: int,
    N: int,
    nside: int = None,
    sampling: str = "mw",
    reality: bool = False,
    precomps: List = None,
    spmd: bool = False,
    L_lower: int = 0,
) -> jnp.ndarray:
    r"""Compute the forward Wigner transform (JAX).

    Uses separation of variables and exploits the Price & McEwen recursion for accelerated
    and numerically stable Wiger-d on-the-fly recursions. The memory overhead for this
    function is theoretically :math:`\mathcal{O}(NL^2)`.

    Importantly, the convention adopted for storage of f is :math:`[\gamma, \beta,
    \alpha]`, for Euler angles :math:`(\alpha, \beta, \gamma)` following the
    :math:`zyz` Euler convention, in order to simplify indexing for internal use.
    For a given :math:`\gamma` we thus recover a signal on the sphere indexed by
    :math:`[\theta, \phi]`, i.e. we associate :math:`\beta` with :math:`\theta` and
    :math:`\alpha` with :math:`\phi`.

    Args:
        f (jnp.ndarray): Signal on the on :math:`SO(3)` with shape
            :math:`[n_{\gamma}, n_{\beta}, n_{\alpha}]`, where :math:`n_\xi` denotes the
            number of samples for angle :math:`\xi`.

        L (int): Harmonic band-limit.

        N (int): Azimuthal band-limit.

        nside (int, optional): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".  Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.  Defaults to "mw".

        method (str, optional): Execution mode in {"numpy", "jax"}. Defaults to "numpy".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.  Defaults to
            False.

        precomps (List[jnp.ndarray]): Precomputed list of recursion coefficients. At most
            of length :math:`L^2`, which is a minimal memory overhead.

        spmd (bool, optional): Whether to map compute over multiple devices. Currently this
            only maps over all available devices, and is only valid for JAX implementations.
            Defaults to False.

        L_lower (int, optional): Harmonic lower-bound. Transform will only be computed
            for :math:`\texttt{L_lower} \leq \ell < \texttt{L}`. Defaults to 0.

    Returns:
        jnp.ndarray: Wigner coefficients `flmn` with shape :math:`[2N-1, L, 2L-1]`.
    """
    flmn = jnp.zeros(samples.flmn_shape(L, N), dtype=jnp.complex128)

    ax = -2 if sampling.lower() == "healpix" else -3
    if reality:
        fban = jnp.fft.rfft(jnp.real(f), axis=ax, norm="backward")
    else:
        fban = jnp.fft.fftshift(
            jnp.fft.fft(f, axis=ax, norm="backward"), axes=ax
        )

    fban *= 2 * jnp.pi / (2 * N - 1)

    if reality:
        sgn = (-1) ** abs(jnp.arange(-L + 1, L))

    n_start_ind = 0 if reality else -N + 1
    for n in range(n_start_ind, N):
        flmn = flmn.at[N - 1 + n].add(
            (-1) ** n
            * spin_spherical.forward_jax(
                fban[n - n_start_ind],
                L,
                -n,
                nside,
                sampling,
                reality if n == 0 else False,
                precomps[n - n_start_ind],
                spmd,
                L_lower,
            )
        )
        if reality and n != 0:
            flmn = flmn.at[N - 1 - n].add(
                jnp.conj(jnp.flip(flmn[N - 1 + n] * sgn * (-1) ** n, axis=-1))
            )

    flmn = flmn.at[:, L_lower:].set(
        jnp.einsum(
            "...nlm,...l->...nlm",
            flmn[:, L_lower:],
            jnp.sqrt(4 * jnp.pi / (2 * jnp.arange(L_lower, L) + 1)),
            optimize=True,
        )
    )
    return flmn
