"""Restore an authenticated encrypted research backup; credentials are opt-in seeds."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"IRPRIVATE1\n"
AAD = b"Investment-Review private backup v1"


def read_backup(archive, key_file):
    raw = Path(archive).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError("unsupported_backup_format")
    payload = AESGCM(Path(key_file).read_bytes()).decrypt(
        raw[len(MAGIC):len(MAGIC) + 12], raw[len(MAGIC) + 12:], AAD)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        manifest = json.load(tar.extractfile("PRIVATE_MANIFEST.json"))
        files = {}
        for member in tar.getmembers():
            if member.name == "PRIVATE_MANIFEST.json":
                continue
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or len(name.parts) < 2 or name.parts[0] not in {".runtime", "reports"}
                    or member.name in files):
                raise ValueError("unsafe_backup_entry")
            content = tar.extractfile(member).read()
            record = manifest["files"].get(member.name)
            if not record or hashlib.sha256(content).hexdigest() != record["sha256"] or len(content) != record["size"]:
                raise ValueError("backup_integrity_mismatch")
            files[member.name] = content
        if set(files) != set(manifest["files"]):
            raise ValueError("backup_manifest_mismatch")
    return manifest, files


def restore(archive, key_file, destination, *, with_auth=False, overwrite=False, verify_only=False):
    manifest, files = read_backup(archive, key_file)
    if verify_only:
        return {"verified": True, "file_count": len(files), "code_commit": manifest["code_commit"]}
    dest = Path(destination).resolve()
    if not (dest / ".git").exists():
        raise ValueError("restore_into_a_git_checkout")
    for sample in (".runtime/backup-ignore-check", "reports/backup-ignore-check"):
        if subprocess.run(["git", "check-ignore", "-q", sample], cwd=dest).returncode:
            raise ValueError("private_paths_not_git_ignored")
    selected = {}
    for name, content in files.items():
        if name.startswith(".runtime/auth/"):
            if not with_auth:
                continue
            # Do not revive another host's active OAuth identity. The official
            # bootstrap import will generate/retain this host's stable ID.
            if name == ".runtime/auth/chatgpt-auth.json":
                name = ".runtime/auth/imported-chatgpt-auth.json"
            elif name == ".runtime/auth/imported-chatgpt-auth.json" and ".runtime/auth/chatgpt-auth.json" in files:
                continue  # The active rotated credential wins over an older import seed.
        target = dest / name
        if not target.resolve().is_relative_to(dest) or target.is_symlink():
            raise ValueError("restore_path_escape")
        if target.exists() and not overwrite:
            raise ValueError("restore_target_exists_use_overwrite_explicitly")
        selected[target] = content
    os.umask(0o077)
    for target, content in selected.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        for folder in [target.parent, *target.parent.parents]:
            if folder == dest:
                break
            folder.chmod(0o700)
        target.write_bytes(content)
        target.chmod(0o600)
    return {"restored_files": len(selected), "auth_seed_included": with_auth,
            "code_commit": manifest["code_commit"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--key-file", required=True, help="Local protected key file; never paste its contents into chat")
    parser.add_argument("--destination", default=".")
    parser.add_argument("--with-auth", action="store_true", help="Restore protected credential seeds, not an active OAuth session")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(restore(args.archive, args.key_file, args.destination, with_auth=args.with_auth,
                                 overwrite=args.overwrite, verify_only=args.verify_only)))
    except Exception as exc:
        # Crypto/parser exceptions and private paths must not reveal contents.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
