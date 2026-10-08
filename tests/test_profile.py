"""Interest-profile loading — the file that drives ranking and the score cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from watch.profile import Profile, load_profile

FULL = """
name: Sam
interests:
  - AI agents
  - retrieval
stack:
  - Python
goals:
  - ship something
boost:
  - MCP
mute:
  - crypto
arxiv_keywords:
  - rag
"""


def test_load_profile_reads_every_field(tmp_path: Path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text(FULL, encoding="utf-8")

    profile = load_profile(str(p))

    assert profile.name == "Sam"
    assert profile.interests == ["AI agents", "retrieval"]
    assert profile.stack == ["Python"]
    assert profile.goals == ["ship something"]
    assert profile.boost == ["MCP"]
    assert profile.mute == ["crypto"]
    assert profile.arxiv_keywords == ["rag"]


def test_profile_version_is_content_addressed(tmp_path: Path) -> None:
    """The version hash is what invalidates cached scores, so it must track content."""
    p = tmp_path / "profile.yaml"
    p.write_text(FULL, encoding="utf-8")
    before = load_profile(str(p)).version

    assert load_profile(str(p)).version == before, "an unchanged file keeps its version"

    p.write_text(FULL.replace("AI agents", "AI infrastructure"), encoding="utf-8")
    assert load_profile(str(p)).version != before, "editing interests must re-score"


def test_missing_profile_falls_back_to_neutral_defaults(tmp_path: Path) -> None:
    profile = load_profile(str(tmp_path / "absent.yaml"))

    assert profile == Profile()
    assert profile.interests == []
    assert profile.version == "default"


def test_profile_path_that_is_a_directory_falls_back(tmp_path: Path) -> None:
    """Docker creates an empty *directory* when a bind-mounted file does not exist.

    Without this guard the app would raise IsADirectoryError on every ingest and
    never reach the neutral-default path it was designed to have.
    """
    empty_mount = tmp_path / "profile.yaml"
    empty_mount.mkdir()

    profile = load_profile(str(empty_mount))

    assert profile == Profile()


def test_empty_profile_file_falls_back_to_defaults(tmp_path: Path) -> None:
    """A commented-out or blank file is valid YAML and must not crash."""
    p = tmp_path / "profile.yaml"
    p.write_text("# nothing configured yet\n", encoding="utf-8")

    profile = load_profile(str(p))

    assert profile.name == "there"
    assert profile.interests == []


@pytest.mark.parametrize("bad", ["interests: not-a-list", "interests:\n  - 42"])
def test_odd_values_do_not_crash_the_loader(tmp_path: Path, bad: str) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text(bad + "\n", encoding="utf-8")

    # Coerced to a list of strings; the ranker must never see a raw str.
    assert all(isinstance(i, str) for i in load_profile(str(p)).interests)


def test_save_profile_replaces_docker_placeholder_directory(tmp_path: Path) -> None:
    """A bind-mounted missing file becomes an empty directory under Docker.

    The /topics UI writes the profile through save_profile, so it must be able
    to take over that placeholder rather than failing with IsADirectoryError.
    """
    from dataclasses import asdict

    from watch.profile import save_profile

    placeholder = tmp_path / "profile.yaml"
    placeholder.mkdir()

    saved = save_profile({"name": "Sam", "interests": ["AI agents"]}, str(placeholder))

    assert placeholder.is_file(), "the empty placeholder directory is replaced by a file"
    assert saved.name == "Sam"
    assert saved.interests == ["AI agents"]

    # The written file round-trips, and only known keys are persisted.
    reloaded = load_profile(str(placeholder))
    assert asdict(reloaded)["boost"] == []


def test_save_profile_refuses_to_clobber_a_real_directory(tmp_path: Path) -> None:
    from watch.profile import save_profile

    real_dir = tmp_path / "profile.yaml"
    real_dir.mkdir()
    (real_dir / "keep.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(OSError):
        save_profile({"name": "Sam"}, str(real_dir))

    assert (real_dir / "keep.txt").exists(), "content in a real directory is untouched"
