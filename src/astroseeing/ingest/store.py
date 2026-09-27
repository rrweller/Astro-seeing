"""Write decoded ERA5 arrays to Zarr v3 (sharded) atomically, and verify them.

Write protocol (AGENTS.md "Writes: atomic (write temp → verify → rename)"):

1. write the whole store into ``.<name>.tmp-<uuid>`` next to the final path;
2. read it back and compare every array bit-for-bit with what was meant to be written;
3. fsync the files and directories, then ``rename`` to the final name;
4. read the final store back and compare again.

A final path that already exists is never overwritten: if it holds the same
content (same content hash) the write is a no-op, otherwise it is an error.

Layouts:
* ``grid``: (time[, level], latitude, longitude) — validation boxes, all hours.
* ``cells``: (time[, level], cell) — only cells where ``cell_mask`` is True (land
  plus buffer), with optional per-(time, cell) night mask; masked values are NaN
  and counted in the store's ``qc`` attribute.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.ingest.decode import DecodedGrib
from astroseeing.qc import QCCounts

TARGET_CHUNK_BYTES = 4 << 20  # ≥ 1 MB (AGENTS.md), small enough for partial reads
TIME_UNITS = "seconds since 1970-01-01T00:00:00Z"


@dataclass
class Prepared:
    """Arrays exactly as they will be stored."""

    dims: tuple[str, ...]
    coords: dict[str, tuple[tuple[str, ...], np.ndarray]]
    data: dict[str, np.ndarray]
    qc: QCCounts

    def content_sha256(self) -> str:
        h = hashlib.sha256()
        for name in sorted(self.coords):
            dims, arr = self.coords[name]
            h.update(name.encode())
            h.update(json.dumps(dims).encode())
            h.update(np.ascontiguousarray(arr).tobytes())
        for name in sorted(self.data):
            h.update(name.encode())
            h.update(np.ascontiguousarray(self.data[name]).tobytes())
        return h.hexdigest()


def prepare(
    dec: DecodedGrib,
    cell_mask: np.ndarray | None = None,
    keep_hours: np.ndarray | None = None,
) -> Prepared:
    """Arrange decoded arrays into the chosen layout, applying and counting masks.

    ``cell_mask``: bool (nlat, nlon); ``keep_hours``: bool (ntime, ncell) for the
    ``cells`` layout (requires ``cell_mask``).
    """
    qc = QCCounts()
    for var, n in dec.missing.items():
        qc.add(f"grib_missing_values_{var}", n, dec.data[var].size)
    times = dec.times.astype("datetime64[s]").astype(np.int64)
    coords: dict[str, tuple[tuple[str, ...], np.ndarray]] = {"time": (("time",), times)}
    if dec.levels is not None:
        coords["level"] = (("level",), dec.levels)
    data: dict[str, np.ndarray] = {}
    if cell_mask is None:
        if keep_hours is not None:
            raise ValueError("keep_hours needs the cells layout (cell_mask)")
        coords["latitude"] = (("latitude",), dec.lat)
        coords["longitude"] = (("longitude",), dec.lon)
        dims = dec.dims
        data = {k: np.ascontiguousarray(v) for k, v in dec.data.items()}
    else:
        cell_mask = np.asarray(cell_mask, bool)
        if cell_mask.shape != (dec.lat.size, dec.lon.size):
            raise ValueError(
                f"cell_mask shape {cell_mask.shape} != grid {(dec.lat.size, dec.lon.size)}"
            )
        iy, ix = np.nonzero(cell_mask)
        qc.add("cells_dropped_not_land", int((~cell_mask).sum()), cell_mask.size)
        coords["cell_lat"] = (("cell",), dec.lat[iy])
        coords["cell_lon"] = (("cell",), dec.lon[ix])
        coords["cell_index"] = (("cell",), (iy * dec.lon.size + ix).astype(np.int64))
        dims = (*dec.dims[:-2], "cell")
        for k, v in dec.data.items():
            arr = np.ascontiguousarray(v[..., iy, ix])
            if keep_hours is not None:
                keep = np.asarray(keep_hours, bool)
                if keep.shape != (times.size, iy.size):
                    raise ValueError(f"keep_hours shape {keep.shape} != {(times.size, iy.size)}")
                drop = ~keep
                if arr.ndim == 3:
                    drop = drop[:, None, :]
                drop_full = np.broadcast_to(drop, arr.shape)
                qc.add(f"night_masked_values_{k}", int(drop_full.sum()), arr.size)
                arr = np.where(drop_full, np.float32(np.nan), arr)
            data[k] = arr
    return Prepared(dims=dims, coords=coords, data=data, qc=qc)


SPLITTABLE_DIMS = ("latitude", "longitude", "cell")


def choose_chunks(
    shape: tuple[int, ...],
    dims: tuple[str, ...],
    itemsize: int = 4,
    target: int = TARGET_CHUNK_BYTES,
) -> tuple[int, ...]:
    """Keep time and level whole; halve the largest spatial dim until ≤ ``target`` bytes."""
    chunks = list(shape)
    spatial = [i for i, d in enumerate(dims) if d in SPLITTABLE_DIMS]
    while np.prod(chunks) * itemsize > target and any(chunks[i] > 1 for i in spatial):
        i = max(spatial, key=lambda j: chunks[j])
        chunks[i] = (chunks[i] + 1) // 2
    return tuple(int(c) for c in chunks)


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fd = os.open(os.path.join(dirpath, f), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        fd = os.open(dirpath, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path: Path, prep: Prepared, attrs: dict[str, Any]) -> None:
    import zarr
    from zarr.codecs import BloscCodec

    g = zarr.open_group(str(path), mode="w-", zarr_format=3)
    for name, (dims, arr) in prep.coords.items():
        a = g.create_array(
            name,
            shape=arr.shape,
            dtype=arr.dtype,
            chunks=arr.shape,
            dimension_names=dims,
            attributes={"units": TIME_UNITS, "calendar": "proleptic_gregorian"}
            if name == "time"
            else {},
        )
        a[...] = arr
    comp = [BloscCodec(cname="zstd", clevel=5, shuffle="shuffle")]
    for name, arr in prep.data.items():
        chunks = choose_chunks(arr.shape, prep.dims, arr.dtype.itemsize)
        a = g.create_array(
            name,
            shape=arr.shape,
            dtype=arr.dtype,
            chunks=chunks,
            shards=arr.shape,
            compressors=comp,
            fill_value=np.nan,
            dimension_names=prep.dims,
        )
        a[...] = arr
    g.attrs.update(attrs)


def read_store(path: Path) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    import zarr

    g = zarr.open_group(str(path), mode="r", zarr_format=3)
    arrays = {name: np.asarray(a[...]) for name, a in g.arrays()}
    return arrays, dict(g.attrs)


def compare_store(path: Path, prep: Prepared) -> list[str]:
    """Bit-for-bit comparison of a store with the prepared arrays; returns problems."""
    arrays, attrs = read_store(path)
    problems: list[str] = []
    expected = {**{k: v[1] for k, v in prep.coords.items()}, **prep.data}
    if set(arrays) != set(expected):
        problems.append(f"array names {sorted(arrays)} != {sorted(expected)}")
    for name, want in expected.items():
        got = arrays.get(name)
        if got is None:
            continue
        if got.shape != want.shape or got.dtype != want.dtype:
            problems.append(f"{name}: {got.shape}/{got.dtype} != {want.shape}/{want.dtype}")
        elif not np.array_equal(got, want, equal_nan=np.issubdtype(want.dtype, np.floating)):
            problems.append(f"{name}: values differ")
    if attrs.get("content_sha256") != prep.content_sha256():
        problems.append("content_sha256 attribute mismatch")
    return problems


@dataclass
class WriteResult:
    path: Path
    content_sha256: str
    already_present: bool
    qc: QCCounts


def write_store_atomic(final: Path, prep: Prepared, attrs: dict[str, Any]) -> WriteResult:
    final = Path(final)
    digest = prep.content_sha256()
    if final.exists():
        _, existing = read_store(final)
        if existing.get("content_sha256") == digest and not compare_store(final, prep):
            return WriteResult(final, digest, True, prep.qc)
        raise FileExistsError(f"{final} exists with different content; not overwriting (ASK Riley)")
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.parent / f".{final.name}.tmp-{uuid.uuid4().hex[:12]}"
    all_attrs = {**attrs, "content_sha256": digest, "qc": prep.qc.as_dict()}
    try:
        _write(tmp, prep, all_attrs)
        problems = compare_store(tmp, prep)
        if problems:
            raise OSError(f"read-back of {tmp} failed: {problems}")
        _fsync_tree(tmp)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)  # our own temp directory only
        raise
    fd = os.open(final.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    problems = compare_store(final, prep)
    if problems:
        raise OSError(f"verification of {final} after rename failed: {problems}")
    return WriteResult(final, digest, False, prep.qc)
