"""Filename templates use document metadata without interpreting it as code."""

import unittest

from otClient import Document, safe_windows_filename
from ot_app.filename_format import (
    format_document_filename,
    format_document_folder,
    validate_filename_format,
    validate_folder_format,
)


class FilenameFormatTests(unittest.TestCase):
    def setUp(self):
        self.document = Document("id-1", "PR.001.pdf", "Kalite Prosedürü", "", 3)

    def test_number_format_preserves_existing_names(self):
        for number in ("PR.001.pdf", "PR.001", "Report.PDF", "PR.REV", "manual.pdf.pdf", "Report.pdf."):
            with self.subTest(number=number):
                document = Document("id", number, "Title", "", 0)
                self.assertEqual(format_document_filename("{numara}", document), number)

    def test_all_tags_use_server_metadata_and_keep_extension_at_end(self):
        self.assertEqual(
            format_document_filename("{numara} - {ad} - Rev{revizyon}", self.document),
            "PR.001 - Kalite Prosedürü - Rev3.pdf",
        )

    def test_reordered_and_repeated_tags_and_zero_revision(self):
        document = Document("id", "DOC-01.PDF", "İş Akışı", "", 0)
        self.assertEqual(
            format_document_filename("{revizyon}_{ad}_{numara}_{revizyon}", document),
            "0_İş Akışı_DOC-01_0.PDF",
        )

    def test_numeric_number_suffix_is_not_an_extension(self):
        document = Document("id", "PR.001", "Title", "", 2)
        self.assertEqual(format_document_filename("{numara}_R{revizyon}", document), "PR.001_R2")

    def test_empty_title_falls_back_to_document_number(self):
        document = Document("id", "DOC-01.pdf", "", "", 2)
        self.assertEqual(format_document_filename("{ad}", document), "DOC-01.pdf")

    def test_metadata_is_not_parsed_again_as_template(self):
        document = Document("id", "DOC-01.pdf", "{numara} {revizyon}", "", 2)
        self.assertEqual(format_document_filename("{ad}", document), "{numara} {revizyon}.pdf")

    def test_metadata_stays_within_one_safe_filename(self):
        document = Document("id", "DOC-01.pdf", "../../CON:report", "", 2)
        name = safe_windows_filename(format_document_filename("{ad}", document), document.id)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertNotIn(":", name)
        self.assertTrue(name.endswith(".pdf"))

    def test_format_rejects_missing_unknown_and_malformed_tags(self):
        for value in ("", " ", "report", "{title}", "{ad", "ad}", "{{ad}}", "{ad!r}",
                      "{revizyon:02d}", "{ad.__class__}", "{ad[0]}", "{ad}{unknown}"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_filename_format(value)

    def test_format_rejects_paths_controls_invalid_types_and_excessive_length(self):
        for value in (None, 1, "../{ad}", "C:\\{ad}", "{ad}:copy", "{ad}\n", "{ad}\x00",
                      "{ad}\x7f", "{ad}\ud800", "x" * 257 + "{ad}"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate_filename_format(value)


class FolderFormatTests(unittest.TestCase):
    def test_folder_number_strips_only_known_source_extension(self):
        for number, expected in (
            ("PR.001.pdf", "PR.001"), ("PR.001", "PR.001"),
            ("Report.PDF", "Report"), ("manual.pdf.pdf", "manual.pdf"),
        ):
            with self.subTest(number=number):
                self.assertEqual(
                    format_document_folder("{numara}", Document("id", number, "Title", "", 0)),
                    expected,
                )

    def test_folder_expands_repeated_tags_without_appending_an_extension(self):
        selected = Document("id", "PR.001.pdf", "Kalite Prosedürü", "", 3)
        self.assertEqual(
            format_document_folder(" {ad} - {numara} - R{revizyon}_{revizyon} ", selected),
            "Kalite Prosedürü - PR.001 - R3_3",
        )

    def test_folder_title_falls_back_to_number_and_metadata_remains_literal(self):
        for title, expected in ((" ", "PR.001"), ("{numara}:test", "{numara}:test")):
            with self.subTest(title=title):
                selected = Document("id", "PR.001.pdf", title, "", 0)
                self.assertEqual(format_document_folder("{ad}", selected), expected)

    def test_folder_format_rejects_paths_controls_and_formatting_expressions(self):
        for value in (
            "", " ", None, 1, "literal", "../{ad}", "C:\\{ad}", "{ad}\n",
            "{ad}\x00", "{ad}\x7f", "{ad}\ud800", "x" * 257 + "{ad}",
            "{title}", "{{ad}}", "{ad!r}", "{revizyon:02d}", "{ad.__class__}",
        ):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate_folder_format(value)


if __name__ == "__main__":
    unittest.main()
