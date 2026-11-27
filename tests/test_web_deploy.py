"""``astro web deploy`` and its rollback (F1 spec #47 Module 11, ticket #62, D52 item 5).

Tested with a throwaway git repository and a temp site folder: the site is copied
from the commit, never from the working tree, and ``current`` is swapped atomically.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from astroseeing import cli
from astroseeing.forecast.deploy import DeployError, deploy, rollback
from astroseeing.provenance import REPO_ROOT

NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.UTC)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit_page(repo: Path, html: str, extra: dict[str, str] | None = None) -> str:
    """Write ``web/forecast/index.html`` (and any extra files), commit, return the sha."""
    for rel, text in {"web/forecast/index.html": html, **(extra or {})}.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"page {html[:20]}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.invalid")
    git(r, "config", "user.name", "test")
    (r / "README.md").write_text("not part of the site\n")
    return r


@pytest.fixture
def site(tmp_path: Path) -> Path:
    return tmp_path / "staging" / "forecast" / "site"


def test_first_deploy_copies_the_commits_web_folder_and_points_current_at_it(repo, site):
    sha = commit_page(repo, "<p>one</p>", {"web/forecast/js/main.js": "export {};\n"})

    result = deploy(repo, site, now=NOW)

    assert result.commit == sha
    assert result.previous is None
    assert result.changed
    live = site / "current"
    assert live.is_symlink()
    assert os.readlink(live) == sha  # relative, so the site folder can be moved whole
    assert (live / "forecast" / "index.html").read_text() == "<p>one</p>"
    assert (live / "forecast" / "js" / "main.js").read_text() == "export {};\n"
    assert not (live / "README.md").exists()  # only web/ is deployed
    assert json.loads((live / "version.json").read_text()) == {"commit": sha}


def test_a_later_deploy_keeps_the_older_copy_and_names_it_previous(repo, site):
    first = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    second = commit_page(repo, "<p>two</p>")

    result = deploy(repo, site, now=NOW)

    assert (result.commit, result.previous, result.changed) == (second, first, True)
    assert (site / "current" / "forecast" / "index.html").read_text() == "<p>two</p>"
    assert (site / first / "forecast" / "index.html").read_text() == "<p>one</p>"


def test_uncommitted_edits_in_the_checkout_never_reach_the_site(repo, site):
    sha = commit_page(repo, "<p>committed</p>")
    (repo / "web" / "forecast" / "index.html").write_text("<p>edited, not committed</p>")
    (repo / "web" / "forecast" / "untracked.js").write_text("// not in git\n")

    result = deploy(repo, site, now=NOW)

    assert result.commit == sha
    assert (site / "current" / "forecast" / "index.html").read_text() == "<p>committed</p>"
    assert not (site / "current" / "forecast" / "untracked.js").exists()


def test_deploying_the_live_commit_again_changes_nothing(repo, site):
    first = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    second = commit_page(repo, "<p>two</p>")
    deploy(repo, site, now=NOW)

    again = deploy(repo, site, now=NOW)

    assert (again.commit, again.previous, again.changed) == (second, second, False)
    assert rollback(site, now=NOW).commit == first  # the earlier commit is still the one before


def test_rollback_restores_the_previous_commit_and_a_second_rollback_undoes_it(repo, site):
    first = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    second = commit_page(repo, "<p>two</p>")
    deploy(repo, site, now=NOW)

    back = rollback(site, now=NOW)

    assert (back.commit, back.previous) == (first, second)
    assert (site / "current" / "forecast" / "index.html").read_text() == "<p>one</p>"
    assert json.loads((site / "current" / "version.json").read_text()) == {"commit": first}

    forward = rollback(site, now=NOW)  # the same one switch, again

    assert (forward.commit, forward.previous) == (second, first)
    assert json.loads((site / "current" / "version.json").read_text()) == {"commit": second}


def test_rollback_with_nothing_before_is_refused_and_leaves_the_page_alone(repo, site):
    sha = commit_page(repo, "<p>one</p>")
    with pytest.raises(DeployError, match="nothing to roll back to"):
        rollback(site, now=NOW)  # nothing deployed at all
    deploy(repo, site, now=NOW)

    with pytest.raises(DeployError, match="nothing to roll back to"):
        rollback(site, now=NOW)

    assert os.readlink(site / "current") == sha


def test_the_copy_is_world_readable_whatever_the_umask(repo, site):
    commit_page(repo, "<p>one</p>", {"web/forecast/js/main.js": "export {};\n"})
    old = os.umask(0o077)  # nginx runs as another (dynamic) user: it must still read all
    try:
        deploy(repo, site, now=NOW)
    finally:
        os.umask(old)

    live = (site / "current").resolve()
    for p in [site, live, *live.rglob("*")]:
        want = 0o755 if p.is_dir() else 0o644
        assert p.stat().st_mode & 0o777 == want, p


def test_a_commit_with_something_other_than_plain_files_in_web_is_refused(repo, site):
    good = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    os.symlink("/etc/passwd", repo / "web" / "forecast" / "link.txt")
    bad = commit_page(repo, "<p>two</p>")

    with pytest.raises(DeployError, match=r"web/forecast/link\.txt"):
        deploy(repo, site, now=NOW)

    assert os.readlink(site / "current") == good
    assert not (site / bad).exists()
    assert sorted(p.name for p in site.iterdir()) == sorted(
        [good, f"{good}.sha256", "current", "deploys.jsonl", ".deploy.lock"]
    )


def test_an_existing_copy_that_no_longer_matches_its_commit_is_refused(repo, site):
    first = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    commit_page(repo, "<p>two</p>")
    deploy(repo, site, now=NOW)
    (site / first / "forecast" / "index.html").write_text("<p>changed by hand</p>")

    with pytest.raises(DeployError, match=r"forecast/index\.html"):
        deploy(repo, site, rev=first, now=NOW)
    with pytest.raises(DeployError, match=r"forecast/index\.html"):
        rollback(site, now=NOW)

    assert os.readlink(site / "current") != first


def test_current_never_goes_missing_while_deploys_and_rollbacks_swap_it(repo, site):
    commits = [commit_page(repo, f"<p>{i}</p>") for i in range(2)]
    for sha in commits:
        deploy(repo, site, rev=sha, now=NOW)
    seen: set[str] = set()
    misses = 0
    stop = threading.Event()

    def watch() -> None:  # what nginx does on every request: resolve `current`
        nonlocal misses
        while not stop.is_set():
            try:
                seen.add(os.readlink(site / "current"))
            except OSError:
                misses += 1

    watcher = threading.Thread(target=watch)
    watcher.start()
    try:
        for _ in range(100):
            rollback(site, now=NOW)
    finally:
        stop.set()
        watcher.join()

    assert misses == 0
    assert seen == set(commits)  # the watcher really saw the swaps happen


def test_every_deploy_and_rollback_is_logged_with_its_time_and_commits(repo, site):
    first = commit_page(repo, "<p>one</p>")
    deploy(repo, site, now=NOW)
    second = commit_page(repo, "<p>two</p>")
    deploy(repo, site, now=NOW + dt.timedelta(minutes=1))
    deploy(repo, site, now=NOW + dt.timedelta(minutes=2))  # already live: not a change
    rollback(site, now=NOW + dt.timedelta(minutes=3))

    lines = (site / "deploys.jsonl").read_text().splitlines()

    assert [json.loads(line) for line in lines] == [
        {"at": "2026-11-27T12:00:00Z", "action": "deploy", "commit": first, "previous": None},
        {"at": "2026-11-27T12:01:00Z", "action": "deploy", "commit": second, "previous": first},
        {"at": "2026-11-27T12:03:00Z", "action": "rollback", "commit": first, "previous": second},
    ]


def test_astro_web_deploy_puts_this_checkouts_commit_live_under_staging(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    head = git(REPO_ROOT, "rev-parse", "HEAD")
    site = tmp_path / "staging" / "forecast" / "site"

    assert cli.main(["web", "deploy"]) == 0

    assert head in capsys.readouterr().out
    committed = subprocess.run(
        ["git", "show", "HEAD:web/forecast/index.html"], cwd=REPO_ROOT, capture_output=True
    ).stdout
    assert (site / "current" / "forecast" / "index.html").read_bytes() == committed
    assert json.loads((site / "current" / "version.json").read_text()) == {"commit": head}

    assert cli.main(["web", "deploy", "--rollback"]) == 1  # nothing before it

    assert "nothing to roll back to" in capsys.readouterr().err
    assert os.readlink(site / "current") == head
