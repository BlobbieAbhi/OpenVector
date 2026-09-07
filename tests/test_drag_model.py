"""
tests/test_drag_model.py

Unit tests for openvector.DragModel, using the real ARGUS OpenRocket
export in examples/argus/.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openvector import DragModel

REPO_ROOT = Path(__file__).resolve().parents[1]
ARGUS_CSV = REPO_ROOT / "examples" / "argus" / "argus_openrocket_export.csv"


@pytest.fixture(scope="module")
def argus_drag_model():
    return DragModel(str(ARGUS_CSV))


def test_loads_data(argus_drag_model):
    """The model should successfully parse points from the real export."""
    assert len(argus_drag_model._points) > 0


def test_no_aoa_column(argus_drag_model):
    """The ARGUS OpenRocket export has no AoA column, so the model
    should correctly degrade to 1D Mach-only interpolation."""
    assert argus_drag_model.has_aoa is False


def test_mid_mach_cd_is_reasonable(argus_drag_model):
    """
    At a representative mid-flight Mach number (0.3), Cd should be a
    physically reasonable subsonic value -- not one of the spurious
    low-Mach liftoff spikes seen near Mach ~0.01-0.03.
    """
    cd = argus_drag_model.get_cd(mach=0.3)
    assert 0.5 < cd < 2.0, f"Expected a reasonable subsonic Cd, got {cd}"


def test_low_mach_spike_does_not_crash(argus_drag_model):
    """
    The raw export contains real Cd spikes near liftoff (Mach ~0.01-0.03)
    due to numerically unstable Cd at near-zero dynamic pressure.
    get_cd() should still return a float without raising, even though
    the value itself may be an artifact of the source data.
    """
    cd = argus_drag_model.get_cd(mach=0.01)
    assert isinstance(cd, float)


def test_out_of_range_mach_is_clamped(argus_drag_model):
    """Mach values outside the table's range should clamp to the
    nearest edge rather than extrapolating or raising."""
    machs = argus_drag_model._machs
    cd_below = argus_drag_model.get_cd(mach=machs[0] - 1.0)
    cd_at_min = argus_drag_model.get_cd(mach=machs[0])
    assert cd_below == pytest.approx(cd_at_min)

    cd_above = argus_drag_model.get_cd(mach=machs[-1] + 1.0)
    cd_at_max = argus_drag_model.get_cd(mach=machs[-1])
    assert cd_above == pytest.approx(cd_at_max)


def test_missing_file_raises_clear_error():
    """A nonexistent CSV path should raise, not silently produce an
    empty/unusable model."""
    with pytest.raises(Exception):
        DragModel("this_file_does_not_exist.csv")