import numpy as np
import logs


def compute_eighth(dl: np.ndarray, L: int, el: int) -> np.ndarray:
    """Compute Wigner-d at argument math:`\pi/2` for eighth of plane using
    Trapani & Navaza recursion.

    The Wigner-d plane is computed by recursion over :math:`\ell` (`el`).
    Thus, for :math:`\ell > 0` the plane must be computed already for
    :math:`\ell - 1`. For :math:`\ell = 0` the recusion is initialised.

    The Wigner-d plane :math:`d^\ell_{mm^\prime}(\pi/2)` (`el`) is indexed for
    :math:`-L < m, m^\prime < L` by `dl[m + L - 1, m' + L - 1]` but is only
    computed for the eighth of the plane
    :math:`m^\prime <= m <0 \ell, 0 <= m^\prime <= \ell`.
    Symmetry relations can be used to fill in the remainder of the plane if
    required (see :func:`~trapani_fill_eighth2quarter`,
    :func:`~trapani_fill_quarter2half`, :func:`~trapani_fill_half2full`).

    Warning:

        This recursion may not be stable above :math:`\ell \gtrsim 1024`.

    Args:

        dl: Wigner-d plane for :math:`\ell - 1` at math:`\pi/2`.  If
        :math:`\ell = 0` the recursion is initialised internally and the `dl`
        argument is ignored.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.

    Returns:

        Plane of Wigner-d for `el`, with eighth of plane computed.

    """

    _arg_checks(dl, L, el)

    if el == 0:

        dl[el + L - 1, el + L - 1] = 1.0

    else:

        dmm = np.zeros(L)

        # Equation (9) of T&N (2006).
        dmm[0] = -np.sqrt((2 * el - 1) / (2 * el)) * dl[el - 1 + (L - 1), 0 + (L - 1)]

        # Equation (10) of T&N (2006).
        for mm in range(1, el + 1):  # 1:el
            dmm[mm] = (
                np.sqrt(el)
                / np.sqrt(2)
                * np.sqrt(2 * el - 1)
                / np.sqrt(el + mm)
                / np.sqrt(el + mm - 1)
                * dl[el - 1 + (L - 1), mm - 1 + (L - 1)]
            )

        # Initialise dl for next el.
        for mm in range(el + 1):  # 0:el
            dl[el + (L - 1), mm + (L - 1)] = dmm[mm]

        # Equation (11) of T&N (2006).
        for mm in range(el + 1):  # 0:el

            # m = el-1 case (t2 = 0).
            m = el - 1
            dl[m + (L - 1), mm + (L - 1)] = (
                2
                * mm
                / np.sqrt(el - m)
                / np.sqrt(el + m + 1)
                * dl[m + 1 + (L - 1), mm + (L - 1)]
            )

            # Remaining m cases.
            for m in range(el - 2, mm - 1, -1):  # el-2:-1:mm
                t1 = (
                    2
                    * mm
                    / np.sqrt(el - m)
                    / np.sqrt(el + m + 1)
                    * dl[m + 1 + (L - 1), mm + (L - 1)]
                )
                t2 = (
                    np.sqrt(el - m - 1)
                    * np.sqrt(el + m + 2)
                    / np.sqrt(el - m)
                    / np.sqrt(el + m + 1)
                    * dl[m + 2 + (L - 1), mm + (L - 1)]
                )
                dl[m + (L - 1), mm + (L - 1)] = t1 - t2

    return dl


def fill_eighth2quarter(dl: np.ndarray, L: int, el: int) -> np.ndarray:
    """Fill in quarter of Wigner-d plane from eighth.

    The Wigner-d plane passed as an argument should be computed for the eighth
    of the plane :math:`m^\prime <= m <0 \ell, 0 <= m^\prime <= \ell`.  The
    returned plane is computed by symmetry for :math:`0 <= m, m^\prime <= \ell`.

    Args:

        dl: Eighth of Wigner-d plane for :math:`\ell` at math:`\pi/2`.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.

    Returns:

        Plane of Wigner-d for `el`, with quarter of plane computed.
    """

    _arg_checks(dl, L, el)

    # Diagonal symmetry to fill in quarter.
    for m in range(el + 1):  # 0:el
        for mm in range(m + 1, el + 1):  # m+1:el
            dl[m + (L - 1), mm + (L - 1)] = (-1) ** (m + mm) * dl[
                mm + (L - 1), m + (L - 1)
            ]

    return dl


def fill_quarter2half(dl: np.ndarray, L: int, el: int) -> np.ndarray:
    """Fill in half of Wigner-d plane from quarter.

    The Wigner-d plane passed as an argument should be computed for the quarter
    of the plane :math:`0 <= m, m^\prime <= \ell`.  The
    returned plane is computed by symmetry for
    :math:`-\ell <= m <= \ell, 0 <= m^\prime <= \ell`.

    Args:

        dl: Quarter of Wigner-d plane for :math:`\ell` at math:`\pi/2`.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.

    Returns:

        Plane of Wigner-d for `el`, with half of plane computed.
    """

    _arg_checks(dl, L, el)

    # Symmetry in m to fill in half.
    for mm in range(0, el + 1):  # 0:el
        for m in range(-el, 0):  # -el:-1
            dl[m + (L - 1), mm + (L - 1)] = (-1) ** (el + mm) * dl[
                -m + (L - 1), mm + (L - 1)
            ]

    return dl


def fill_half2full(dl: np.ndarray, L: int, el: int) -> np.ndarray:
    """Fill in full Wigner-d plane from half.

    The Wigner-d plane passed as an argument should be computed for the half
    of the plane :math:`-\ell <= m <= \ell, 0 <= m^\prime <= \ell`.  The
    returned plane is computed by symmetry for
    :math:`-\ell <= m, m^\prime <= \ell`.

    Args:

        dl: Quarter of Wigner-d plane for :math:`\ell` at math:`\pi/2`.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.

    Returns:

        Plane of Wigner-d for `el`, with full plane computed.
    """

    _arg_checks(dl, L, el)

    # Symmetry in mm to fill in remaining plane.
    for mm in range(-el, 0):  # -el:-1
        for m in range(-el, el + 1):  # -el:el
            dl[m + (L - 1), mm + (L - 1)] = (-1) ** (el + abs(m)) * dl[
                m + (L - 1), -mm + (L - 1)
            ]

    return dl


def compute_full(dl: np.ndarray, L: int, el: int) -> np.ndarray:
    """Compute Wigner-d at argument math:`\pi/2` for full plane using
    Trapani & Navaza recursion.

    The Wigner-d plane is computed by recursion over :math:`\ell` (`el`).
    Thus, for :math:`\ell > 0` the plane must be computed already for
    :math:`\ell - 1`. For :math:`\ell = 0` the recusion is initialised.

    The Wigner-d plane :math:`d^\ell_{mm^\prime}(\pi/2)` (`el`) is indexed for
    :math:`-L < m, m^\prime < L` by `dl[m + L - 1, m' + L - 1]`. The plane is
    computed directly for the eighth of the plane
    :math:`m^\prime <= m <0 \ell, 0 <= m^\prime <= \ell`
    (see :func:`~trapani_halfpi_eighth`).
    Symmetry relations are then used to fill in the remainder of the plane
    (see :func:`~trapani_fill_eighth2quarter`,
    :func:`~trapani_fill_quarter2half`, :func:`~trapani_fill_half2full`).

    Warning:

        This recursion may not be stable above :math:`\ell \gtrsim 1024`.

    Args:

        dl: Wigner-d plane for :math:`\ell - 1` at math:`\pi/2`.  If
        :math:`\ell = 0` the recursion is initialised internally and the `dl`
        argument is ignored.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.

    Returns:

        Plane of Wigner-d for `el`, with eighth of plane computed.

    """

    _arg_checks(dl, L, el)

    dl = compute_eighth(dl, L, el)
    dl = fill_eighth2quarter(dl, L, el)
    dl = fill_quarter2half(dl, L, el)
    dl = fill_half2full(dl, L, el)

    return dl


def _arg_checks(dl: np.ndarray, L: int, el: int):
    """Check arguments of Trapani functions.

    Args:

        dl: Wigner-d plane to check shape of.

        L: Harmonic band-limit.

        ell: Spherical harmonic degree :math:`\ell`.
    """

    assert 0 <= el < L
    assert dl.shape[0] == dl.shape[1] == 2 * L - 1
    if L > 1024:
        logs.warning_log("Trapani recursion may not be stable for L > 1024")
