#!/usr/bin/env python3
"""Retekess TD175P Pager über Raspberry Pi und CC1101 auslösen."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass

try:
    import pigpio
    import spidev
except ImportError as exc:
    raise SystemExit(
        "Fehlendes Paket.\n"
        "Installiere:\n"
        "sudo apt install pigpio python3-pigpio python3-spidev\n"
        "Danach:\n"
        "sudo systemctl enable --now pigpiod"
    ) from exc


# CC1101-Register
IOCFG2 = 0x00
IOCFG1 = 0x01
IOCFG0 = 0x02
FIFOTHR = 0x03
PKTCTRL1 = 0x07
PKTCTRL0 = 0x08
FSCTRL1 = 0x0B
FSCTRL0 = 0x0C
FREQ2 = 0x0D
FREQ1 = 0x0E
FREQ0 = 0x0F
MDMCFG4 = 0x10
MDMCFG3 = 0x11
MDMCFG2 = 0x12
MDMCFG1 = 0x13
MDMCFG0 = 0x14
DEVIATN = 0x15
MCSM2 = 0x16
MCSM1 = 0x17
MCSM0 = 0x18
FOCCFG = 0x19
BSCFG = 0x1A
AGCCTRL2 = 0x1B
AGCCTRL1 = 0x1C
AGCCTRL0 = 0x1D
FREND1 = 0x21
FREND0 = 0x22
FSCAL3 = 0x23
FSCAL2 = 0x24
FSCAL1 = 0x25
FSCAL0 = 0x26
TEST2 = 0x2C
TEST1 = 0x2D
TEST0 = 0x2E
PATABLE = 0x3E

# CC1101-Statusregister
MARCSTATE = 0x35
PARTNUM = 0x30
VERSION = 0x31

# CC1101-Kommandos
SRES = 0x30
SCAL = 0x33
STX = 0x35
SIDLE = 0x36
SFTX = 0x3B

READ_BURST = 0xC0
WRITE_BURST = 0x40


@dataclass(frozen=True)
class Timing:
    """Gemessene TD175P-Pulszeiten in Mikrosekunden."""

    one_high_us: int = 640
    one_low_us: int = 195

    zero_high_us: int = 220
    zero_low_us: int = 615

    trailer_high_us: int = 220
    frame_gap_us: int = 6680

    repeats: int = 30


class CC1101:
    """Minimaler CC1101-Treiber für den TD175P-Sender."""

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        speed_hz: int = 4_000_000,
    ) -> None:
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed_hz
        self.spi.mode = 0

    def close(self) -> None:
        self.spi.close()

    def strobe(self, command: int) -> int:
        return self.spi.xfer2([command])[0]

    def write(self, address: int, value: int) -> None:
        self.spi.xfer2(
            [
                address & 0x3F,
                value & 0xFF,
            ]
        )

    def write_burst(
        self,
        address: int,
        values: list[int],
    ) -> None:
        self.spi.xfer2(
            [
                (address & 0x3F) | WRITE_BURST,
                *values,
            ]
        )

    def read_status(self, address: int) -> int:
        return self.spi.xfer2(
            [
                (address & 0x3F) | READ_BURST,
                0x00,
            ]
        )[1]

    def reset(self) -> None:
        self.strobe(SIDLE)
        time.sleep(0.001)

        self.strobe(SRES)
        time.sleep(0.005)

    def wait_state(
        self,
        wanted: int,
        timeout_s: float = 0.1,
    ) -> bool:
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            state = self.read_status(MARCSTATE) & 0x1F

            if state == wanted:
                return True

            time.sleep(0.001)

        return False

    def configure_async_ook(self, power: int) -> None:
        """Konfiguriert den CC1101 für 433,92 MHz und asynchrones OOK."""

        registers = {
            IOCFG2: 0x29,
            IOCFG1: 0x2E,
            IOCFG0: 0x0D,

            FIFOTHR: 0x47,

            PKTCTRL1: 0x00,
            PKTCTRL0: 0x32,

            FSCTRL1: 0x06,
            FSCTRL0: 0x00,

            FREQ2: 0x10,
            FREQ1: 0xB0,
            FREQ0: 0x71,

            MDMCFG4: 0x48,
            MDMCFG3: 0x93,
            MDMCFG2: 0x30,
            MDMCFG1: 0x00,
            MDMCFG0: 0xF8,

            DEVIATN: 0x00,

            MCSM2: 0x07,
            MCSM1: 0x30,
            MCSM0: 0x18,

            FOCCFG: 0x16,
            BSCFG: 0x6C,

            AGCCTRL2: 0x43,
            AGCCTRL1: 0x40,
            AGCCTRL0: 0x91,

            FREND1: 0x56,
            FREND0: 0x11,

            FSCAL3: 0xEF,
            FSCAL2: 0x2D,
            FSCAL1: 0x17,
            FSCAL0: 0x1F,

            TEST2: 0x81,
            TEST1: 0x35,
            TEST0: 0x09,
        }

        for address, value in registers.items():
            self.write(address, value)

        # PATABLE[0] = aus
        # PATABLE[1] = konfigurierte Sendeleistung
        self.write_burst(
            PATABLE,
            [
                0x00,
                power & 0xFF,
            ],
        )


def pager_bcd(pager: int) -> int:
    """Wandelt die Pagernummer 1–30 in den BCD-Wert um."""

    if not 1 <= pager <= 30:
        raise ValueError(
            "Pagernummer muss zwischen 1 und 30 liegen."
        )

    return ((pager // 10) << 4) | (pager % 10)


def payload_for(pager: int) -> bytes:
    """Erzeugt das bestätigte TD175P-Ruftelegramm."""

    return bytes(
        (
            pager_bcd(pager),
            0x00,
            0x92,
            0x02,
        )
    )


def bits_lsb_first(payload: bytes) -> list[int]:
    """Wandelt die Bytes in LSB-first-Bits um."""

    return [
        (byte >> bit_position) & 1
        for byte in payload
        for bit_position in range(8)
    ]


def build_wave(
    pi: pigpio.pi,
    gpio: int,
    payload: bytes,
    timing: Timing,
) -> int:
    """Erstellt die komplette TD175P-Sendewelle."""

    mask = 1 << gpio
    pulses: list[pigpio.pulse] = []
    bits = bits_lsb_first(payload)

    for _ in range(timing.repeats):
        for bit in bits:
            if bit:
                high_us = timing.one_high_us
                low_us = timing.one_low_us
            else:
                high_us = timing.zero_high_us
                low_us = timing.zero_low_us

            pulses.append(
                pigpio.pulse(
                    mask,
                    0,
                    high_us,
                )
            )

            pulses.append(
                pigpio.pulse(
                    0,
                    mask,
                    low_us,
                )
            )

        pulses.append(
            pigpio.pulse(
                mask,
                0,
                timing.trailer_high_us,
            )
        )

        pulses.append(
            pigpio.pulse(
                0,
                mask,
                timing.frame_gap_us,
            )
        )

    pi.wave_clear()

    result = pi.wave_add_generic(pulses)

    if result < 0:
        raise RuntimeError(
            f"pigpio konnte die Pulse nicht übernehmen: {result}"
        )

    wave_id = pi.wave_create()

    if wave_id < 0:
        raise RuntimeError(
            f"pigpio konnte die Sendewelle nicht erzeugen: {wave_id}"
        )

    return wave_id


def send_pager(
    pager: int,
    gpio: int = 24,
    spi_bus: int = 0,
    spi_device: int = 0,
    power: int = 0x60,
    repeats: int = 30,
    confirm: bool = True,
) -> None:
    """Sendet einen Ruf an den angegebenen Pager."""

    if not 1 <= repeats <= 30:
        raise ValueError(
            "Wiederholungszahl muss zwischen 1 und 30 liegen."
        )

    timing = Timing(repeats=repeats)
    payload = payload_for(pager)

    print(
        f"Pager {pager}: "
        f"{' '.join(f'{byte:02X}' for byte in payload)}"
    )
    print("Frequenz: 433,92 MHz")
    print(f"GPIO: {gpio}")
    print(f"Sendeleistung: 0x{power:02X}")
    print(f"Wiederholungen: {repeats}")

    if confirm:
        answer = input(
            "Pager jetzt auslösen? [j/N] "
        ).strip().lower()

        if answer not in {
            "j",
            "ja",
            "y",
            "yes",
        }:
            print("Abgebrochen.")
            return

    pi = pigpio.pi()

    if not pi.connected:
        raise RuntimeError(
            "Keine Verbindung zu pigpiod. "
            "Starte: sudo systemctl start pigpiod"
        )

    radio: CC1101 | None = None
    wave_id = -1
    aborted = False

    def stop_now(
        _signum: int,
        _frame: object,
    ) -> None:
        nonlocal aborted

        aborted = True
        pi.wave_tx_stop()

    old_sigint = signal.signal(
        signal.SIGINT,
        stop_now,
    )

    try:
        radio = CC1101(
            bus=spi_bus,
            device=spi_device,
        )

        radio.reset()

        part = radio.read_status(PARTNUM)
        version = radio.read_status(VERSION)

        if part != 0x00 or version != 0x14:
            raise RuntimeError(
                "Unerwarteter CC1101: "
                f"PARTNUM=0x{part:02X}, "
                f"VERSION=0x{version:02X}"
            )

        pi.set_mode(
            gpio,
            pigpio.OUTPUT,
        )

        pi.write(
            gpio,
            0,
        )

        radio.configure_async_ook(power)

        radio.strobe(SIDLE)
        radio.strobe(SFTX)
        radio.strobe(SCAL)

        time.sleep(0.002)

        wave_id = build_wave(
            pi=pi,
            gpio=gpio,
            payload=payload,
            timing=timing,
        )

        radio.strobe(STX)

        # MARCSTATE 0x13 = TX
        if not radio.wait_state(0x13):
            raise RuntimeError(
                "CC1101 erreicht den TX-Zustand nicht."
            )

        pi.wave_send_once(wave_id)

        deadline = time.monotonic() + 2.0

        while pi.wave_tx_busy() and not aborted:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Senden wurde nach zwei Sekunden "
                    "aus Sicherheitsgründen beendet."
                )

            time.sleep(0.01)

        if aborted:
            print("\nSenden wurde abgebrochen.")
        else:
            print(
                f"Pager {pager} wurde erfolgreich ausgelöst."
            )

    finally:
        pi.wave_tx_stop()

        if radio is not None:
            radio.strobe(SIDLE)

        pi.write(
            gpio,
            0,
        )

        if wave_id >= 0:
            pi.wave_delete(wave_id)

        if radio is not None:
            radio.close()

        pi.stop()

        signal.signal(
            signal.SIGINT,
            old_sigint,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Retekess TD175P Pager 1–30 auslösen"
        )
    )

    parser.add_argument(
        "pager",
        type=int,
        choices=range(1, 31),
        help="Pagernummer 1–30",
    )

    parser.add_argument(
        "--gpio",
        type=int,
        default=24,
        help="BCM-GPIO an CC1101 GDO0 (Standard: 24)",
    )

    parser.add_argument(
        "--spi-bus",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--spi-device",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--repeats",
        type=int,
        default=30,
        choices=range(1, 31),
    )

    parser.add_argument(
        "--power",
        type=lambda value: int(value, 0),
        default=0x60,
        help=(
            "CC1101 PATABLE-Wert "
            "(Standard: 0x60)"
        ),
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Bestätigungsfrage überspringen",
    )

    args = parser.parse_args()

    try:
        send_pager(
            pager=args.pager,
            gpio=args.gpio,
            spi_bus=args.spi_bus,
            spi_device=args.spi_device,
            power=args.power,
            repeats=args.repeats,
            confirm=not args.yes,
        )

        return 0

    except (
        ValueError,
        RuntimeError,
        TimeoutError,
        OSError,
    ) as exc:
        print(
            f"Fehler: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
