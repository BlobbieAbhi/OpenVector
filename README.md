# OpenVector

**An open-source drag-model bridge that brings RASAero-grade, multi-axis (Mach + AoA) drag data into AeroVECTOR's 6-DOF sim — straight from your OpenRocket or RASAero II exports.**

## Why

[AeroVECTOR](https://github.com/GuidodiPasquo/AeroVECTOR) is a great open-source 6-DOF rocket flight simulator, but its default drag model is a simplified empirical build-up (friction + pressure + base drag). RASAero II offers much richer Cd-vs-Mach/AoA data from real wind-tunnel-correlated methods — but it's Windows-only and doesn't talk to AeroVECTOR.

OpenVector bridges that gap. It reads Cd tables exported from **either** OpenRocket **or** RASAero II and drops them straight into AeroVECTOR's simulation loop, so anyone gets higher-fidelity drag modeling without leaving the open-source ecosystem, and without needing Windows or RASAero at all — an OpenRocket export alone is enough to get started.

## What it does

- **`DragModel`** — parses a RASAero II ("Export All Data") or OpenRocket ("Export Data") CSV. Column names are matched by keyword, not exact position, so exports from either tool work without manual renaming.
- **2D interpolation** over Mach and Angle of Attack when both are present in the export; degrades gracefully to 1D Mach-only interpolation when AoA isn't available (the common case for most OpenRocket exports).
- **Drop-in integration** with AeroVECTOR via two new methods on its rocket/aerodynamics class: `set_drag_model(csv_path)` and `clear_drag_model()` — no rewrite of AeroVECTOR's simulation core required.

## Quick start

```python
from openvector import DragModel

drag_model = DragModel("my_rocket_openrocket_export.csv")
cd = drag_model.get_cd(mach=0.85, aoa_deg=2.3)
```

## Wiring into AeroVECTOR

1. Drop `openvector/drag_model.py` into your AeroVECTOR fork (e.g. next to `rocket_functions.py`).
2. In your rocket/aerodynamics class:

```python
from openvector.drag_model import DragModel

def set_drag_model(self, csv_path, use_power_on=False):
    self.drag_model = DragModel(csv_path, use_power_on=use_power_on)

def clear_drag_model(self):
    self.drag_model = None
```

3. Wherever Cd is currently computed (e.g. `_calculate_cd`), check for an active drag model first:

```python
def _calculate_cd(self, aoa):
    if self.drag_model is not None:
        self.cd0 = self.drag_model.get_cd(mach=self.mach, aoa_deg=aoa * RAD2DEG)
        return
    # ...fall back to AeroVECTOR's default empirical calculation
```

See `examples/argus/` for a complete real-world example: an OpenRocket export from the ARGUS TVC rocket project, with a comparison plot of AeroVECTOR's default drag curve vs. the imported table.

## Getting a drag export

- **OpenRocket**: open your rocket, run a simulation, then *Plot/Export → Export Data* tab. Select **Mach number** and **Drag coefficient** as columns, and export to CSV.
- **RASAero II**: run *Flight Data* or component analysis, then **Export All Data** — this includes Mach, Alpha, and both CD Power-Off/Power-On columns for higher fidelity.

## Status

Core `DragModel` parser and interpolation are complete and tested against real OpenRocket exports. AeroVECTOR integration pattern is documented and working. Contributions for other sim targets welcome.

## License

MIT
