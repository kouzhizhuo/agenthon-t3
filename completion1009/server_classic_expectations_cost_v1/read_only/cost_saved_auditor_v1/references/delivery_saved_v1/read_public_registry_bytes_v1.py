"""Download and hash inert public image bytes; never execute an image or a layer."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request


REPOSITORY = 'kouzhizhuo/agenthon-t3-classic'
ROOT = 'https://ghcr.io/v2/' + REPOSITORY
ACCEPT = 'application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'
MANIFEST_TYPES = ACCEPT.split(', ')
GZIP_TYPES = ('application/vnd.docker.image.rootfs.diff.tar.gzip', 'application/vnd.oci.image.layer.v1.tar+gzip')
TAR_TYPES = ('application/vnd.oci.image.layer.v1.tar',)
CONFIG_TYPES = ('application/vnd.docker.container.image.v1+json', 'application/vnd.oci.image.config.v1+json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def digest(value):
    require(type(value) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value), 'exact sha256 digest required')
    return value[7:]


def pin(path):
    result = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            size += len(block)
            result.update(block)
    return {'bytes': size, 'sha256': result.hexdigest()}


def unpacked_pin(path, media_type, max_bytes):
    require(media_type in GZIP_TYPES + TAR_TYPES, 'supported inert layer compression')
    result = hashlib.sha256()
    size = 0
    with (gzip.open(path, 'rb') if media_type in GZIP_TYPES else path.open('rb')) as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            size += len(block)
            require(size <= max_bytes, 'finite uncompressed layer bound')
            result.update(block)
    return {'bytes': size, 'sha256': result.hexdigest()}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        require(urllib.parse.urlsplit(url).scheme == 'https', 'HTTPS public byte redirect required')
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if urllib.parse.urlsplit(request.full_url).netloc != urllib.parse.urlsplit(url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def download(opener, token, url, path, expected_digest=None, expected_bytes=None, max_bytes=8 * 1024**3):
    require(not path.exists() and not path.is_symlink(), 'fresh regular target required')
    attempts_file = path.with_name(path.name + '.download-attempts.json')
    require(not attempts_file.exists() and not attempts_file.is_symlink(), 'fresh download attempt receipt')
    requests = []
    for attempt in range(1, 4):
        partial = path.with_name(path.name + '.attempt-%d.partial' % attempt)
        require(not partial.exists() and not partial.is_symlink(), 'fresh bounded partial target')
        checksum, count = hashlib.sha256(), 0
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': ACCEPT})
        observed = {'attempt': attempt, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        requests.append(observed)
        attempts_file.write_text(json.dumps(requests, indent=2, sort_keys=True) + '\n')
        try:
            with opener.open(request, timeout=45) as response, partial.open('xb') as stream:
                require(response.status == 200, 'public response200 required')
                observed['status'] = response.status
                observed['final_host'] = urllib.parse.urlsplit(response.url).hostname
                observed['content_type'] = response.headers.get_content_type()
                observed['content_length'] = response.headers.get('Content-Length')
                observed['content_digest'] = response.headers.get('Docker-Content-Digest')
                if expected_bytes is not None and observed['content_length'] is not None:
                    require(int(observed['content_length']) == expected_bytes, 'actual response Content-Length')
                if expected_digest is not None and observed['content_digest'] is not None:
                    require(observed['content_digest'] == expected_digest, 'actual response digest header')
                for block in iter(lambda: response.read(1024**2), b''):
                    count += len(block)
                    require(count <= max_bytes and (expected_bytes is None or count <= expected_bytes), 'finite public byte boundary')
                    checksum.update(block)
                    stream.write(block)
            require(expected_bytes is None or count == expected_bytes, 'complete actual descriptor byte size')
            require(expected_digest is None or 'sha256:' + checksum.hexdigest() == expected_digest, 'complete actual descriptor byte digest')
            observed.update(bytes=count, sha256=checksum.hexdigest(), completed=True)
            attempts_file.write_text(json.dumps(requests, indent=2, sort_keys=True) + '\n')
            partial.rename(path)
            return {'path': path.name, 'bytes': count, 'sha256': checksum.hexdigest(),
                'requests': requests, 'attempts_receipt': {'path': attempts_file.name, **pin(attempts_file)}}
        except Exception as error:
            # Exception text may contain a redirected signed URL; record its class only.
            observed.update(bytes=count, completed=False, error_type=type(error).__name__)
            if partial.is_file():
                observed['retained_partial'] = {'path': partial.name, **pin(partial)}
            attempts_file.write_text(json.dumps(requests, indent=2, sort_keys=True) + '\n')
            require(not isinstance(error, ValueError), 'public byte contract failed; no network retry')
            if attempt == 3:
                raise RuntimeError('public byte download exhausted; partial bytes retained') from None
    raise RuntimeError('public byte download incomplete')


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--image', required=True)
    parser.add_argument('--tested-image-id', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    prefix = 'ghcr.io/' + REPOSITORY + '@'
    require(args.image.startswith(prefix), 'existing authorized public repository required')
    manifest_digest = args.image[len(prefix):]
    digest(manifest_digest)
    digest(args.tested_image_id)
    folder = args.out_dir
    require(not folder.exists() and not folder.is_symlink() and folder.parent.is_dir(), 'fresh explicit public evidence folder')
    folder.mkdir()
    report = {'schema': 't3-anonymous-registry-byte-readback-v1', 'image': args.image,
        'tested_image_id': args.tested_image_id, 'anonymous': True, 'all_passed': False,
        'participant_executed': False, 'native_compiled': False, 'layers': [],
        'token_saved_or_printed': False, 'signed_urls_saved_or_printed': False}
    target = folder / 'REGISTRY_BYTE_READBACK_v1.json'
    opener = urllib.request.build_opener(SafeRedirect())
    try:
        token_url = 'https://ghcr.io/token?' + urllib.parse.urlencode({'scope': 'repository:' + REPOSITORY + ':pull', 'service': 'ghcr.io'})
        with opener.open(token_url, timeout=30) as response:
            require(response.status == 200, 'anonymous pull-scope token required')
            raw = response.read(1024**2 + 1)
            require(len(raw) <= 1024**2, 'bounded anonymous token response')
            token = read_json(raw)['token']
        report['manifest'] = download(opener, token, ROOT + '/manifests/' + manifest_digest,
            folder / 'manifest.json', expected_digest=manifest_digest, max_bytes=16 * 1024**2)
        manifest = read_json((folder / 'manifest.json').read_bytes())
        require(manifest['schemaVersion'] == 2 and manifest['mediaType'] in MANIFEST_TYPES
            and type(manifest['layers']) is list and 0 < len(manifest['layers']) <= 128, 'single-platform manifest contract')
        descriptor = manifest['config']
        require(descriptor['mediaType'] in CONFIG_TYPES and descriptor['digest'] == args.tested_image_id
            and type(descriptor['size']) is int and 0 < descriptor['size'] <= 16 * 1024**2, 'exact tested config descriptor')
        report['config'] = download(opener, token, ROOT + '/blobs/' + descriptor['digest'], folder / 'config.json',
            expected_digest=descriptor['digest'], expected_bytes=descriptor['size'], max_bytes=16 * 1024**2)
        config = read_json((folder / 'config.json').read_bytes())
        require(config['architecture'] == 'amd64' and config['os'] == 'linux'
            and config['rootfs']['type'] == 'layers' and len(config['rootfs']['diff_ids']) == len(manifest['layers']), 'linuxamd64 tested rootfs chain')
        seen = {}
        for index, layer in enumerate(manifest['layers']):
            layer_hash = digest(layer['digest'])
            require(type(layer['size']) is int and 0 < layer['size'] <= 8 * 1024**3
                and layer['mediaType'] in GZIP_TYPES + TAR_TYPES, 'finite ordinary layer descriptor')
            if layer_hash not in seen:
                row = download(opener, token, ROOT + '/blobs/' + layer['digest'], folder / ('layer-' + layer_hash + '.blob'),
                    expected_digest=layer['digest'], expected_bytes=layer['size'])
                row['uncompressed'] = unpacked_pin(folder / row['path'], layer['mediaType'], 16 * 1024**3)
                seen[layer_hash] = row
            row = dict(seen[layer_hash])
            require(row['bytes'] == layer['size'] and 'sha256:' + row['uncompressed']['sha256'] == config['rootfs']['diff_ids'][index], 'complete layer bytes and actual uncompressed diffID')
            report['layers'].append(row)
            target.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
            print('layer', index + 1, 'of', len(manifest['layers']), 'complete bytes and diffID verified', flush=True)
        report['all_passed'] = True
    except Exception as error:
        report['failure'] = {'type': type(error).__name__, 'message': 'Anonymous inert registry byte validation did not complete; actual saved bytes retained.'}
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'all_passed': report['all_passed'], 'report': str(target), 'layers': len(report['layers'])}), flush=True)
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
