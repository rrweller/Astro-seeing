"""Deploy the page (F1 spec #47 Module 11, ticket #62, D52 item 5): ``astro web deploy``.

The site folder (``/staging/forecast/site/`` on the CT) holds:

- ``<commit>/``: a copy of that commit's ``web/`` plus ``version.json``
  (``{"commit": …}``, which the page's About panel reads, D73 item 2);
- ``<commit>.sha256``: the copy's checksums (``sha256sum -c`` format), checked before
  the copy is put live again;
- ``current``: the symlink nginx serves, and ``previous``: the one a rollback restores;
- ``deploys.jsonl``: one line per deploy or rollback.

The copy comes from the commit's git objects, never from the working tree, so a branch
checkout or an uncommitted edit on the CT can't change the live page. It is written to
a temp folder, read back and checked, then renamed (AGENTS.md "Writes"); ``current``
is swapped with one ``rename(2)``, so it always exists. Files are world-readable, since
nginx runs as its own dynamic user (D52 item 9).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

CURRENT = "current"
PREVIOUS = "previous"
VERSION_FILE = "version.json"
LOG_FILE = "deploys.jsonl"
_PLAIN_FILE_MODES = {"100644", "100755"}  # git's modes for files; links and submodules aren't


class DeployError(RuntimeError):
    """The deploy or rollback was refused; the live page is unchanged."""


@dataclass(frozen=True)
class DeployResult:
    commit: str  # now live
    previous: str | None  # live before, if anything was
    changed: bool  # False when the commit was already live


def deploy(repo: Path, site: Path, *, now: dt.datetime, rev: str = "HEAD") -> DeployResult:
    """Put ``rev``'s ``web/`` live; the commit that was live becomes ``previous``."""
    commit = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").decode().strip()
    files = _commit_files(repo, commit)
    site.mkdir(parents=True, exist_ok=True)
    site.chmod(0o755)
    with _lock(site):
        if (site / commit).exists():
            _check_copy(site / commit, _sums(files))
        else:
            _write_copy(site, commit, files)
        live = _target(site, CURRENT)
        if live == commit:
            return DeployResult(commit=commit, previous=live, changed=False)
        if live is not None:
            _swap_symlink(site / PREVIOUS, live)
        _swap_symlink(site / CURRENT, commit)
        _log(site, now, "deploy", commit, live)
    return DeployResult(commit=commit, previous=live, changed=True)


def rollback(site: Path, *, now: dt.datetime) -> DeployResult:
    """Swap ``current`` and ``previous``: one switch back, and the same switch forward."""
    if not site.is_dir():
        raise DeployError(f"nothing to roll back to: {site} doesn't exist")
    with _lock(site):
        live, before = _target(site, CURRENT), _target(site, PREVIOUS)
        if before is None:
            raise DeployError(f"nothing to roll back to: {site / PREVIOUS} doesn't exist")
        _check_copy(site / before, _read_sums(site / f"{before}.sha256"))
        _swap_symlink(site / CURRENT, before)  # first: the page is what matters
        if live is not None:
            _swap_symlink(site / PREVIOUS, live)
        _log(site, now, "rollback", before, live)
    return DeployResult(commit=before, previous=live, changed=True)


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, check=True, timeout=60
        ).stdout
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="replace").strip() or f"exit {e.returncode}"
        raise DeployError(f"git {' '.join(args)}: {err}") from e


def _commit_files(repo: Path, commit: str) -> dict[str, bytes]:
    """Each file the site copy holds (path inside the copy → content), from git objects."""
    out = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", "web")
    files: dict[str, bytes] = {}
    for entry in filter(None, out.split(b"\0")):
        meta, path = entry.decode().split("\t", 1)
        mode, _kind, oid = meta.split()
        if mode not in _PLAIN_FILE_MODES:
            raise DeployError(f"{path} in {commit} is not a plain file (git mode {mode})")
        files[path.removeprefix("web/")] = _git(repo, "cat-file", "blob", oid)
    if not files:
        raise DeployError(f"{commit} has no web/ folder")
    files[VERSION_FILE] = (json.dumps({"commit": commit}) + "\n").encode()
    return files


def _sums(files: dict[str, bytes]) -> dict[str, str]:
    return {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}


def _write_copy(site: Path, commit: str, files: dict[str, bytes]) -> None:
    tmp = site / f".tmp-{commit}"
    if tmp.exists():
        log.warning("removing %s, left by an interrupted deploy (never live)", tmp)
        shutil.rmtree(tmp)
    for path, data in files.items():
        target = tmp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    for d in [tmp, *(p for p in tmp.rglob("*") if p.is_dir())]:
        d.chmod(0o755)
    sums = _sums(files)
    _check_copy(tmp, sums)
    listing = site / f".tmp-{commit}.sha256"
    listing.write_text("".join(f"{h}  {p}\n" for p, h in sorted(sums.items())))
    listing.chmod(0o644)
    os.replace(listing, site / f"{commit}.sha256")
    os.replace(tmp, site / commit)


def _read_sums(listing: Path) -> dict[str, str]:
    try:
        lines = listing.read_text().splitlines()
    except FileNotFoundError as e:
        raise DeployError(f"{listing} is missing, so the copy can't be checked") from e
    pairs = [line.split("  ", 1) for line in lines]
    if not pairs or any(len(pair) != 2 for pair in pairs):
        raise DeployError(f"{listing} is not a checksum list, so the copy can't be checked")
    return {p: h for h, p in pairs}


def _check_copy(copy: Path, sums: dict[str, str]) -> None:
    """Refuse a copy whose files differ from ``sums`` in name or content."""
    found = {str(p.relative_to(copy)) for p in copy.rglob("*") if not p.is_dir()}
    bad = sorted(found ^ set(sums))
    bad += sorted(
        p for p in found & set(sums)
        if hashlib.sha256((copy / p).read_bytes()).hexdigest() != sums[p]
    )  # fmt: skip
    if bad:
        raise DeployError(f"{copy} doesn't match its commit: {', '.join(bad)}")


def _swap_symlink(link: Path, target: str) -> None:
    tmp = link.with_name(f".{link.name}.tmp")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target)  # relative: resolved inside the site folder
    os.replace(tmp, link)  # rename(2): `link` always exists, old or new


def _target(site: Path, name: str) -> str | None:
    try:
        return os.readlink(site / name)
    except FileNotFoundError:
        return None


def _log(site: Path, now: dt.datetime, action: str, commit: str, previous: str | None) -> None:
    at = now.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = json.dumps({"at": at, "action": action, "commit": commit, "previous": previous})
    with open(site / LOG_FILE, "a") as f:
        f.write(line + "\n")


@contextmanager
def _lock(site: Path) -> Iterator[None]:
    """One deploy or rollback at a time."""
    with open(site / ".deploy.lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise DeployError(f"another deploy or rollback is running in {site}") from e
        yield
