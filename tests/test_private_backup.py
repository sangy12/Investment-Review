import hashlib
import io
import json
import subprocess
import tarfile

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.restore_private_backup import AAD, MAGIC, restore


def backup(tmp_path, files):
    manifest = {"code_commit": "fixture", "files": {
        name: {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)} for name, body in files.items()}}
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name, body in {**files, "PRIVATE_MANIFEST.json": json.dumps(manifest).encode()}.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    key = AESGCM.generate_key(bit_length=256)
    nonce = b"0" * 12  # Fixed only for synthetic test fixtures with a fresh random key.
    key_path, path = tmp_path / "key", tmp_path / "backup.aesgcm"
    key_path.write_bytes(key)
    path.write_bytes(MAGIC + nonce + AESGCM(key).encrypt(nonce, data.getvalue(), AAD))
    return path, key_path


def checkout(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    (path / ".gitignore").write_text("/.runtime/\n/reports/\n")
    return path


def test_restore_defaults_to_research_only_and_auth_is_an_import_seed(tmp_path):
    path, key = backup(tmp_path, {"reports/report.md": b"personal thesis", ".runtime/auth/chatgpt-auth.json": b"current fixture",
                                  ".runtime/auth/imported-chatgpt-auth.json": b"obsolete fixture"})
    dest = checkout(tmp_path)
    assert restore(path, key, dest)["restored_files"] == 1
    assert not (dest / ".runtime/auth/chatgpt-auth.json").exists()
    assert (dest / "reports/report.md").stat().st_mode & 0o777 == 0o600
    restore(path, key, dest, with_auth=True, overwrite=True)
    assert (dest / ".runtime/auth/imported-chatgpt-auth.json").read_bytes() == b"current fixture"
    assert not (dest / ".runtime/auth/chatgpt-auth.json").exists()
    with pytest.raises(ValueError):
        restore(path, key, dest)


def test_wrong_key_tampering_and_traversal_fail_before_writes(tmp_path):
    path, key = backup(tmp_path, {"reports/report.md": b"fixture"})
    dest = checkout(tmp_path)
    wrong = tmp_path / "wrong"
    wrong.write_bytes(AESGCM.generate_key(bit_length=256))
    with pytest.raises(InvalidTag):
        restore(path, wrong, dest)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    with pytest.raises(InvalidTag):
        restore(path, key, dest)
    path, key = backup(tmp_path, {"reports/../../escaped": b"fixture"})
    with pytest.raises(ValueError):
        restore(path, key, dest)
    assert not (dest / "reports").exists()
    assert not (tmp_path / "escaped").exists()
