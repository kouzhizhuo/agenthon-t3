"""Evaluator cgroup-v2 mapping and optional CPU diagnostics; no quota guesses."""
import ctypes
import hashlib
import os
from pathlib import PurePosixPath
import re

LIMIT = 1048576
MAGIC = 0x63677270


def path_parts(value):
    if not isinstance(value, str) or not value.startswith("/") or "\0" in value:
        raise ValueError("invalid absolute cgroup path")
    parts = value.split("/")[1:]
    if parts == [""]:
        return ()
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("unsafe cgroup path component")
    return tuple(parts)


def decode(value):
    escapes = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
    if re.search(r"\\(?!040|011|012|134)", value):
        raise ValueError("invalid mountinfo escape")
    return re.sub(r"\\(040|011|012|134)", lambda m: escapes[m[1]], value)


def parse(cgroup, mountinfo):
    for value in (cgroup, mountinfo):
        if len(value.encode()) > LIMIT or len(value.splitlines()) > 4096 or "\0" in value:
            raise ValueError("oversized/invalid proc cgroup input")
    unified = []
    for line in cgroup.splitlines():
        fields = line.split(":")
        if len(fields) != 3 or not re.fullmatch(r"0|[1-9][0-9]*", fields[0]):
            raise ValueError("malformed self cgroup")
        if fields[0] == "0":
            if fields[1]:
                raise ValueError("invalid unified cgroup")
            path_parts(fields[2])
            unified.append(fields[2])
    if len(unified) != 1:
        raise ValueError("exact one unified cgroup required")
    mounts = []
    for line in mountinfo.splitlines():
        sides = line.split(" - ")
        if len(sides) != 2:
            raise ValueError("malformed mountinfo separator")
        left, right = sides[0].split(" "), sides[1].split(" ")
        if len(left) < 6 or len(right) != 3 or any(not f for f in left + right):
            raise ValueError("malformed mountinfo fields")
        if not all(re.fullmatch(r"[1-9][0-9]*", f) for f in left[:2]) or not re.fullmatch(r"[0-9]+:[0-9]+", left[2]):
            raise ValueError("malformed mountinfo IDs")
        root, mount = decode(left[3]), decode(left[4])
        decode(right[1])
        path_parts(root); path_parts(mount)
        if right[0] == "cgroup2":
            mounts.append({"mount_id": left[0], "major_minor": left[2], "root": root, "mountpoint": mount})
    return unified[0], mounts


class NativeFS:
    def open(self, path, directory=False):
        parts = path_parts(path)
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for i, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                if i < len(parts)-1 or directory:
                    flags |= os.O_DIRECTORY
                new = os.open(part, flags, dir_fd=fd)
                os.close(fd); fd = new
            return fd
        except BaseException:
            os.close(fd); raise

    def read(self, path, limit=LIMIT):
        # /proc/self is a kernel symlink; resolve only these two fixed trusted
        # proc inputs to the own numeric PID before no-follow traversal.
        if path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
            path = "/proc/" + str(os.getpid()) + path[len("/proc/self"):]
        fd = self.open(path)
        try:
            chunks, size = [], 0
            while True:
                value = os.read(fd, min(65536, limit+1-size))
                if not value: break
                chunks.append(value); size += len(value)
                if size > limit: raise ValueError("cgroup read limit exceeded")
            return b"".join(chunks).decode("utf-8", errors="strict")
        finally:
            os.close(fd)

    def identity(self, path):
        fd = self.open(path, True)
        try:
            stat = os.fstat(fd)
            # struct statfs starts with long f_type on Linux; reserve enough
            # bytes for the full platform structure written by libc.
            buffer = ctypes.create_string_buffer(512)
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.fstatfs(fd, ctypes.byref(buffer)) != 0:
                raise OSError(ctypes.get_errno(), "fstatfs failed")
            if ctypes.c_long.from_buffer(buffer).value != MAGIC:
                raise ValueError("mapped directory is not cgroup2")
            return [stat.st_dev, stat.st_ino, MAGIC]
        finally:
            os.close(fd)


def membership(fs, current, pid):
    lines = fs.read(current.rstrip("/") + "/cgroup.procs", 65536).splitlines()
    if any(not re.fullmatch(r"[1-9][0-9]*", x) for x in lines) or str(pid) not in lines:
        raise ValueError("current cgroup lacks exact process membership")


def snapshot(fs, pid, cgroup, mountinfo):
    """Resolve one bounded proc snapshot, including every visible ancestor."""
    c, mounts = parse(cgroup, mountinfo); cp = path_parts(c)
    candidates, failures = {}, []
    for mount in mounts:
        rp = path_parts(mount["root"])
        namespace = c == "/" and bool(rp)
        if cp[:len(rp)] == rp:
            relative = cp[len(rp):]
        elif namespace:
            relative = ()
        else:
            continue
        current = mount["mountpoint"].rstrip("/") + ("/" + "/".join(relative) if relative else "")
        current = current or "/"
        try:
            identity = list(fs.identity(current)); membership(fs, current, pid)
            key = tuple(identity)
            candidates.setdefault(key, []).append({**mount, "current": current, "identity": identity,
                "ancestry_complete": mount["root"] == "/" and not namespace})
        except Exception as exc:
            failures.append({"mount": mount, "reason": str(exc)})
    if len(candidates) != 1:
        raise ValueError("CGROUP_MAPPING_AMBIGUOUS" if candidates else "CGROUP_MAPPING_UNRESOLVED: " + str(failures))
    # Same-inode bind mounts are equivalent current objects, but pick the
    # lexicographic mountpoint deterministically and never enlarge ancestry.
    selected = sorted(next(iter(candidates.values())), key=lambda x:(x["mountpoint"],x["mount_id"]))[0]
    current, floor = PurePosixPath(selected["current"]), PurePosixPath(selected["mountpoint"])
    ancestors, ancestor_identities = [], []
    while True:
        ancestor_identities.append(list(fs.identity(str(current))))
        ancestors.append(str(current))
        if current == floor: break
        if floor not in current.parents: raise ValueError("mapped current escaped mount")
        current = current.parent
    return {**selected, "ancestors": ancestors, "ancestor_identities": ancestor_identities,
            "pid": pid, "cgroup_raw": cgroup, "mountinfo_raw": mountinfo,
            "cgroup_sha256": hashlib.sha256(cgroup.encode()).hexdigest(),
            "mountinfo_sha256": hashlib.sha256(mountinfo.encode()).hexdigest(), "cgroup_v2": True}


def signature(mapping):
    # Non-cgroup mounts may legitimately change while Docker operates. Compare
    # the adopted cgroup object and its scope, never the entire mount table.
    return {key: mapping[key] for key in ("mount_id", "major_minor", "root", "mountpoint",
            "current", "identity", "ancestors", "ancestor_identities", "pid")}


class MappingIntegrityError(ValueError):
    def __init__(self, reason, observation_inputs):
        super().__init__(reason)
        self.observation_inputs = observation_inputs


def stable_snapshot(fs, pid, expected=None):
    inputs = []
    try:
        readings = []
        for _ in range(2):
            cgroup = fs.read("/proc/self/cgroup")
            mountinfo = fs.read("/proc/self/mountinfo")
            inputs.append({"cgroup_raw": cgroup, "mountinfo_raw": mountinfo,
                           "cgroup_sha256": hashlib.sha256(cgroup.encode()).hexdigest(),
                           "mountinfo_sha256": hashlib.sha256(mountinfo.encode()).hexdigest()})
            readings.append(snapshot(fs, pid, cgroup, mountinfo))
        first, latest = readings
        if first["cgroup_raw"] != latest["cgroup_raw"] or signature(first) != signature(latest):
            raise ValueError("proc cgroup mapping changed during validation")
        if expected is not None and (latest["cgroup_raw"] != expected["cgroup_raw"] or signature(latest) != signature(expected)):
            raise ValueError("controller cgroup mapping changed")
        return {**latest, "validation_inputs": inputs}
    except Exception as exc:
        raise MappingIntegrityError(str(exc), inputs) from exc


def resolve(fs=None, pid=None):
    fs = fs or NativeFS(); pid = os.getpid() if pid is None else pid
    return stable_snapshot(fs, pid)


def cpu_observation(mapping, fs=None):
    fs = fs or NativeFS()
    latest_mapping = stable_snapshot(fs, mapping["pid"], mapping)
    rows, errors, finite, max_count = [], [], False, 0
    for path in mapping["ancestors"]:
        row = {"path": path, "cpu_max": None}
        try:
            text = fs.read(path.rstrip("/") + "/cpu.max", 65536)
            token = text[:-1] if text.endswith("\n") else text
            if not re.fullmatch(r"(?:max|[1-9][0-9]*) [1-9][0-9]*", token):
                raise ValueError("malformed cpu.max")
            row["cpu_max"] = token
            if token.startswith("max "): max_count += 1
            else: finite = True
        except Exception as exc:
            errors.append({"path": path, "field": "cpu.max", "type": type(exc).__name__, "reason": str(exc)})
        for field in ("cgroup.controllers", "cgroup.subtree_control"):
            try:
                row[field] = fs.read(path.rstrip("/") + "/" + field, 65536)
            except Exception as exc:
                row[field] = None
                errors.append({"path": path, "field": field, "type": type(exc).__name__, "reason": str(exc)})
        rows.append(row)
    stat, stat_status = None, "UNKNOWN"
    try:
        stat = fs.read(mapping["current"].rstrip("/") + "/cpu.stat", 65536)
        entries = [line.split() for line in stat.splitlines()]
        if not entries or any(len(x)!=2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",x[0]) or not re.fullmatch(r"0|[1-9][0-9]*",x[1]) for x in entries) or len({x[0] for x in entries}) != len(entries) or "usage_usec" not in {x[0] for x in entries}:
            raise ValueError("malformed cpu.stat")
        stat_status = "KNOWN"
    except Exception as exc:
        stat = None
        errors.append({"path": mapping["current"], "field": "cpu.stat", "type": type(exc).__name__, "reason": str(exc)})
    # These proc files cannot prove no ancestors outside the cgroup namespace.
    # Visible max values are observations, never a global no-quota assertion.
    status = "KNOWN_FINITE" if finite else "UNKNOWN"
    return {"quota_status": status, "host_cpu_quota_imposed": True if finite else None,
            "visible_all_cpu_max_unlimited": max_count == len(rows),
            "hidden_ancestors_not_ruled_out": True,
            "ancestor_cpu_max": rows, "host_cpu_stat": stat, "host_cpu_stat_status": stat_status,
            "optional_errors": errors, "mapping_validation": latest_mapping}
