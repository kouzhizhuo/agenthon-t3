"""Bounded mode-only preparation of the two frozen T3 source mounts."""
import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath


ROOTS = ["t3/research1008v5b/baseline", "t3/research1008v5b/runtime"]
ROSTER_SHA256 = "afff62807b44cfe7909da1a16497128ec494b035c90616dd0f0e6f22ce9283fa"


class PreparationError(ValueError):
    pass


def fail(message):
    raise PreparationError(message)


def path_parts(path):
    if type(path) is not str or not path or "\\" in path or "\x00" in path:
        fail("invalid path")
    parts = PurePosixPath(path)
    if parts.is_absolute() or str(parts) != path or any(p in (".", "..") for p in parts.parts):
        fail("unsafe or noncanonical path")
    return parts.parts


def validate_roster(roster):
    fields = {"schema_version", "roots", "directory_mode", "file_mode_rule", "files", "source_manifest_sha256", "bundle_sha256"}
    if type(roster) is not dict or set(roster) != fields or type(roster["schema_version"]) is not int or roster["schema_version"] != 1:
        fail("exact roster schema required")
    if roster["roots"] != ROOTS or roster["directory_mode"] != 0o755 or roster["file_mode_rule"] != "0755_if_archive_execute_else0644":
        fail("exact two-root mode policy required")
    for key in ("source_manifest_sha256", "bundle_sha256"):
        if type(roster[key]) is not str or re.fullmatch("[0-9a-f]{64}", roster[key]) is None:
            fail("invalid pinned digest")
    if type(roster["files"]) is not list or not roster["files"]:
        fail("nonempty file roster required")
    files, directories = {}, set(ROOTS)
    for entry in roster["files"]:
        if type(entry) is not dict or set(entry) != {"path", "sha256", "bytes", "archive_mode"}:
            fail("exact file metadata required")
        path = entry["path"]
        path_parts(path)
        matches = [r for r in ROOTS if path.startswith(r + "/")]
        if len(matches) != 1 or path in files:
            fail("out-of-scope or duplicate file")
        if type(entry["sha256"]) is not str or re.fullmatch("[0-9a-f]{64}", entry["sha256"]) is None:
            fail("invalid file digest")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0 or type(entry["archive_mode"]) is not int or not 0 <= entry["archive_mode"] <= 0o7777:
            fail("invalid frozen size or mode")
        files[path] = entry
        parent = str(PurePosixPath(path).parent)
        while parent != matches[0]:
            directories.add(parent)
            parent = str(PurePosixPath(parent).parent)
    if any(not any(p.startswith(r + "/") for p in files) for r in ROOTS):
        fail("both source mounts required")
    if set(files) & directories:
        fail("file-directory collision")
    return files, directories


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def metadata(info):
    return {"mode": format(stat.S_IMODE(info.st_mode), "04o"), "uid": info.st_uid,
            "gid": info.st_gid, "device": info.st_dev, "inode": info.st_ino,
            "links": info.st_nlink, "bytes": info.st_size}


def digest_fd(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        data = os.read(fd, 1024 * 1024)
        if not data:
            break
        digest.update(data)
    return digest.hexdigest()


def normalize(workspace, roster):
    """Validate every node before chmod; operate on retained no-follow descriptors."""
    opened, records, mutations = [], {}, 0
    try:
        files, directories = validate_roster(roster)
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            fail("no-follow directory descriptors required")
        work = os.open(os.fspath(workspace), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(work)
        work_info = os.fstat(work)
        if not stat.S_ISDIR(work_info.st_mode):
            fail("workspace must be a real directory")
        dirs = {"": work}
        required = set(directories)
        for root in ROOTS:
            parent = str(PurePosixPath(root).parent)
            while parent != ".":
                required.add(parent)
                parent = str(PurePosixPath(parent).parent)
        for path in sorted(required, key=lambda p: (len(path_parts(p)), p)):
            parent, name = str(PurePosixPath(path).parent), PurePosixPath(path).name
            parent = "" if parent == "." else parent
            prior = os.stat(name, dir_fd=dirs[parent], follow_symlinks=False)
            if not stat.S_ISDIR(prior.st_mode):
                fail("non-directory or symlink in source path: " + path)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirs[parent])
            opened.append(fd)
            current = os.fstat(fd)
            if identity(current) != identity(prior):
                fail("directory changed during admission: " + path)
            dirs[path] = fd
            records[path] = {"fd": fd, "parent": dirs[parent], "name": name, "identity": identity(current), "before": metadata(current), "selected": path in directories}
        for path in sorted(directories):
            expected = {PurePosixPath(p).name for p in set(files) | directories if str(PurePosixPath(p).parent) == path}
            if set(os.listdir(dirs[path])) != expected:
                fail("unexpected or missing source node: " + path)
        for path, entry in sorted(files.items()):
            parent, name = str(PurePosixPath(path).parent), PurePosixPath(path).name
            prior = os.stat(name, dir_fd=dirs[parent], follow_symlinks=False)
            if not stat.S_ISREG(prior.st_mode) or prior.st_nlink != 1:
                fail("nonregular, symlink or hardlinked source: " + path)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirs[parent])
            opened.append(fd)
            current = os.fstat(fd)
            if identity(current) != identity(prior) or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_size != entry["bytes"]:
                fail("file changed or wrong size: " + path)
            if digest_fd(fd) != entry["sha256"]:
                fail("source content hash mismatch: " + path)
            records[path] = {"fd": fd, "parent": dirs[parent], "name": name, "identity": identity(current), "before": metadata(current), "selected": True, "sha256": entry["sha256"]}

        def revalidate():
            for path, record in records.items():
                info = os.stat(record["name"], dir_fd=record["parent"], follow_symlinks=False)
                held = os.fstat(record["fd"])
                if identity(info) != record["identity"] or identity(held) != record["identity"]:
                    fail("admitted source path identity changed: " + path)
                if path in files and (info.st_nlink != 1 or held.st_nlink != 1 or held.st_size != files[path]["bytes"] or digest_fd(record["fd"]) != files[path]["sha256"]):
                    fail("admitted source file changed: " + path)
            for path in directories:
                expected = {PurePosixPath(p).name for p in set(files) | directories if str(PurePosixPath(p).parent) == path}
                if set(os.listdir(dirs[path])) != expected:
                    fail("admitted source roster changed: " + path)

        revalidate()
        for path in sorted(directories):
            os.fchmod(records[path]["fd"], 0o755)
            mutations += 1
        for path, entry in sorted(files.items()):
            os.fchmod(records[path]["fd"], 0o755 if entry["archive_mode"] & 0o111 else 0o644)
            mutations += 1
        revalidate()
        receipt = []
        for path, record in sorted(records.items()):
            after = metadata(os.fstat(record["fd"]))
            target = 0o755 if path in directories else (0o755 if files[path]["archive_mode"] & 0o111 else 0o644) if path in files else None
            if target is not None and after["mode"] != format(target, "04o"):
                fail("mode normalization did not take effect: " + path)
            if after["uid"] != record["before"]["uid"] or after["gid"] != record["before"]["gid"]:
                fail("ownership changed: " + path)
            if not record["selected"] and after["mode"] != record["before"]["mode"]:
                fail("ancestor mode changed outside source mounts: " + path)
            receipt.append({"path": path, "type": "regular_file" if path in files else "directory", "selected_for_mode_policy": record["selected"], "before": record["before"], "after": after, "sha256_before": record.get("sha256"), "sha256_after": record.get("sha256")})
        return {"status": "PASS", "roots": ROOTS, "files": len(files), "selected_directories": len(directories), "mode_operations": mutations, "source_contents_unchanged": True, "source_roster_unchanged": True, "ownership_unchanged": True, "records": receipt, "actual_different_uid_or_Docker_access_verified": False}
    except (OSError, PreparationError) as exc:
        raise PreparationError("mode preparation failed after %d mode operations: %s" % (mutations, exc)) from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def reserve_receipt(workspace, receipt_path):
    """Reserve the fixed evidence receipt before any source-mode operation."""
    expected = Path(os.path.abspath(workspace)) / "evidence/source_mode_preparation.json"
    if Path(os.path.abspath(receipt_path)) != expected:
        fail("receipt must be the fixed evidence path outside source mounts")
    work = os.open(os.fspath(workspace), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        evidence = os.open("evidence", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work)
        try:
            return os.open("source_mode_preparation.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=evidence)
        finally:
            os.close(evidence)
    finally:
        os.close(work)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    with open(args.roster, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != ROSTER_SHA256:
        fail("exact frozen production mode roster required")
    roster = json.loads(raw)
    fd = reserve_receipt(args.workspace, args.receipt)
    with os.fdopen(fd, "w") as handle:
        receipt = {"status": "FAIL", "source_mode_roster_sha256": ROSTER_SHA256}
        try:
            receipt.update(normalize(args.workspace, roster))
        except PreparationError as exc:
            receipt["error"] = str(exc)
            raise
        finally:
            handle.write(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
