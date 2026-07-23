"""Hardwarefreie Basistests der TD175P-Protokollbibliothek."""

import unittest

from td175p_radio import (
    TD175PTiming,
    bits_lsb_first,
    encode_bcd_address,
    payload_for,
    pulse_durations,
    validate_pager_command,
)


class ProtocolTests(unittest.TestCase):
    def test_confirmed_payloads(self) -> None:
        self.assertEqual(payload_for(1), bytes.fromhex("01 00 92 02"))
        self.assertEqual(payload_for(16), bytes.fromhex("16 00 92 02"))
        self.assertEqual(payload_for(20), bytes.fromhex("20 00 92 02"))
        self.assertEqual(payload_for(30), bytes.fromhex("30 00 92 02"))

    def test_power_off_payload(self) -> None:
        self.assertEqual(encode_bcd_address(999), bytes.fromhex("99 09"))
        self.assertEqual(payload_for(999), bytes.fromhex("99 09 92 02"))

    def test_allowed_commands(self) -> None:
        for pager in (1, 16, 30, 999):
            self.assertEqual(validate_pager_command(pager), pager)
        for pager in (0, 31, 998, 1000):
            with self.assertRaises(ValueError):
                validate_pager_command(pager)

    def test_lsb_first(self) -> None:
        self.assertEqual(
            bits_lsb_first(bytes.fromhex("01")),
            (1, 0, 0, 0, 0, 0, 0, 0),
        )
        self.assertEqual(
            bits_lsb_first(bytes.fromhex("20")),
            (0, 0, 0, 0, 0, 1, 0, 0),
        )

    def test_pulse_durations(self) -> None:
        timing = TD175PTiming()
        durations = pulse_durations(bytes.fromhex("01"), timing)
        self.assertEqual(durations[0], (640, 195))
        self.assertTrue(all(value == (220, 615) for value in durations[1:]))


if __name__ == "__main__":
    unittest.main()
