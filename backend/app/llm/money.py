"""Money units for AI spend. Ledger integrity is an invariant, never a setting.

Every cost, reservation and sum is an integer number of **micros**: millionths of the budget
currency's major unit (1 USD = 1_000_000 micros). Small calls are never rounded up to a whole
cent; conversion to minor units (cents) happens only for display and for comparing with the
owner's caps, which are entered in minor units. Budget currencies have two decimal places.
"""

from __future__ import annotations

MICROS_PER_MINOR = 10_000  # 1 cent = 10_000 micros (two-decimal currencies)


def minor_to_micros(minor: int) -> int:
    return int(minor) * MICROS_PER_MINOR


def micros_to_minor(micros: int) -> int:
    """For display only: nearest minor unit, halves rounded up."""
    return (int(micros) + MICROS_PER_MINOR // 2) // MICROS_PER_MINOR
