"""Standard locations and storage guards (AGENTS.md "Environment", "Storage").

Defaults are the CT layout; override with environment variables for tests or
other machines:

    ASTRO_DATA_ROOT   /data/astro        durable store on the NAS (NFS)
    ASTRO_STAGING     /staging           local SSD for downloads in flight
    ASTRO_STATE_DIR   ~/.local/state/astro   SQLite manifest (never on NFS)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

NETWORK_FS_TYPES = frozenset(
    {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p", "afs", "ceph", "glusterfs"}
)


@dataclass(frozen=True)
class Paths:
    data_root: Path
    staging: Path
    state_dir: Path

    @classmethod
    def from_env(cls) -> Paths:
        return cls(
            data_root=Path(os.environ.get("ASTRO_DATA_ROOT", "/data/astro")),
            staging=Path(os.environ.get("ASTRO_STAGING", "/staging")),
            state_dir=Path(os.environ.get("ASTRO_STATE_DIR", Path.home() / ".local/state/astro")),
        )

    @property
    def manifest(self) -> Path:
        return self.state_dir / "manifest.sqlite"

    @property
    def grib_dir(self) -> Path:
        return self.staging / "grib"

    @property
    def tmp_dir(self) -> Path:
        return self.staging / "tmp"

    @property
    def manifest_exports(self) -> Path:
        return self.data_root / "manifest-exports"

    @property
    def static_dir(self) -> Path:
        return self.data_root / "static"

    def era5_dir(self, kind: str) -> Path:
        return self.data_root / "era5" / kind


def filesystem_type(path: Path) -> str:
    """Filesystem type of the mount containing ``path`` (from /proc/self/mounts)."""
    p = Path(path).resolve()
    while not p.exists():
        p = p.parent
    best, best_type = "", "unknown"
    try:
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                inside = str(p) == mnt or str(p).startswith(mnt.rstrip("/") + "/")
                if inside and len(mnt) > len(best):
                    best, best_type = mnt, parts[2]
    except OSError:
        return "unknown"
    return best_type


def assert_local_filesystem(path: Path, what: str = "SQLite database") -> None:
    """Refuse network filesystems (docs/RESEARCH.md §9 pitfall 16)."""
    fs = filesystem_type(path)
    if fs in NETWORK_FS_TYPES or fs.startswith("nfs"):
        raise RuntimeError(f"{what} must not live on a network filesystem: {path} is on {fs}")


class StorageUnresponsive(RuntimeError):
    """The NAS did not answer in time (hard NFS mounts hang instead of failing)."""


def probe_responsive(path: Path, timeout_s: float = 30.0) -> None:
    """``stat`` the path in a child process with a timeout.

    A hung hard-mounted NFS share blocks the calling process in uninterruptible
    sleep; doing the probe in a child keeps this process alive so it can log and
    exit cleanly instead of hanging with it.
    """
    try:
        subprocess.run(
            ["stat", "--", str(path)], check=True, capture_output=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired as e:
        raise StorageUnresponsive(f"{path} did not respond within {timeout_s} s") from e
    except subprocess.CalledProcessError as e:
        raise FileNotFoundError(f"{path}: {e.stderr.decode(errors='replace').strip()}") from e
