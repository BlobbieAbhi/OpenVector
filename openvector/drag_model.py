"""
drag_data.py

Parses exported Cd-vs-Mach(/AoA) tables from either RASAero II or
OpenRocket and provides a drop-in replacement for AeroVECTOR's default
drag coefficient lookup, using 2D interpolation over Mach number and
Angle of Attack (AoA).

Supported source formats
-------------------------
RASAero II ("Export All Data"):
    Mach, Alpha (deg), CD, CD Power-Off, CD Power-On, CL, CP, ...

OpenRocket (Plot/Export -> Export Data tab):
    Mach number, Drag coefficient  (AoA column optional/rare in OR exports)
    -- OpenRocket also offers "Axial drag coefficient", "Friction drag
       coefficient", "Pressure drag coefficient", "Base drag coefficient".
       "Drag coefficient" (aka CD, total) is the closest match to
       RASAero's CD Power-Off and is preferred by default.

This module is defensive about column naming since headers vary between
tools/versions -- it searches for the right columns by keyword rather
than assuming exact names, so exports from either tool work without
manual renaming.

Usage:
    from drag_data import DragModel

    drag_model = DragModel("argus_rasaero.csv")   # RASAero or OpenRocket export
    cd = drag_model.get_cd(mach=0.85, aoa_deg=2.3)

To wire into AeroVECTOR, see integration notes at the bottom of this file.
"""

import csv
import bisect
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class _AeroPoint:
    mach: float
    aoa_deg: float
    cd: float


class DragModel:
    """
    Loads a RASAero II or OpenRocket Cd table and interpolates
    Cd(Mach, AoA).

    If the CSV has no AoA column (RASAero power-off exports, and most
    OpenRocket exports, are Mach-only), the model degrades gracefully to
    1D interpolation over Mach only, and get_cd() ignores aoa_deg.
    """

    # Candidate header names seen across RASAero II versions and
    # OpenRocket's Export Data tab.
    MACH_KEYS = ["mach", "mach number", "mach no"]
    AOA_KEYS = ["alpha", "aoa", "angle of attack", "alpha (deg)"]
    CD_KEYS_PREFERRED = [
        "cd power-off", "cd poweroff", "cd (power off)",
    ]
    CD_KEYS_FALLBACK = [
        "cd", "cd total", "drag coefficient", "axial drag coefficient",
    ]

    def __init__(self, csv_path: str, use_power_on: bool = False):
        """
        Args:
            csv_path: path to a RASAero II or OpenRocket exported CSV.
            use_power_on: if True, prefer "CD Power-On" column when present
                (RASAero only -- use this only for the boosted/motor-burn
                portion of flight if you're running separate models for
                burn vs. coast; most users should leave this False and use
                Power-Off/total Cd, the more conservative, commonly-used
                reference value. OpenRocket exports don't distinguish
                power-on/off, so this flag has no effect on them).
        """
        self.has_aoa = False
        self._points: List[_AeroPoint] = []
        self._load(csv_path, use_power_on)

        if not self._points:
            raise ValueError(
                f"No usable Cd data parsed from {csv_path}. "
                f"Check that the file is a RASAero II 'Export All Data' CSV "
                f"or an OpenRocket 'Export Data' CSV with Mach and a drag "
                f"coefficient column selected."
            )

        # Sorted unique mach and aoa grids for interpolation.
        self._machs = sorted(set(p.mach for p in self._points))
        self._aoas = sorted(set(p.aoa_deg for p in self._points)) if self.has_aoa else [0.0]

        # Build lookup dict keyed by (mach, aoa) -> cd for exact/grid points.
        self._grid = {}
        for p in self._points:
            key = (p.mach, p.aoa_deg if self.has_aoa else 0.0)
            self._grid[key] = p.cd

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------
    def _find_col(self, header_row: List[str], candidates: List[str]) -> Optional[int]:
        normalized = [h.strip().lower() for h in header_row]
        for cand in candidates:
            for i, h in enumerate(normalized):
                if h == cand:
                    return i
        # fallback: substring match
        for cand in candidates:
            for i, h in enumerate(normalized):
                if cand in h:
                    return i
        return None

    def _load(self, csv_path: str, use_power_on: bool):
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = [r for r in reader if any(cell.strip() for cell in r)]

        if not rows:
            return

        # OpenRocket prefixes every exported line with '#', including the
        # real header row, and interleaves '# Event ...' comment lines
        # into the data section. Strip a leading '#' before matching, and
        # search all rows (not just row 0) for the real header.
        def _strip_hash(cell):
            c = cell.strip()
            if c.startswith("#"):
                c = c[1:].strip()
            return c

        cd_keys = self.CD_KEYS_PREFERRED if not use_power_on else [
            "cd power-on", "cd poweron", "cd (power on)"
        ]

        header_idx = None
        mach_idx = aoa_idx = cd_idx = None
        for i, row in enumerate(rows):
            candidate = [_strip_hash(cell) for cell in row]
            m_idx = self._find_col(candidate, self.MACH_KEYS)
            c_idx = self._find_col(candidate, cd_keys)
            if c_idx is None:
                c_idx = self._find_col(candidate, self.CD_KEYS_FALLBACK)
            if m_idx is not None and c_idx is not None:
                header_idx = i
                mach_idx = m_idx
                cd_idx = c_idx
                aoa_idx = self._find_col(candidate, self.AOA_KEYS)
                break

        if header_idx is None or mach_idx is None or cd_idx is None:
            raise ValueError(
                f"Could not locate Mach and/or Cd columns in: {csv_path}. "
                f"Expected something like 'Mach'/'Mach number' and "
                f"'CD Power-Off'/'Drag coefficient'."
            )

        self.has_aoa = aoa_idx is not None

        for row in rows[header_idx + 1:]:
            if row and row[0].strip().startswith("#"):
                continue  # skip OpenRocket inline event/comment rows
            try:
                mach = float(row[mach_idx])
                cd = float(row[cd_idx])
                aoa = float(row[aoa_idx]) if self.has_aoa else 0.0
            except (ValueError, IndexError):
                continue  # skip malformed/blank rows
            self._points.append(_AeroPoint(mach=mach, aoa_deg=aoa, cd=cd))

    # ------------------------------------------------------------------
    # Interpolation
    # ------------------------------------------------------------------
    @staticmethod
    def _lerp(x0, y0, x1, y1, x):
        if x1 == x0:
            return y0
        t = (x - x0) / (x1 - x0)
        return y0 + t * (y1 - y0)

    def _bracket(self, sorted_vals: List[float], x: float) -> Tuple[float, float]:
        """Return (lo, hi) bracketing values, clamped at the ends."""
        if x <= sorted_vals[0]:
            return sorted_vals[0], sorted_vals[0]
        if x >= sorted_vals[-1]:
            return sorted_vals[-1], sorted_vals[-1]
        idx = bisect.bisect_right(sorted_vals, x)
        return sorted_vals[idx - 1], sorted_vals[idx]

    def _cd_at(self, mach: float, aoa: float) -> float:
        return self._grid.get((mach, aoa), None)

    def get_cd(self, mach: float, aoa_deg: float = 0.0) -> float:
        """
        Returns interpolated Cd at the given Mach number and AoA (degrees).
        Values outside the table range are clamped to the nearest edge
        (RASAero tables commonly run Mach 0 - 5+; extrapolation beyond
        that is not physically reliable, so we clamp rather than guess).
        """
        m_lo, m_hi = self._bracket(self._machs, mach)

        if not self.has_aoa:
            cd_lo = self._cd_at(m_lo, 0.0)
            cd_hi = self._cd_at(m_hi, 0.0)
            return self._lerp(m_lo, cd_lo, m_hi, cd_hi, mach)

        a_lo, a_hi = self._bracket(self._aoas, aoa_deg)

        # Bilinear interpolation over the 4 corners (mach, aoa) grid.
        c00 = self._grid.get((m_lo, a_lo))
        c01 = self._grid.get((m_lo, a_hi))
        c10 = self._grid.get((m_hi, a_lo))
        c11 = self._grid.get((m_hi, a_hi))

        # If the table isn't a full rectangular grid, fall back to nearest
        # available corner rather than crashing.
        if None in (c00, c01, c10, c11):
            nearest = min(
                self._points,
                key=lambda p: (p.mach - mach) ** 2 + (p.aoa_deg - aoa_deg) ** 2,
            )
            return nearest.cd

        cd_lo = self._lerp(a_lo, c00, a_hi, c01, aoa_deg)
        cd_hi = self._lerp(a_lo, c10, a_hi, c11, aoa_deg)
        return self._lerp(m_lo, cd_lo, m_hi, cd_hi, mach)


# ----------------------------------------------------------------------
# INTEGRATION NOTES for AeroVECTOR
# ----------------------------------------------------------------------
# AeroVECTOR (upstream GuidodiPasquo/AeroVECTOR) computes drag inside its
# simulation loop, typically in a rocket/aerodynamics module where it pulls
# a Cd value (often currently a constant or a simple function of Mach) and
# uses it with dynamic pressure and reference area to get drag force.
#
# Steps to wire this in:
#
# 1. Drop this file into your fork's source tree (e.g. next to the main
#    simulation module) and place your RASAero CSV export alongside your
#    other config/data files (e.g. /Data/ or /Simulator/ depending on your
#    fork's layout).
#
# 2. At sim setup time (wherever AeroVECTOR currently reads rocket
#    parameters from its config file), instantiate:
#
#       from drag_data import DragModel
#       drag_model = DragModel("Data/argus_rasaero.csv")
#
# 3. Find where AeroVECTOR currently computes/returns Cd -- search your
#    fork for the drag coefficient function (likely named something like
#    `calculate_cd`, `get_cd`, or inline as `self.cd = ...` inside the
#    aerodynamics/rocket class). Replace that computation with:
#
#       cd = drag_model.get_cd(mach=current_mach, aoa_deg=current_aoa_deg)
#
#    Make sure current_mach and current_aoa_deg are pulled from the same
#    state variables AeroVECTOR already tracks each timestep (it computes
#    Mach from velocity/speed of sound, and AoA from the velocity vector
#    vs. body axis -- both should already exist in the 6-DOF state).
#
# 4. If AeroVECTOR's existing drag function only takes Mach (no AoA), you
#    can still call get_cd(mach=..., aoa_deg=0.0) and get a 1D Mach-only
#    lookup -- send me that function's exact signature and I'll adapt the
#    call site precisely.
#
# 5. Send me the actual file/function (e.g. paste the aerodynamics module
#    from your fork) and I'll write the exact patch/diff rather than these
#    generic instructions.
