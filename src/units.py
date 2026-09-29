"""
Shared quantity-formatting rules for any menu/display that shows a
chemical amount (moles, mass, or volume) -- not a "generic" number (a
slider's own min/max endpoint labels when they aren't a chemical amount,
a time/purity readout, ...), which keeps whatever formatting it already
uses. Nothing here is arcade-specific, so any bench can import it.

Every quantity kind picks a unit tier by magnitude and renders it at up
to 4 significant figures -- "1.000 g" (1 integer digit, 3 decimals) up
to "999.9 g" (3 integer digits, 1 decimal) -- the same rule for every
tier, so a screen never has to think about precision per-value:

    mass:   >=1000 g -> kg   |   >=1 g -> g   |   else -> mg
    volume: >=1000 mL -> L   |   else -> mL
    moles:  >=1 mol -> mol   |   else -> mmol

A quantity below its smallest tier's stated minimum (e.g. 3 mg, 0.4 mL)
still displays in that smallest unit rather than switching to something
even smaller -- _format_in_unit's significant-figure rule naturally
grows the decimal count for an in-unit value under 1 (e.g. 0.003 for
3 mg), so nothing rounds away to "0 mg".
"""

# Each tier: (threshold, unit_label, unit_size_in_base_units) -- the base
# unit is grams for mass, mL for volume, mol for moles. Checked largest
# threshold first; the last tier's threshold of 0.0 always matches, so
# every value (however small) lands somewhere.
_MASS_TIERS = [
    (1000.0, "kg", 1000.0),
    (1.0, "g", 1.0),
    (0.0, "mg", 0.001),
]
_VOLUME_TIERS = [
    (1000.0, "L", 1000.0),
    (0.0, "mL", 1.0),
]
_MOLES_TIERS = [
    (1.0, "mol", 1.0),
    (0.0, "mmol", 0.001),
]


def _format_in_unit(value_in_unit: float, unit: str, sig_figs: int = 4) -> str:
    if value_in_unit <= 0:
        return f"0 {unit}"
    integer_digits = len(str(int(value_in_unit))) if value_in_unit >= 1 else 1
    decimals = max(0, sig_figs - integer_digits)
    return f"{value_in_unit:.{decimals}f} {unit}"


def _format_tiered(value: float, tiers: list[tuple[float, str, float]]) -> str:
    for threshold, unit, unit_size in tiers:
        if value >= threshold:
            return _format_in_unit(value / unit_size, unit)
    threshold, unit, unit_size = tiers[-1]  # unreachable (last threshold is 0.0), kept for safety
    return _format_in_unit(value / unit_size, unit)


def format_mass(grams: float) -> str:
    """grams -> "<value> mg/g/kg" at up to 4 significant figures."""
    return _format_tiered(grams, _MASS_TIERS)


def format_volume(ml: float) -> str:
    """mL -> "<value> mL/L" at up to 4 significant figures."""
    return _format_tiered(ml, _VOLUME_TIERS)


def format_moles(mol: float) -> str:
    """mol -> "<value> mmol/mol" at up to 4 significant figures."""
    return _format_tiered(mol, _MOLES_TIERS)


def format_native_amount(species, native_amount: float) -> str:
    """A species' own native-unit amount (grams for a solid, mL for a
    liquid/solution) -- format_mass()/format_volume() picked by
    species.state, so a caller with a ChemicalSpecies doesn't have to
    branch on state itself."""
    if species.state == "solid":
        return format_mass(native_amount)
    return format_volume(native_amount)
