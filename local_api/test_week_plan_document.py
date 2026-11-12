import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from week_plan_document import MAX_PDF_BYTES, DocumentUnavailable, read_document


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.attachments = self.root / "db/attachments"
        self.attachments.mkdir(parents=True)
        self.source = self.attachments / "plan.pdf"
        self.body = b"%PDF-1.4\nfictional bytes for transport tests\n%%EOF\n"
        self.source.write_bytes(self.body)

    def tearDown(self):
        self.temp.cleanup()

    def read(self, source=None, **extra):
        return read_document(self.root, json.dumps({"source_pdf": str(source or self.source), **extra}))

    def test_original_bytes_and_optional_fingerprint(self):
        self.assertEqual(self.read(), self.body)  # legacy layout without a hash
        self.assertEqual(self.read(source_sha256=hashlib.sha256(self.body).hexdigest()), self.body)

    def test_replaced_document_fails_closed(self):
        with self.assertRaises(DocumentUnavailable):
            self.read(source_sha256="0" * 64)
        with self.assertRaises(DocumentUnavailable):
            self.read(source_sha256=True)

    def test_paths_and_metadata_are_not_a_generic_file_server(self):
        outside = self.root / "private.pdf"
        outside.write_bytes(self.body)
        for value in (outside, self.attachments / "../private.pdf", "https://example.invalid/a.pdf", "plan.pdf"):
            with self.subTest(value=str(value)), self.assertRaises(DocumentUnavailable):
                self.read(value)
        for value in ("not json", "[]", "{}", '{"source_pdf":3}', " " * 2_000_001, "[" * 2000 + "]" * 2000):
            with self.assertRaises(DocumentUnavailable):
                read_document(self.root, value)

    def test_symlinks_are_rejected_for_files_and_directories(self):
        alias = self.attachments / "alias.pdf"
        alias.symlink_to(self.source)
        nested = self.attachments / "nested"
        nested.symlink_to(self.attachments, target_is_directory=True)
        for source in (alias, nested / "plan.pdf"):
            with self.assertRaises(DocumentUnavailable):
                self.read(source)

    def test_missing_non_pdf_directory_fifo_and_oversized_files(self):
        for payload in (b"not a pdf", b"%PDF-1.4\n" + b"x" * MAX_PDF_BYTES):
            self.source.write_bytes(payload)
            with self.assertRaises(DocumentUnavailable):
                self.read()
        self.source.unlink()
        with self.assertRaises(DocumentUnavailable):
            self.read()
        self.source.mkdir()
        with self.assertRaises(DocumentUnavailable):
            self.read()
        self.source.rmdir()
        os.mkfifo(self.source)
        with self.assertRaises(DocumentUnavailable):
            self.read()

    def test_attachment_root_cannot_be_redirected(self):
        actual = self.root / "moved"
        self.attachments.rename(actual)
        self.attachments.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(DocumentUnavailable):
            self.read()
