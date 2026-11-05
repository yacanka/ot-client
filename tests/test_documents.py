import codecs
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ot_app.documents import (
    MAX_DOCUMENTS,
    MAX_IDENTIFIER_LENGTH,
    MAX_INPUT_CHARACTERS,
    merge_document_numbers,
    parse_document_text,
    read_document_file,
    write_document_file,
)


class DocumentParsingTests(unittest.TestCase):
    def test_empty_and_bom_only_inputs(self):
        for text in ("", " \r\n\t ", "\ufeff", "\ufeff \n"):
            with self.subTest(text=repr(text)):
                self.assertEqual(parse_document_text(text), [])

    def test_mixed_excel_delimiters_preserve_order_and_identifier_semantics(self):
        self.assertEqual(
            parse_document_text(" 0012\t0012,Ab;ab\r\n X-7 ;\n"),
            ["0012", "Ab", "ab", "X-7"],
        )

    def test_quotes_delimiters_and_multiline_cells(self):
        self.assertEqual(
            parse_document_text('"A,01";"B;02"\t"C\t03"\n"D\n04"\n"E""05"'),
            ["A,01", "B;02", "C\t03", "D\n04", 'E"05'],
        )

    def test_crlf_inside_a_quoted_cell_is_preserved(self):
        self.assertEqual(parse_document_text('"A\r\nB"\r\nC'), ["A\r\nB", "C"])

    def test_whitespace_around_quoted_cells(self):
        self.assertEqual(parse_document_text('  " A,B " ; "C"  '), ["A,B", "C"])

    def test_literal_internal_quote_in_unquoted_identifier(self):
        self.assertEqual(parse_document_text('A"B\nC'), ['A"B', "C"])

    def test_bad_csv_quotes_are_rejected(self):
        for text in ('"unterminated', '"ok"junk', '"one";"two'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_document_text(text)

    def test_json_array_of_strings(self):
        self.assertEqual(
            parse_document_text('\ufeff[" 001 ", "001", "Ab", "ab", "A,B", ""]'),
            ["001", "Ab", "ab", "A,B"],
        )

    def test_malformed_or_nonstring_json_is_not_reinterpreted_as_identifiers(self):
        for text in ('["A",', '[A]', '{"number":"A"}', '[12]', '[null]', '[true]', '[{}]', '[["A"]]', '["A"] trailing'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_document_text(text)

    def test_merge_does_not_mutate_its_inputs_or_coerce_types(self):
        existing = [" A ", "001"]
        incoming = ["A", "a", "002"]
        self.assertEqual(merge_document_numbers(existing, incoming), ["A", "001", "a", "002"])
        self.assertEqual(existing, [" A ", "001"])
        self.assertEqual(incoming, ["A", "a", "002"])
        for incoming in ([12], [None], "ABC"):
            with self.subTest(incoming=incoming), self.assertRaises(ValueError):
                merge_document_numbers([], incoming)

    def test_nul_and_resource_limits_fail_explicitly(self):
        for text in ("A\x00B", "X" * (MAX_IDENTIFIER_LENGTH + 1), " " * (MAX_INPUT_CHARACTERS + 1)):
            with self.subTest(length=len(text)), self.assertRaises(ValueError):
                parse_document_text(text)
        with self.assertRaises(ValueError):
            merge_document_numbers([], (str(i) for i in range(MAX_DOCUMENTS + 1)))


class DocumentFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_utf8_bom_utf16_le_and_utf16_be(self):
        text = "0012\r\nİŞ-42\r\n"
        encoded_samples = [
            text.encode("utf-8"),
            codecs.BOM_UTF8 + text.encode("utf-8"),
            codecs.BOM_UTF16_LE + text.encode("utf-16-le"),
            codecs.BOM_UTF16_BE + text.encode("utf-16-be"),
        ]
        for index, encoded in enumerate(encoded_samples):
            with self.subTest(index=index):
                path = self.root / f"input-{index}.txt"
                path.write_bytes(encoded)
                self.assertEqual(read_document_file(path), ["0012", "İŞ-42"])

    def test_bomless_ascii_utf16_is_recognized(self):
        for encoding in ("utf-16-le", "utf-16-be"):
            with self.subTest(encoding=encoding):
                path = self.root / "input.txt"
                path.write_bytes("0012\nA-42".encode(encoding))
                self.assertEqual(read_document_file(path), ["0012", "A-42"])

    def test_bad_encoding_and_oversize_file_are_rejected(self):
        path = self.root / "invalid.txt"
        path.write_bytes(b"\xff\xff\xfe")
        with self.assertRaises(ValueError):
            read_document_file(path)
        path.write_bytes(b"12345")
        with patch("ot_app.documents.MAX_FILE_BYTES", 4), self.assertRaises(ValueError):
            read_document_file(path)

    def test_json_file_extension_requires_an_array_even_without_brackets(self):
        path = self.root / "numbers.json"
        for content in ("null", "true", '"0012"', "0012", "not-json"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                path.write_text(content, encoding="utf-8")
                read_document_file(path)

    def test_txt_and_json_roundtrip_canonical_identifiers(self):
        numbers = ["0012", "Ab", "ab", "A,B", "B;C", "C\tD", "D\nE", 'E"F', "=A1", "İŞ-42", "[A]"]
        for extension in ("txt", "json"):
            with self.subTest(extension=extension):
                path = self.root / f"numbers.{extension}"
                write_document_file(path, numbers)
                self.assertEqual(read_document_file(path), numbers)

    def test_simple_txt_is_readable_one_per_line(self):
        path = self.root / "numbers.txt"
        write_document_file(path, ["0012", "A-42"])
        self.assertEqual(path.read_text(encoding="utf-8"), "0012\nA-42\n")

    def test_json_looking_identifier_is_quoted_for_txt_roundtrip(self):
        path = self.root / "numbers.txt"
        for identifier in ("[A]", "{A}", "\ufeffA"):
            with self.subTest(identifier=identifier):
                write_document_file(path, [identifier])
                self.assertEqual(read_document_file(path), [identifier])

    def test_csv_formula_guard_does_not_modify_canonical_input(self):
        numbers = ["=SUM(A1:A2)", "+1", "-2", "@name", "0012", "A,B"]
        original = list(numbers)
        path = self.root / "numbers.csv"
        write_document_file(path, numbers)
        self.assertEqual(numbers, original)
        self.assertEqual(read_document_file(path), ["'=SUM(A1:A2)", "'+1", "'-2", "'@name", "0012", "A,B"])

    def test_failed_replace_preserves_existing_export_and_cleans_temporary_file(self):
        path = self.root / "numbers.txt"
        path.write_text("original\n", encoding="utf-8")
        with patch("ot_app.documents.os.replace", side_effect=PermissionError("locked")), self.assertRaises(OSError):
            write_document_file(path, ["replacement"])
        self.assertEqual(path.read_text(encoding="utf-8"), "original\n")
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_invalid_export_does_not_touch_existing_file(self):
        path = self.root / "numbers.json"
        path.write_text('["original"]', encoding="utf-8")
        with self.assertRaises(ValueError):
            write_document_file(path, ["A\x00B"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), ["original"])

    def test_export_encoding_overhead_cannot_produce_an_unimportable_file(self):
        path = self.root / "numbers.json"
        with patch("ot_app.documents.MAX_INPUT_CHARACTERS", 8), self.assertRaises(ValueError):
            write_document_file(path, ["12345678"])
        self.assertFalse(path.exists())
        with patch("ot_app.documents.MAX_FILE_BYTES", 8), self.assertRaises(ValueError):
            write_document_file(path, ["İŞ-42"])
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
