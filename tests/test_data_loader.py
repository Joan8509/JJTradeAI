"""Pruebas de normalización de exportaciones TC2000."""

from io import BytesIO
import unittest

from data_loader import load_tc2000_upload


HEADERS = [
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Moving Average 20",
    "Moving Average 40",
    "Moving Average 100",
    "Moving Average 200",
    "Volume",
    "Worden Stochastics",
]


def _upload(rows: list[list[object]], separator: str = "\t"):
    text = separator.join(HEADERS) + "\n"
    text += "\n".join(separator.join(map(str, row)) for row in rows)
    return load_tc2000_upload(BytesIO(text.encode("utf-8")), "sample.txt")


class DataLoaderTests(unittest.TestCase):
    def test_tab_export_is_normalized_and_sorted(self) -> None:
        rows = [
            ["2026-06-24", 10, 11, 9, 10.5, 10, 9, 8, 7, 1000, 55],
            ["2026-06-23", 9, 10, 8, 9.5, 9, 8, 7, 6, 900, 50],
        ]

        result = _upload(rows)

        self.assertEqual(result.columns[0], "date")
        self.assertEqual(result.iloc[0]["close"], 9.5)
        self.assertEqual(str(result["close"].dtype), "float64")

    def test_invalid_numeric_value_is_rejected(self) -> None:
        row = ["2026-06-24", 10, 11, 9, "INVALID", 10, 9, 8, 7, 1000, 55]

        with self.assertRaises(ValueError):
            _upload([row])

    def test_invalid_date_is_rejected(self) -> None:
        row = ["NOT-A-DATE", 10, 11, 9, 10, 10, 9, 8, 7, 1000, 55]

        with self.assertRaises(ValueError):
            _upload([row])

    def test_missing_column_is_rejected(self) -> None:
        text = "Date,Open\n2026-06-24,10\n"

        with self.assertRaises(ValueError):
            load_tc2000_upload(BytesIO(text.encode("utf-8")), "sample.csv")

    def test_empty_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_tc2000_upload(BytesIO(b""), "sample.csv")

    def test_header_only_file_is_rejected(self) -> None:
        text = ",".join(HEADERS) + "\n"

        with self.assertRaises(ValueError):
            load_tc2000_upload(BytesIO(text.encode("utf-8")), "sample.csv")

    def test_empty_required_numeric_cell_is_rejected(self) -> None:
        row = ["2026-06-24", 10, 11, 9, "", 10, 9, 8, 7, 1000, 55]

        with self.assertRaises(ValueError):
            _upload([row])

    def test_negative_required_numeric_value_is_rejected(self) -> None:
        row = ["2026-06-24", 10, 11, 9, 10, 10, 9, 8, 7, -1000, 55]

        with self.assertRaises(ValueError):
            _upload([row])

    def test_high_below_ohlc_values_is_rejected(self) -> None:
        row = ["2026-06-24", 10, 9, 8, 10, 10, 9, 8, 7, 1000, 55]

        with self.assertRaisesRegex(ValueError, "high"):
            _upload([row])

    def test_low_above_ohlc_values_is_rejected(self) -> None:
        row = ["2026-06-24", 10, 11, 12, 10, 10, 9, 8, 7, 1000, 55]

        with self.assertRaisesRegex(ValueError, "low"):
            _upload([row])


if __name__ == "__main__":
    unittest.main()
