from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from download_archive import download, validate_url


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length)}


class DownloadTests(unittest.TestCase):
    def test_stream_real_parquet_and_keep_signed_query_out_of_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.parquet'
            con = duckdb.connect()
            con.execute('COPY (SELECT 42 AS value) TO ? (FORMAT PARQUET)', [str(source)])
            con.close()
            data = source.read_bytes()
            target = Path(folder) / 'download.parquet'
            logs = io.StringIO()
            with patch('download_archive.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(data)
                with redirect_stdout(logs):
                    download('https://example.com/export?signature=PRIVATE_TEST_VALUE', target)
            self.assertEqual(target.read_bytes(), data)
            report = json.loads(target.with_suffix('.download.json').read_text())
            self.assertEqual(report['sha256'], hashlib.sha256(data).hexdigest())
            self.assertNotIn('PRIVATE_TEST_VALUE', logs.getvalue())
            self.assertNotIn('PRIVATE_TEST_VALUE', json.dumps(report))

    def test_incomplete_download_does_not_become_final_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'incomplete.parquet'
            with patch('download_archive.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(b'PAR1truncated', length=999)
                with self.assertRaisesRegex(ValueError, 'Incomplete download'):
                    download('https://example.com/export', target)
            self.assertFalse(target.exists())

    def test_reject_insecure_and_embedded_credentials(self):
        for url in ('http://example.com/file', 'https://user:password@example.com/file'):
            with self.assertRaises(ValueError):
                validate_url(url)


if __name__ == '__main__':
    unittest.main()
