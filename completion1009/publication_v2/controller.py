#!/usr/bin/env python3
"""Archive exact tested images; publish independently with bounded credentials.

No competition upload is implemented. The CLI requires --execute for archive or
registry mutations; network-free plan is the default. Registry anonymous proof
streams every remote blob and never removes any Docker daemon image.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REGISTRY = "ghcr.io"
REPOSITORY = "kouzhizhuo/agenthon-t3"
HEX = re.compile(r"[0-9a-f]{64}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MANIFEST_TYPES = "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json"
CRITICAL = ("SELECTED_IMAGE.json", "full/SUMMARY.json", "full/RAW_RESULTS.json",
            "pilot/SUMMARY.json", "pilot/RAW_RESULTS.json")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_member(name):
    require(not name.startswith("/") and "\\" not in name
            and all(piece not in ("", ".", "..") for piece in name.split("/")), "unsafe archive member")
    return str(PurePosixPath(name))


def check_archive(path, image_id):
    """Read only Docker-save metadata; no archive extraction or path following."""
    require(DIGEST.fullmatch(image_id), "immutable image ID required")
    with tarfile.open(path, "r:") as archive:
        members = {}
        for member in archive:
            name = member.name.rstrip("/") if member.isdir() else member.name
            name = safe_member(name)
            require(name not in members and (member.isfile() or member.isdir()), "duplicate/nonregular archive member")
            members[name] = member
        require("manifest.json" in members and members["manifest.json"].isfile(), "Docker-save manifest missing")
        require(members["manifest.json"].size < 1 << 20, "oversized archive manifest")
        manifest = json.load(archive.extractfile(members["manifest.json"]))
        require(isinstance(manifest, list) and len(manifest) == 1, "exactly one saved image required")
        config_name = safe_member(manifest[0]["Config"])
        config_member = members.get(config_name)
        require(config_member and config_member.isfile() and config_member.size < 4 << 20, "saved config absent/oversized")
        config = archive.extractfile(config_member).read()
        require("sha256:" + hashlib.sha256(config).hexdigest() == image_id, "saved config digest differs from tested ID")
        parsed = json.loads(config)
        require(parsed.get("os") == "linux" and parsed.get("architecture") == "amd64", "saved Linux/amd64 config required")
        layers = manifest[0].get("Layers")
        require(isinstance(layers, list) and layers, "saved layers missing")
        require(all(safe_member(name) in members and members[name].isfile() for name in layers), "saved layer absent/nonregular")
        require(len(set(layers)) == len(layers), "duplicate saved layer")
        diff_ids = parsed.get("rootfs", {}).get("diff_ids")
        require(parsed.get("rootfs", {}).get("type") == "layers" and isinstance(diff_ids, list)
                and len(diff_ids) == len(layers) and all(DIGEST.fullmatch(value) for value in diff_ids),
                "saved config uncompressed layer digests missing")
        for layer, diff_id in zip(layers, diff_ids):
            hashed = hashlib.sha256()
            with archive.extractfile(members[layer]) as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    hashed.update(chunk)
            require("sha256:" + hashed.hexdigest() == diff_id, "saved uncompressed layer differs from config diff_id")
    return {"image_id": image_id, "archive_sha256": sha256(path), "archive_bytes": Path(path).stat().st_size,
            "layer_members": layers, "config_member": config_name, "single_image": True}


def inspect(docker, reference, env=None):
    result = subprocess.run([docker, "image", "inspect", reference], capture_output=True, check=True, timeout=30, env=env)
    values = json.loads(result.stdout)
    require(isinstance(values, list) and len(values) == 1, "one local image required")
    image = values[0]
    require(image.get("Id") == reference and image.get("Os") == "linux" and image.get("Architecture") == "amd64",
            "local exact Linux/amd64 image ID differs")
    require(not image.get("Config", {}).get("Volumes"), "Docker VOLUME prohibited")
    return image


def selection(evidence, completion):
    spec = importlib.util.spec_from_file_location("t3_archive_selector", completion / "select_linux_image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    derived = module.select(evidence / "full", evidence / "pilot")
    actual = read_json(evidence / "SELECTED_IMAGE.json")
    require(all(actual.get(key) == value for key, value in derived.items()), "selection receipt differs from complete evidence")
    return actual


def final_binding(final_dir, selected_id):
    result = read_json(final_dir / "FINAL_IMAGE_RESULT.json")
    freeze = read_json(final_dir / "FROZEN_IMAGE_RECEIPT.json")
    require(result.get("schema") == "t3-final-doc-layer-result-v1" and result.get("status") == "prepared_and_verified"
            and result.get("rankable") is False and result.get("strict_smoke_passed") is True
            and result.get("complete_filesystem_and_config_freeze_passed") is True, "final docs image is not verified")
    require(freeze.get("passed") is True and freeze.get("selected_image_id") == selected_id
            and freeze.get("final_image_id") == result.get("final_image_id")
            and DIGEST.fullmatch(result.get("final_image_id", "")), "final image not derived from selected ID")
    filesystem, configuration = freeze.get("filesystem", {}), freeze.get("configuration", {})
    require(filesystem.get("passed") is True and configuration.get("passed") is True
            and configuration.get("complete_config_equal") is True and configuration.get("no_volumes") is True,
            "final actual filesystem/config comparison not proven")
    require(filesystem.get("excluded_change_paths") == ["opt/t3-production/LICENSE", "opt/t3-production/LICENSING.md"],
            "final freeze excludes paths other than two license documents")
    for key in ("strict_smoke_limits", "strict_paired_limits"):
        limits = result.get(key, {})
        require(limits.get("passed") is True and limits.get("nproc_soft_hard") == 256
                and limits.get("fsize_soft_hard_bytes") == 268435456, "strict final nproc/fsize not proven")
    return result["final_image_id"]


def export_bundle(args):
    evidence, completion, bundle = args.evidence.resolve(), args.completion.resolve(), args.bundle.resolve()
    selected = selection(evidence, completion)
    image_id = selected["selected_image_id"]
    files = list(CRITICAL)
    final_info = None
    if args.final_dir:
        final_dir = args.final_dir.resolve()
        image_id = final_binding(final_dir, image_id)
        final_info = {"directory": final_dir, "files": ["FINAL_IMAGE_RESULT.json", "FROZEN_IMAGE_RECEIPT.json",
            "strict-smoke/SUMMARY.json", "strict-smoke/RAW_RESULTS.json"]}
    plan = {"action": "archive" if args.execute else "plan_only", "selected_image_id": selected["selected_image_id"],
            "archive_image_id": image_id, "final_docs_layer": bool(final_info), "competition_upload_performed": False}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    require(not bundle.exists(), "bundle destination already exists")
    bundle.mkdir(parents=True)
    image = inspect(args.docker, image_id)
    receipt_files = {}
    for name in files:
        src, dst = evidence / name, bundle / "receipts" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        receipt_files["receipts/" + name] = sha256(dst)
    if final_info:
        for name in final_info["files"]:
            dst = bundle / "receipts/final" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(final_info["directory"] / name, dst)
            receipt_files["receipts/final/" + name] = sha256(dst)
    archive = bundle / "selected-image.tar"
    subprocess.run([args.docker, "image", "save", "--output", str(archive), image_id], check=True, timeout=1200)
    saved = check_archive(archive, image_id)
    inspect(args.docker, image_id)
    # Store launch admission fields, never complete Config.Env or credentials.
    info = {"schema": "t3-verified-publication-bundle-v2", "rankable": False, **plan, **saved,
        "archive_name": archive.name, "receipt_sha256": receipt_files,
        "provenance": {"repository": os.environ.get("GITHUB_REPOSITORY"), "run_id": os.environ.get("GITHUB_RUN_ID"),
                       "workflow_commit": os.environ.get("GITHUB_SHA"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")},
        "admission": {"linux_amd64": True, "no_volumes": True, "user": image["Config"].get("User"),
                      "interface_version": image["Config"].get("Labels", {}).get("qfbench2.interface_version")},
        "verification_image_id": selected["selected_image_id"], "publication_performed": False}
    write_json(bundle / "BUNDLE.json", info)
    print(json.dumps({"bundle_manifest_sha256": sha256(bundle / "BUNDLE.json"), "archive_image_id": image_id,
                      "archive_sha256": saved["archive_sha256"]}, indent=2))


def validate_bundle(bundle, expected_manifest):
    require(HEX.fullmatch(expected_manifest), "expected bundle SHA256 required")
    require(sha256(bundle / "BUNDLE.json") == expected_manifest, "bundle manifest SHA256 differs")
    data = read_json(bundle / "BUNDLE.json")
    require(data.get("schema") == "t3-verified-publication-bundle-v2" and data.get("rankable") is False,
            "unknown publication bundle")
    require(data.get("provenance", {}).get("repository") == "kouzhizhuo/agenthon-t3", "bundle repository differs")
    require(data.get("archive_name") == "selected-image.tar", "unexpected archive name")
    for name, expected in data.get("receipt_sha256", {}).items():
        require(name.startswith("receipts/") and HEX.fullmatch(expected), "invalid receipt hash path")
        require(sha256(bundle / safe_member(name)) == expected, "bound verification receipt differs")
    require(set("receipts/" + name for name in CRITICAL) <= set(data.get("receipt_sha256", {})), "verification receipt set incomplete")
    admission = data.get("admission", {})
    require(admission.get("linux_amd64") is True and admission.get("no_volumes") is True
            and admission.get("user") == "65534:65534" and admission.get("interface_version") == "2.0", "bundle image admission differs")
    require(data.get("publication_performed") is False and data.get("competition_upload_performed") is False,
            "bundle must precede publication and competition upload")
    selected_id = data.get("selected_image_id")
    require(DIGEST.fullmatch(selected_id or "") and data.get("verification_image_id") == selected_id
            and data.get("archive_image_id") == data.get("image_id"), "bundle verification/archive image relationship differs")
    selected_receipt = read_json(bundle / "receipts/SELECTED_IMAGE.json")
    require(selected_receipt.get("selected_image_id") == selected_id and selected_receipt.get("status") == "selected",
            "bound selection receipt image differs")
    require(type(data.get("final_docs_layer")) is bool, "explicit final-doc-layer marker required")
    if data["final_docs_layer"]:
        names = {"receipts/final/FINAL_IMAGE_RESULT.json", "receipts/final/FROZEN_IMAGE_RECEIPT.json",
                 "receipts/final/strict-smoke/SUMMARY.json", "receipts/final/strict-smoke/RAW_RESULTS.json"}
        require(names <= set(data["receipt_sha256"]), "final image receipt set incomplete")
        require(final_binding(bundle / "receipts/final", selected_id) == data["image_id"], "final archive ID differs from final receipt")
    else:
        require(data["image_id"] == selected_id, "source archive image differs from tested selected ID")
    saved = check_archive(bundle / "selected-image.tar", data["image_id"])
    require(saved["archive_sha256"] == data.get("archive_sha256") and saved["archive_bytes"] == data.get("archive_bytes"),
            "saved archive bytes differ")
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Registry:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, url, headers=None, data=None):
        request = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
        try:
            return self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            return error


def read_response(response, limit=4 << 20):
    data = response.read(limit + 1)
    require(len(data) <= limit, "registry response exceeds bound")
    return data


def scoped_token(client, credential=None):
    query = urllib.parse.urlencode({"service": REGISTRY, "scope": "repository:" + REPOSITORY + (":pull,push" if credential else ":pull")})
    headers = {"Accept": "application/json"}
    if credential:
        actor, token = credential
        headers["Authorization"] = "Basic " + base64.b64encode((actor + ":" + token).encode()).decode()
    with client.request("GET", "https://" + REGISTRY + "/token?" + query, headers) as response:
        require(response.status == 200, "registry scope token request rejected")
        value = json.loads(read_response(response))
    token = value.get("token") or value.get("access_token")
    require(isinstance(token, str) and token and "\n" not in token, "scope token missing")
    return token


def upload_location(value):
    require(isinstance(value, str) and value, "registry upload Location missing")
    url = urllib.parse.urljoin("https://" + REGISTRY, value)
    parsed = urllib.parse.urlsplit(url)
    prefix = "/v2/" + REPOSITORY + "/blobs/uploads/"
    session = parsed.path[len(prefix):] if parsed.path.startswith(prefix) else ""
    require(parsed.scheme == "https" and parsed.hostname == REGISTRY and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.fragment
            and re.fullmatch(r"[A-Za-z0-9._-]+", session) and session not in (".", ".."),
            "upload Location crosses owned registry/repository")
    return url


def scope_preflight(client, credential, output=None):
    nonce = uuid.uuid4().hex
    location = None
    receipt = {"nonce": nonce, "repository": REPOSITORY, "manifest_or_tag_created": False,
               "upload_completed": False, "token_recorded": False, "passed": False}
    try:
        token = scoped_token(client, credential)
        auth = {"Authorization": "Bearer " + token}
        # Empty POST creates one uncommitted upload only, with no digest query.
        with client.request("POST", "https://" + REGISTRY + "/v2/" + REPOSITORY + "/blobs/uploads/",
                            {**auth, "Content-Length": "0", "X-T3-Probe-Nonce": nonce}, b"") as response:
            receipt["post_status"] = response.status
            require(response.status == 202, "registry denied empty upload scope probe (HTTP %s)" % response.status)
            location = upload_location(response.headers.get("Location"))
            receipt["location_sha256"] = hashlib.sha256(location.encode()).hexdigest()
    except Exception as error:
        receipt["failure_type"] = type(error).__name__
        raise
    finally:
        if location:
            try:
                with client.request("DELETE", location, auth) as response:
                    receipt["delete_status"] = response.status
                    require(response.status == 204, "exact upload-session cleanup failed (HTTP %s)" % response.status)
                receipt["upload_session_removed"] = True
                receipt["passed"] = True
            finally:
                if output:
                    write_json(output, receipt)
        elif output:
            write_json(output, receipt)
    receipt["passed"] = True
    return receipt


def blob_descriptor(value):
    require(isinstance(value, dict) and DIGEST.fullmatch(value.get("digest", ""))
            and isinstance(value.get("size"), int) and not isinstance(value["size"], bool) and value["size"] > 0,
            "manifest blob descriptor malformed")
    require(not value.get("urls"), "foreign blob URLs prohibited for anonymous proof")
    return value


def anonymous_proof(client, digest):
    require(DIGEST.fullmatch(digest), "published immutable digest required")
    token = scoped_token(client)
    headers = {"Authorization": "Bearer " + token, "Accept": MANIFEST_TYPES}
    url = "https://" + REGISTRY + "/v2/" + REPOSITORY + "/manifests/" + digest
    with client.request("GET", url, headers) as response:
        require(response.status == 200, "anonymous manifest fetch failed")
        raw = read_response(response)
        require("sha256:" + hashlib.sha256(raw).hexdigest() == digest, "remote manifest bytes do not match immutable digest")
        returned_digest = response.headers.get("Docker-Content-Digest")
        require(not returned_digest or returned_digest == digest, "registry content digest differs")
        manifest = json.loads(raw)
    require(manifest.get("schemaVersion") == 2 and manifest.get("mediaType") in MANIFEST_TYPES.split(",")
            and isinstance(manifest.get("layers"), list) and manifest["layers"], "single-platform schema2 manifest required")
    blobs, config_data = [], None
    for descriptor in [blob_descriptor(manifest.get("config")), *[blob_descriptor(v) for v in manifest["layers"]]]:
        hash_value = hashlib.sha256(); total = 0; config_chunks = []
        with client.request("GET", "https://" + REGISTRY + "/v2/" + REPOSITORY + "/blobs/" + descriptor["digest"], headers) as response:
            # GHCR blob CDN redirects are handled without Authorization below.
            if response.status in (301, 302, 307, 308):
                location = response.headers.get("Location")
                parsed = urllib.parse.urlsplit(location or "")
                require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password,
                        "invalid registry blob redirect")
                response.close()
                stream = client.request("GET", location, {"Accept": "application/octet-stream"})
            else:
                stream = response
            with stream:
                require(stream.status == 200, "anonymous blob fetch failed")
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    total += len(chunk)
                    require(total <= descriptor["size"], "remote blob exceeds declared size")
                    hash_value.update(chunk)
                    if descriptor is manifest["config"]:
                        require(total <= 4 << 20, "image config exceeds bound")
                        config_chunks.append(chunk)
        require(total == descriptor["size"] and "sha256:" + hash_value.hexdigest() == descriptor["digest"],
                "remote blob size/digest differs")
        if descriptor is manifest["config"]:
            config_data = json.loads(b"".join(config_chunks))
        blobs.append({"digest": descriptor["digest"], "size": total, "anonymous_fetch_verified": True})
    require(config_data and config_data.get("os") == "linux" and config_data.get("architecture") == "amd64"
            and not config_data.get("config", {}).get("Volumes"), "remote Linux/amd64 no-VOLUME admission failed")
    return {"passed": True, "anonymous_credentials_only": True, "docker_daemon_cache_used": False,
            "manifest_digest": digest, "config_image_id": manifest["config"]["digest"], "blobs": blobs,
            "all_remote_bytes_hashed": True, "image_removal_performed": False}


def publish(args):
    bundle = args.bundle.resolve()
    data = validate_bundle(bundle, args.expected_bundle_sha256)
    plan = {"action": "publish" if args.execute else "plan_only", "archive_image_id": data["image_id"],
            "repository": REPOSITORY, "scope_probe": "empty POST then DELETE exact returned upload Location",
            "anonymous_proof": "stream manifest/config/all layers and verify size+sha256", "competition_upload_performed": False}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    actor, token = os.environ.get("GITHUB_ACTOR"), os.environ.get("T3_REGISTRY_TOKEN")
    require(actor and token, "workflow actor and ephemeral token required")
    client = Registry()
    private = Path(tempfile.mkdtemp(prefix="t3-publish-config-", dir=os.environ.get("RUNNER_TEMP")))
    private.chmod(0o700)
    env = os.environ.copy(); env["DOCKER_CONFIG"] = str(private)
    # Exclude registry token from Docker child environments as well as evidence.
    env.pop("T3_REGISTRY_TOKEN", None)
    result = {**plan, "status": "failed", "publication_performed": False}
    cleanup = {"logout_attempted": False, "private_config_removed": False}
    try:
        result["last_stage"] = "scope_preflight"
        scope_preflight(client, (actor, token), out / "SCOPE_PROBE.json")
        result["last_stage"] = "load_archive"
        with (out / "load.log").open("xb") as stream:
            subprocess.run([args.docker, "image", "load", "--input", str(bundle / "selected-image.tar")], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=1200, env=env)
        inspect(args.docker, data["image_id"], env)
        result["last_stage"] = "login"
        login = subprocess.run([args.docker, "login", REGISTRY, "-u", actor, "--password-stdin"],
                               input=token.encode(), capture_output=True, timeout=60, env=env)
        require(login.returncode == 0, "registry login failed; credentials omitted")
        tag = "ghcr.io/" + REPOSITORY + ":t3-verified-" + os.environ.get("GITHUB_RUN_ID", "local") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        result["last_stage"] = "push"
        subprocess.run([args.docker, "tag", data["image_id"], tag], check=True, timeout=30, env=env)
        with (out / "push.log").open("xb") as stream:
            subprocess.run([args.docker, "push", tag], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1800, env=env)
        pushed = json.loads(subprocess.run([args.docker, "image", "inspect", tag], capture_output=True, check=True,
                                          timeout=30, env=env).stdout)[0]
        result["publication_performed"] = True
        require(pushed.get("Id") == data["image_id"], "pushed local image ID differs")
        refs = [ref for ref in pushed.get("RepoDigests", []) if ref.startswith("ghcr.io/" + REPOSITORY + "@sha256:")]
        require(len(refs) == 1, "one immutable published repository digest required")
        digest = refs[0].rsplit("@", 1)[1]
        result["last_stage"] = "anonymous_remote_bytes"
        proof = anonymous_proof(client, digest)
        require(proof["config_image_id"] == data["image_id"], "remote anonymous config not bound to tested image")
        write_json(out / "ANONYMOUS_PROOF.json", proof)
        (out / "PUBLISHED_REFERENCE.txt").write_text(refs[0] + "\n")
        result.update(status="published_and_anonymously_verified", publication_performed=True,
                      published_reference=refs[0], bundle_manifest_sha256=args.expected_bundle_sha256,
                      config_image_id=data["image_id"], final_docs_layer=data["final_docs_layer"])
    except Exception as error:
        # Exception text from URLs may contain signed CDN queries or auth data.
        result["failure_type"] = type(error).__name__
        result["failure_stage"] = "see retained process/receipt status"
        raise
    finally:
        cleanup["logout_attempted"] = True
        try:
            logout = subprocess.run([args.docker, "logout", REGISTRY], capture_output=True, timeout=30, env=env)
            cleanup["logout_returncode"] = logout.returncode
        finally:
            shutil.rmtree(private)
            cleanup["private_config_removed"] = not private.exists()
            write_json(out / "CREDENTIAL_CLEANUP.json", cleanup)
            write_json(out / "PUBLICATION_RESULT.json", result)
    print(json.dumps(result, indent=2))


def preflight(args):
    plan = {"action": "scope_preflight" if args.execute else "plan_only", "repository": REPOSITORY,
            "payload_downloaded": False, "docker_invoked": False, "competition_upload_performed": False}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    actor, token = os.environ.get("GITHUB_ACTOR"), os.environ.get("T3_REGISTRY_TOKEN")
    require(actor and token, "workflow actor and ephemeral scope token required")
    scope_preflight(Registry(), (actor, token), out / "SCOPE_PROBE.json")
    print(json.dumps({**plan, "scope_probe_passed": True}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    archive = sub.add_parser("archive")
    archive.add_argument("--evidence", type=Path, required=True)
    archive.add_argument("--completion", type=Path, required=True)
    archive.add_argument("--bundle", type=Path, required=True)
    archive.add_argument("--final-dir", type=Path)
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("--bundle", type=Path, required=True)
    publish_parser.add_argument("--expected-bundle-sha256", required=True)
    publish_parser.add_argument("--out", type=Path, required=True)
    probe_parser = sub.add_parser("preflight")
    probe_parser.add_argument("--out", type=Path, required=True)
    probe_parser.add_argument("--execute", action="store_true")
    for command in (archive, publish_parser):
        command.add_argument("--docker", default="docker")
        command.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    {"archive": export_bundle, "publish": publish, "preflight": preflight}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Publication controller rejected action: " + type(error).__name__)
        raise SystemExit(1)
