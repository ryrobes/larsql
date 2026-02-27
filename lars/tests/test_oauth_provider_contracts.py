import json
from pathlib import Path

from lars.agent import _has_valid_chatgpt_auth, _resolve_chatgpt_token_dir
from lars.anthropic_oauth_proxy import REQUIRED_OAUTH_BETA, _merge_beta_header


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_merge_beta_header_adds_required_oauth_flag() -> None:
    merged = _merge_beta_header(None)
    assert merged == REQUIRED_OAUTH_BETA


def test_merge_beta_header_preserves_and_deduplicates() -> None:
    merged = _merge_beta_header(f"foo,{REQUIRED_OAUTH_BETA},bar,foo")
    assert merged.split(",") == ["foo", REQUIRED_OAUTH_BETA, "bar"]


def test_has_valid_chatgpt_auth_rejects_partial_device_marker(tmp_path: Path) -> None:
    auth_dir = tmp_path / "chatgpt"
    _write_json(auth_dir / "auth.json", {"device_code_requested_at": 123.45})
    assert _has_valid_chatgpt_auth(str(auth_dir)) is False


def test_has_valid_chatgpt_auth_accepts_access_token(tmp_path: Path) -> None:
    auth_dir = tmp_path / "chatgpt"
    _write_json(auth_dir / "auth.json", {"access_token": "abc123"})
    assert _has_valid_chatgpt_auth(str(auth_dir)) is True


def test_resolve_chatgpt_token_dir_falls_back_to_litellm_cache(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CHATGPT_TOKEN_DIR", raising=False)

    root_dir = tmp_path / "lars_root"
    lars_auth = root_dir / "auth" / "chatgpt" / "auth.json"
    _write_json(lars_auth, {"device_code_requested_at": 1.0})  # partial/incomplete

    litellm_auth = home / ".config" / "litellm" / "chatgpt" / "auth.json"
    _write_json(litellm_auth, {"access_token": "token"})

    resolved = _resolve_chatgpt_token_dir(str(root_dir))
    assert resolved == str(home / ".config" / "litellm" / "chatgpt")


def test_resolve_chatgpt_token_dir_respects_explicit_env(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "custom_tokens"
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(explicit))
    resolved = _resolve_chatgpt_token_dir(str(tmp_path / "lars_root"))
    assert resolved == str(explicit)
