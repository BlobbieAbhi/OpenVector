"""
compare_drag.py

Worked example: loads a real OpenRocket drag export from the ARGUS TVC
rocket project via OpenVector's DragModel, and compares it against a
constant-Cd baseline (a stand-in for AeroVECTOR's simplified default
empirical drag build-up).

This demonstrates the actual value OpenVector adds: a real Mach-dependent
drag curve pulled straight from OpenRocket simulation data, instead of a
single fixed Cd value.

Run from the repo root:
    python examples/argus/compare_drag.py

Produces argus_drag_comparison.png in this same folder.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Allow running this script directly from examples/argus/ without installing
# the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openvector import DragModel

HERE = Path(__file__).resolve().parent
EXPORT_CSV = HERE / "argus_openrocket_export.csv"
OUTPUT_PNG = HERE / "argus_drag_comparison.png"


def main():
    drag_model = DragModel(str(EXPORT_CSV))

    print(f"Loaded {len(drag_model._points)} data points from {EXPORT_CSV.name}")
    print(f"Has AoA data: {drag_model.has_aoa}")
    print(f"Mach range: {drag_model._machs[0]:.3f} - {drag_model._machs[-1]:.3f}")

    mach_range = np.linspace(drag_model._machs[0], drag_model._machs[-1], 300)
    cd_raw = np.array([drag_model.get_cd(mach=m) for m in mach_range])

    # NOTE: raw OpenRocket exports commonly contain spurious high-Cd spikes
    # at very low Mach (near launch/liftoff), because Cd = drag / dynamic
    # pressure is numerically unstable when velocity is near zero. This is
    # a real characteristic of the source data, not a bug in DragModel --
    # we show it here rather than hiding it, and apply a simple physical
    # clamp (Cd rarely exceeds ~3 for a subsonic airframe) as one
    # reasonable way to filter it for plotting/sim use.
    cd_clamped = np.clip(cd_raw, 0, 3.0)

    n_spikes = int(np.sum(cd_raw > 3.0))
    print(f"Note: {n_spikes}/{len(cd_raw)} sampled points show low-Mach Cd "
          f"spikes (>3.0) from raw OpenRocket data noise near liftoff; "
          f"clamped in the 'cleaned' curve below.")

    # A flat baseline Cd, representative of treating drag as constant --
    # the kind of simplification you get without a real imported table.
    baseline_cd = float(np.mean(cd_clamped))

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].plot(mach_range, cd_raw, color="tab:red", linewidth=1.5)
    axes[0].set_title("Raw OpenRocket export\n(low-Mach Cd spikes near liftoff)")
    axes[0].set_xlabel("Mach number")
    axes[0].set_ylabel("Drag coefficient (Cd)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(mach_range, cd_clamped, label="OpenVector (clamped)", linewidth=2)
    axes[1].axhline(baseline_cd, color="gray", linestyle="--",
                     label=f"Constant-Cd baseline ({baseline_cd:.3f})")
    axes[1].set_title("Cleaned for use\n(clamped at physically reasonable Cd)")
    axes[1].set_xlabel("Mach number")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    fig.suptitle("ARGUS drag curve: OpenVector import, raw vs. cleaned, vs. a constant-Cd baseline")
    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150)
    print(f"Saved comparison plot to {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
