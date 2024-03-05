from jax import jit

import numpy as np
import jax.numpy as jnp
import torch
from s2fft.sampling import s2_samples as samples
from s2fft.utils import resampling, resampling_jax, resampling_torch
from s2fft.utils import healpix_ffts as hp
from functools import partial
from warnings import warn


def inverse(
    flm: np.ndarray,
    L: int,
    spin: int = 0,
    kernel: np.ndarray = None,
    sampling: str = "mw",
    reality: bool = False,
    method: str = "jax",
    nside: int = None,
) -> np.ndarray:
    r"""Compute the inverse spherical harmonic transform via precompute.

    Args:
        flm (np.ndarray): Spherical harmonic coefficients.

        L (int): Harmonic band-limit.

        spin (int, optional): Harmonic spin. Defaults to 0.

        kernel (np.ndarray, optional): Wigner-d kernel. Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}. Defaults to "mw".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.
            Defaults to False.

        method (str, optional): Execution mode in {"numpy", "jax", "torch"}.
            Defaults to "jax".

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Raises:
        ValueError: Transform method not recognised.

        Warning: Reality set but field is != spin 0 = complex.

    Returns:
        np.ndarray: Pixel-space coefficients with shape.
    """
    if reality and spin != 0:
        reality = False
        warn(
            "Reality acceleration only supports spin 0 fields. "
            + "Defering to complex transform."
        )
    if method == "numpy":
        return inverse_transform(flm, kernel, L, sampling, reality, spin, nside)
    elif method == "jax":
        return inverse_transform_jax(flm, kernel, L, sampling, reality, spin, nside)
    elif method == "torch":
        return inverse_transform_torch(flm, kernel, L, sampling, reality, spin, nside)
    else:
        raise ValueError(f"Method {method} not recognised.")


def inverse_transform(
    flm: np.ndarray,
    kernel: np.ndarray,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> np.ndarray:
    r"""Compute the forward spherical harmonic transform via precompute (vectorized
    implementation).

    Args:
        flm (np.ndarray): Spherical harmonic coefficients.

        kernel (np.ndarray): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        np.ndarray: Pixel-space coefficients.
    """
    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    ftm = np.zeros(samples.ftm_shape(L, sampling, nside), dtype=np.complex128)
    ftm[:, m_start_ind + m_offset :] = np.einsum(
        "...tlm, ...lm -> ...tm", kernel, flm[:, m_start_ind:]
    )
    ftm *= (-1) ** (spin)

    if sampling.lower() == "healpix":
        if reality:
            ftm[:, m_offset : m_start_ind + m_offset] = np.flip(
                np.conj(ftm[:, m_start_ind + m_offset + 1 :]), axis=-1
            )
        f = hp.healpix_ifft(ftm, L, nside, "numpy", reality)

    else:
        if reality:
            f = np.fft.irfft(
                ftm[:, m_start_ind + m_offset :],
                samples.nphi_equiang(L, sampling),
                axis=-1,
                norm="forward",
            )
        else:
            f = np.fft.ifftshift(ftm, axes=-1)
            f = np.fft.ifft(f, axis=-1, norm="forward")
    return f


@partial(jit, static_argnums=(2, 3, 4, 5, 6))
def inverse_transform_jax(
    flm: jnp.ndarray,
    kernel: jnp.ndarray,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> jnp.ndarray:
    r"""Compute the inverse spherical harmonic transform via precompute (JAX
    implementation).

    Args:
        flm (jnp.ndarray): Spherical harmonic coefficients.

        kernel (jnp.ndarray): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        jnp.ndarray: Pixel-space coefficients with shape.
    """
    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    ftm = jnp.zeros(samples.ftm_shape(L, sampling, nside), dtype=jnp.complex128)
    ftm = ftm.at[:, m_start_ind + m_offset :].add(
        jnp.einsum(
            "...tlm, ...lm -> ...tm",
            kernel,
            flm[:, m_start_ind:],
            optimize=True,
        )
    )
    ftm *= (-1) ** spin
    if reality:
        ftm = ftm.at[:, m_offset : m_start_ind + m_offset].set(
            jnp.flip(jnp.conj(ftm[:, m_start_ind + m_offset + 1 :]), axis=-1)
        )

    if sampling.lower() == "healpix":
        f = hp.healpix_ifft(ftm, L, nside, "jax", reality)

    else:
        f = jnp.conj(jnp.fft.ifftshift(ftm, axes=-1))
        f = jnp.conj(jnp.fft.fft(f, axis=-1, norm="backward"))
    return jnp.real(f) if reality else f


def inverse_transform_torch(
    flm: torch.tensor,
    kernel: torch.tensor,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> torch.tensor:
    r"""Compute the inverse spherical harmonic transform via precompute (Torch
    implementation).

    Args:
        flm (torch.tensor): Spherical harmonic coefficients.

        kernel (torch.tensor): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        torch.tensor: Pixel-space coefficients with shape.
    """
    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    ftm = torch.zeros(samples.ftm_shape(L, sampling, nside), dtype=torch.complex128)
    if sampling.lower() == "healpix":
        ftm[:, m_start_ind + m_offset :] += torch.einsum(
            "...tlm, ...lm -> ...tm", kernel, flm[:, m_start_ind:]
        )
    else:
        ftm[:, m_start_ind + m_offset :].real += torch.einsum(
            "...tlm, ...lm -> ...tm", kernel, flm[:, m_start_ind:].real
        )
        ftm[:, m_start_ind + m_offset :].imag += torch.einsum(
            "...tlm, ...lm -> ...tm", kernel, flm[:, m_start_ind:].imag
        )
    ftm *= (-1) ** spin
    if reality:
        ftm[:, m_offset : m_start_ind + m_offset] = torch.flip(
            torch.conj(ftm[:, m_start_ind + m_offset + 1 :]), dims=[-1]
        )

    if sampling.lower() == "healpix":
        f = hp.healpix_ifft(ftm, L, nside, "torch", reality)

    else:
        f = torch.conj(torch.fft.ifftshift(ftm, dim=[-1]))
        f = torch.conj(torch.fft.fft(f, axis=-1, norm="backward"))
    return f.real if reality else f


def forward(
    f: np.ndarray,
    L: int,
    spin: int = 0,
    kernel: np.ndarray = None,
    sampling: str = "mw",
    reality: bool = False,
    method: str = "jax",
    nside: int = None,
) -> np.ndarray:
    r"""Compute the forward spherical harmonic transform via precompute.

    Args:
        f (np.ndarray): Signal on the sphere.

        L (int): Harmonic band-limit.

        spin (int, optional): Harmonic spin. Defaults to 0.

        kernel (np.ndarray, optional): Wigner-d kernel. Defaults to None.

        sampling (str, optional): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}. Defaults to "mw".

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.
            Defaults to False.

        method (str, optional): Execution mode in {"numpy", "jax", "torch"}.
            Defaults to "jax".

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Raises:
        ValueError: Transform method not recognised.

        Warning: Reality set but field is != spin 0 = complex.

    Returns:
        np.ndarray: Spherical harmonic coefficients.
    """
    if reality and spin != 0:
        reality = False
        warn(
            "Reality acceleration only supports spin 0 fields. "
            + "Defering to complex transform."
        )
    if method == "numpy":
        return forward_transform(f, kernel, L, sampling, reality, spin, nside)
    elif method == "jax":
        return forward_transform_jax(f, kernel, L, sampling, reality, spin, nside)
    elif method == "torch":
        return forward_transform_torch(f, kernel, L, sampling, reality, spin, nside)
    else:
        raise ValueError(f"Method {method} not recognised.")


def forward_transform(
    f: np.ndarray,
    kernel: np.ndarray,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> np.ndarray:
    r"""Compute the forward spherical harmonic transform via precompute (vectorized
    implementation).

    Args:
        f (np.ndarray): Signal on the sphere.

        kernel (np.ndarray): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        np.ndarray: Pixel-space coefficients.
    """
    if sampling.lower() == "mw":
        f = resampling.mw_to_mwss(f, L, spin)

    if sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        f = resampling.upsample_by_two_mwss(f, L, spin)

    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    if sampling.lower() == "healpix":
        ftm = hp.healpix_fft(f, L, nside, "numpy", reality)[:, m_offset:]
        if reality:
            ftm = ftm[:, m_start_ind:]
    else:
        if reality:
            ftm = np.fft.rfft(np.real(f), axis=-1, norm="backward")
            if m_offset != 0:
                ftm = ftm[:, :-1]
        else:
            ftm = np.fft.fft(f, axis=-1, norm="backward")
            ftm = np.fft.fftshift(ftm, axes=-1)[:, m_offset:]
    flm = np.zeros(samples.flm_shape(L), dtype=np.complex128)
    flm[:, m_start_ind:] = np.einsum("...tlm, ...tm -> ...lm", kernel, ftm)

    if reality:
        flm[:, :m_start_ind] = np.flip(
            (-1) ** (np.arange(1, L) % 2) * np.conj(flm[:, m_start_ind + 1 :]),
            axis=-1,
        )

    return flm * (-1) ** spin


@partial(jit, static_argnums=(2, 3, 4, 5, 6))
def forward_transform_jax(
    f: jnp.ndarray,
    kernel: jnp.ndarray,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> jnp.ndarray:
    r"""Compute the forward spherical harmonic tranclearsform via precompute (vectorized
    implementation).

    Args:
        f (jnp.ndarray): Signal on the sphere.

        kernel (jnp.ndarray): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "gl", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        jnp.ndarray: Pixel-space coefficients.
    """
    if sampling.lower() == "mw":
        f = resampling_jax.mw_to_mwss(f, L, spin)

    if sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        f = resampling_jax.upsample_by_two_mwss(f, L, spin)

    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    if sampling.lower() == "healpix":
        ftm = hp.healpix_fft(f, L, nside, "jax", reality)[:, m_offset:]
        if reality:
            ftm = ftm[:, m_start_ind:]
    else:
        if reality:
            ftm = jnp.fft.rfft(jnp.real(f), axis=-1, norm="backward")
            if m_offset != 0:
                ftm = ftm[:, :-1]
        else:
            ftm = jnp.fft.fft(f, axis=-1, norm="backward")
            ftm = jnp.fft.fftshift(ftm, axes=-1)[:, m_offset:]

    flm = jnp.zeros(samples.flm_shape(L), dtype=jnp.complex128)
    flm = flm.at[:, m_start_ind:].set(
        jnp.einsum("...tlm, ...tm -> ...lm", kernel, ftm, optimize=True)
    )

    if reality:
        flm = flm.at[:, :m_start_ind].set(
            jnp.flip(
                (-1) ** (jnp.arange(1, L) % 2) * jnp.conj(flm[:, m_start_ind + 1 :]),
                axis=-1,
            )
        )

    return flm * (-1) ** spin


def forward_transform_torch(
    f: torch.tensor,
    kernel: torch.tensor,
    L: int,
    sampling: str,
    reality: bool,
    spin: int,
    nside: int,
) -> torch.tensor:
    r"""Compute the forward spherical harmonic tranclearsform via precompute (vectorized
    implementation).

    Args:
        f (torch.tensor): Signal on the sphere.

        kernel (torch.tensor): Wigner-d kernel.

        L (int): Harmonic band-limit.

        sampling (str): Sampling scheme.  Supported sampling schemes include
            {"mw", "mwss", "dh", "healpix"}.

        reality (bool, optional): Whether the signal on the sphere is real.  If so,
            conjugate symmetry is exploited to reduce computational costs.

        spin (int): Harmonic spin.

        nside (int): HEALPix Nside resolution parameter.  Only required
            if sampling="healpix".

    Returns:
        torch.tensor: Pixel-space coefficients.
    """
    if sampling.lower() == "mw":
        f = resampling_torch.mw_to_mwss(f, L, spin)

    if sampling.lower() in ["mw", "mwss"]:
        sampling = "mwss"
        f = resampling_torch.upsample_by_two_mwss(f, L, spin)

    m_offset = 1 if sampling in ["mwss", "healpix"] else 0
    m_start_ind = L - 1 if reality else 0

    if sampling.lower() == "healpix":
        ftm = hp.healpix_fft(f, L, nside, "torch", reality)[:, m_offset:]
        if reality:
            ftm = ftm[:, m_start_ind:]
    else:
        if reality:
            ftm = torch.fft.rfft(torch.real(f), axis=-1, norm="backward")
            if m_offset != 0:
                ftm = ftm[:, :-1]
        else:
            ftm = torch.fft.fft(f, axis=-1, norm="backward")
            ftm = torch.fft.fftshift(ftm, dim=[-1])[:, m_offset:]

    flm = torch.zeros(samples.flm_shape(L), dtype=torch.complex128)
    if sampling.lower() == "healpix":
        flm[:, m_start_ind:] = torch.einsum("...tlm, ...tm -> ...lm", kernel, ftm)
    else:
        flm[:, m_start_ind:].real = torch.einsum(
            "...tlm, ...tm -> ...lm", kernel, ftm.real
        )
        flm[:, m_start_ind:].imag = torch.einsum(
            "...tlm, ...tm -> ...lm", kernel, ftm.imag
        )

    if reality:
        flm[:, :m_start_ind] = torch.flip(
            (-1) ** (torch.arange(1, L) % 2) * torch.conj(flm[:, m_start_ind + 1 :]),
            dims=[-1],
        )

    return flm * (-1) ** spin
