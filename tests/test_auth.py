"""Tests for the auth module."""

import json
from pathlib import Path

import pytest

import agent.auth as auth


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect all auth storage to a temp directory for every test."""
    monkeypatch.setattr(auth, "CONFIG_DIR",   tmp_path)
    monkeypatch.setattr(auth, "AUTH_FILE",    tmp_path / "auth.json")
    monkeypatch.setattr(auth, "SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr(auth, "PERMS_FILE",   tmp_path / "permissions.json")


def test_no_account_initially():
    assert not auth.has_account()


def test_register_creates_auth_file():
    auth.register("alice", "s3cr3t")
    assert auth.has_account()


def test_verify_correct_password():
    auth.register("alice", "s3cr3t")
    assert auth.verify_credentials("s3cr3t") == "alice"


def test_verify_wrong_password():
    auth.register("alice", "s3cr3t")
    assert auth.verify_credentials("wrong") is None


def test_create_and_read_session():
    auth.register("alice", "s3cr3t")
    auth.create_session("alice")
    assert auth.is_logged_in()
    session = auth.get_active_session()
    assert session["username"] == "alice"


def test_logout_clears_session():
    auth.register("alice", "s3cr3t")
    auth.create_session("alice")
    auth.logout()
    assert not auth.is_logged_in()


def test_approve_and_check_directory(tmp_path):
    target = tmp_path / "myproject"
    target.mkdir()
    assert not auth.is_directory_approved(target)
    auth.approve_directory(target)
    assert auth.is_directory_approved(target)


def test_revoke_directory(tmp_path):
    target = tmp_path / "myproject"
    target.mkdir()
    auth.approve_directory(target)
    auth.revoke_directory(target)
    assert not auth.is_directory_approved(target)


def test_list_approved_directories(tmp_path):
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir(); b.mkdir()
    auth.approve_directory(a)
    auth.approve_directory(b)
    listed = auth.list_approved_directories()
    assert str(a.resolve()) in listed
    assert str(b.resolve()) in listed


def test_get_stored_username():
    auth.register("bob", "pass")
    assert auth.get_stored_username() == "bob"
