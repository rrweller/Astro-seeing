#!/usr/bin/env python3
"""Figure for reports/landmask.md, drawn from the stores on /data (read-only).

Left: the ERA5 0.25° cells kept (land plus 1 km buffer). Right: La Palma at the
native 30″ GLOBE resolution: land, the 1 km buffer, and the outlines of the kept
ERA5 cells. Colours follow the entity: blue is always "kept ERA5 cell".

    pixi run python scripts/plot_landmask.py [out.png]
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import zarr
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch, Rectangle

from astroseeing.paths import Paths

# Reference palette (light mode): surface, slot 1 blue, slot 2 orange, chrome.
SURFACE, BLUE, ORANGE = "#fcfcfb", "#2a78d6", "#eb6834"
LAND_GRAY, INK, INK2, MUTED = "#c3c2b7", "#0b0b0b", "#52514e", "#898781"

SITE = ("Roque de los Muchachos (La Palma)", 28.7572, -17.8851)
BOX = (28.40, 28.95, -18.10, -17.60)  # south, north, west, east


def main(out: Path) -> None:
    root = Paths.from_env().data_root / "static" / "landmask"
    cells = zarr.open_group(str(root / "era5_0p25_cells_v1.zarr"), mode="r", zarr_format=3)
    keep = np.asarray(cells["keep"][...])
    glat = np.asarray(cells["latitude"][...])
    glon = np.asarray(cells["longitude"][...])
    globe = zarr.open_group(str(root / "globe_30s_land_buffer_v1.zarr"), mode="r", zarr_format=3)

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 9,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK2,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.titlecolor": INK,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
        }
    )
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [2.1, 1]}, layout="constrained"
    )

    # Left: kept cells on a −180..180 layout.
    shift = int(np.searchsorted(glon, 180.0))
    k = np.roll(keep, -shift, axis=1)
    ax1.imshow(
        k,
        extent=(-180, 180, -90.125, 90.125),
        cmap=ListedColormap([SURFACE, BLUE]),
        interpolation="nearest",
        aspect="equal",
    )
    ax1.set_title(f"ERA5 0.25° cells kept: {int(keep.sum()):,} of {keep.size:,}", loc="left")
    ax1.set_xticks(range(-180, 181, 60))
    ax1.set_yticks(range(-90, 91, 30))
    ax1.set_xlabel("longitude (°E)")
    ax1.set_ylabel("latitude (°N)")
    ax1.add_patch(Rectangle((BOX[2], BOX[0]), BOX[3] - BOX[2], BOX[1] - BOX[0], fill=False, ec=INK))
    ax1.annotate(
        "right panel", (BOX[2], BOX[0]), xytext=(-50, 5), fontsize=8, color=INK2,
        arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.8},
    )  # fmt: skip

    # Right: 30″ land and buffer around La Palma, with kept ERA5 cell outlines.
    s, n, w, e = BOX
    i0, i1 = int((90 - n) * 120), int(np.ceil((90 - s) * 120))
    j0, j1 = int((w + 180) * 120), int(np.ceil((e + 180) * 120))
    land = np.asarray(globe["land"][i0:i1, j0:j1])
    lob = np.asarray(globe["land_or_buffer"][i0:i1, j0:j1])
    cls = np.where(land, 1, np.where(lob, 2, 0))
    ext = (-180 + j0 / 120, -180 + j1 / 120, 90 - i1 / 120, 90 - i0 / 120)
    ax2.imshow(
        cls,
        extent=ext,
        cmap=ListedColormap([SURFACE, LAND_GRAY, ORANGE]),
        vmin=0,
        vmax=2,
        interpolation="nearest",
        aspect=1 / np.cos(np.radians((s + n) / 2)),
    )
    # ERA5 grid points on multiples of 0.25° (cells are ±0.125° boxes around them).
    lon360 = np.mod(np.arange(np.floor(w * 4) / 4, e + 0.26, 0.25), 360.0)
    for la in np.arange(np.floor(s * 4) / 4, n + 0.26, 0.25):
        for lo in lon360:
            iy = round((90 - la) / 0.25)
            ix = round(lo / 0.25) % glon.size
            if 0 <= iy < glat.size and keep[iy, ix]:
                lo180 = (lo + 180) % 360 - 180
                ax2.add_patch(
                    Rectangle((lo180 - 0.125, la - 0.125), 0.25, 0.25, fill=False, ec=BLUE, lw=1.4)
                )
    ax2.plot(SITE[2], SITE[1], marker="o", ms=8, mfc="none", mec=INK, mew=1.5)
    ax2.annotate(SITE[0], (SITE[2], SITE[1]), xytext=(-18.08, 28.915), fontsize=8, color=INK,
                 arrowprops={"arrowstyle": "-", "color": INK, "lw": 0.8})  # fmt: skip
    ax2.set_xlim(w, e)
    ax2.set_ylim(s, n)
    ax2.set_title("La Palma at 30″ (GLOBE)", loc="left")
    ax2.set_xlabel("longitude (°E)")
    ax2.legend(
        handles=[
            Patch(fc=LAND_GRAY, label="land"),
            Patch(fc=ORANGE, label="1 km buffer"),
            Patch(fc="none", ec=BLUE, lw=1.4, label="kept ERA5 cell"),
        ],
        loc="lower right",
        fontsize=8,
        frameon=True,
        facecolor=SURFACE,
        edgecolor=LAND_GRAY,
    )
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "reports/figures/landmask_overview.png"))
