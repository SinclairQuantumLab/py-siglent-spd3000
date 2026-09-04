from __future__ import annotations

import pytest

import siglent_spd3000._commit as commit_module


def test_runtime_commit_does_not_follow_head_after_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported_commit = commit_module.get_commit()

    def unexpected_git_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("get_commit() queried Git again after package import")

    monkeypatch.setattr(commit_module.subprocess, "run", unexpected_git_lookup)

    assert commit_module.get_commit() == imported_commit
