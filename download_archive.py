"""Download a purchased export using a URL supplied in environment settings.

Never print the signed URL. This program makes no purchases or API requests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
from urllib.parse import urlsplit
import urllib.request


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Download link must be an HTTPS URL without embedded login credentials')
    return parts.hostname


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, destination):
    host = validate_url(url)
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + '.part')
    if destination.exists() or partial.exists() or destination.with_suffix('.download.json').exists():
        raise ValueError('Destination or partial download exists; choose a new --output path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(HTTPSRedirects())
    # URLs and redirect targets are used only in memory; do not save them.
    print('Download host:', host, flush=True)
    digest = hashlib.sha256()
    size, next_progress = 0, 64 * 1024 * 1024
    with opener.open(request, timeout=45) as response:
        if response.status != 200:
            raise ValueError(f'Unexpected response status: {response.status}')
        if response.headers.get('Content-Encoding', 'identity') != 'identity':
            raise ValueError('Unexpected transport encoding; download stopped')
        length = response.headers.get('Content-Length')
        expected = int(length) if length is not None else None
        with partial.open('xb') as stream:
            while chunk := response.read(4 * 1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if size >= next_progress:
                    print(f'Downloaded {size / (1024**2):.0f} MiB', flush=True)
                    next_progress = size + 64 * 1024 * 1024
    if expected is not None and size != expected:
        raise ValueError('Incomplete download: byte count differs from Content-Length')
    with partial.open('rb') as stream:
        head = stream.read(4)
        if size < 12:
            raise ValueError('Downloaded file is too small to be Parquet')
        stream.seek(-4, 2)
        if head != b'PAR1' or stream.read(4) != b'PAR1':
            raise ValueError('Response is not a Parquet file; check that the link is for the data file')
    partial.rename(destination)
    report = {'source_hostname': host, 'file': destination.name,
              'bytes': size, 'sha256': digest.hexdigest(),
              'checksum_note': 'Computed locally, not compared with a publisher checksum.'}
    destination.with_suffix('.download.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Download complete: {size} bytes. Saved: {destination}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/0xarchive/export.parquet'))
    parser.add_argument('--check-host', action='store_true', help='Print hostname only; do not download')
    args = parser.parse_args()
    url = os.environ.get('OXARCHIVE_DOWNLOAD_URL', '').strip()
    if not url:
        raise ValueError('Set OXARCHIVE_DOWNLOAD_URL securely in environment settings first')
    if args.check_host:
        print(validate_url(url))
    else:
        download(url, args.output)


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        # str(exc) or a traceback could expose the signed download URL.
        sys.exit(f'Download failed: HTTP {exc.code}. Check link expiry and network permissions.')
    except urllib.error.URLError:
        sys.exit('Download failed: connection error. Check allowed hostname and link availability.')
    except (ValueError, OSError) as exc:
        # Our validation messages contain no URL. OSError may refer to local paths.
        sys.exit(f'Download stopped: {exc}')
    except Exception:
        sys.exit('Download failed unexpectedly. The signed URL is omitted from diagnostics.')
