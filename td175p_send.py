#!/usr/bin/env python3
"""Retekess TD175P pager sender for Raspberry Pi + CC1101.

The waveform is based on measured calls for pagers 1, 2, 3, 4, 16 and 20.
Use only with your own paging system and on frequencies you are allowed to use.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from dataclasses import dataclass

try:
    import pigpio
    import spidev
except ImportError as exc:
    raise SystemExit(
        "Fehlendes Paket. Installiere: sudo apt install pigpio python3-pigpio "
        "python3-spidev\nDanach: sudo systemctl enable --now pigpiod"
    ) from exc


# CC1101 registers
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
MARCSTATE = 0x35
PARTNUM = 0x30
VERSION = 0x31

# Command strobes
SRES = 0x30
SCAL = 0x33
SRX = 0x34
STX = 0x35
SIDLE = 0x36
SFTX = 0x3B

READ_BURST = 0xC0
WRITE_BURST = 0x40


@dataclass(frozen=True)
class Timing:
    """Measured TD175P pulse timing in microseconds."""

    one_high_us: int = 640
    one_low_us: int = 195
    zero_high_us: int = 220
    zero_low_us: int = 615
    trailer_high_us: int = 220
    frame_gap_us: int = 6680
    repeats: int = 30


class CC1101:
    """Small CC1101 driver containing only what this sender needs."""

    def __init__(self, bus: int, device: int, speed_hz: int = 4_000_000) -> None:
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed_hz
        self.spi.mode = 0

    def close(self) -> None:
        self.spi.close()

    def strobe(self, command: int) -> int:
        return self.spi.xfer2([command])[0]

    def write(self, address: int, value: int) -> None:
        self.spi.xfer2([address & 0x3F, value & 0xFF])

    def write_burst(self, address: int, values: list[int]) -> None:
        self.spi.xfer2([(address & 0x3F) | WRITE_BURST, *values])

    def read_status(self, address: int) -> int:
        return self.spi.xfer2([(address & 0x3F) | READ_BURST, 0])[1]

    def reset(self) -> None:
        self.strobe(SIDLE)
        time.sleep(0.001)
        self.strobe(SRES)
        time.sleep(0.005)

    def wait_state(self, wanted: int, timeout_s: float = 0.1) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if (self.read_status(MARCSTATE) & 0x1F) == wanted:
                return True
            time.sleep(0.001)
        return False

    def configure_async_ook(self, power: int) -> None:
        """Apply the measured 433.92 MHz asynchronous OOK profile."""
        registers = {
            IOCFG2: 0x29,
            IOCFG1: 0x2E,
            IOCFG0: 0x0D,  # asynchronous serial data on GDO0
            FIFOTHR: 0x47,
            PKTCTRL1: 0x00,
            PKTCTRL0: 0x32,  # asynchronous serial mode
            FSCTRL1: 0x06,
            FSCTRL0: 0x00,
            FREQ2: 0x10,     # 433.92 MHz for a 26 MHz crystal
            FREQ1: 0xB0,
            FREQ0: 0x71,
            MDMCFG4: 0x48,
            MDMCFG3: 0x93,
            MDMCFG2: 0x30,  # ASK/OOK, no sync detection
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
            FREND0: 0x11,   # PATABLE index 1 for logical HIGH
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
        # In OOK mode PATABLE[0] is off and PATABLE[1] is the selected power.
        self.write_burst(PATABLE, [0x00, power & 0xFF])


def pager_bcd(pager: int) -> int:
    """Convert printed pager number 1..30 to its measured BCD address."""
    if not 1 <= pager <= 30:
        raise ValueError("Pagernummer muss zwischen 1 und 30 liegen.")
    return ((pager // 10) << 4) | (pager % 10)


def payload_for(pager: int) -> bytes:
    """Return the confirmed four-byte call payload."""
    return bytes((pager_bcd(pager), 0x00, 0x92, 0x02))


def bits_lsb_first(payload: bytes) -> list[int]:
    """Return each byte least-significant bit first, as observed on air."""
    return [(byte >> bit) & 1 for byte in payload for bit in range(8)]


def build_wave(
    pi: pigpio.pi,
    gpio: int,
    payload: bytes,
    timing: Timing,
    invert: bool,
) -> int:
    """Build all 30 telegram repetitions as one deterministic pigpio wave."""
    mask = 1 << gpio
    pulses: list[pigpio.pulse] = []
    bits = bits_lsb_first(payload)

    def pulse(level: int, duration_us: int) -> pigpio.pulse:
        """Translate the captured level to the CC1101 TX input polarity."""
        physical_level = level ^ int(invert)
        if physical_level:
            return pigpio.pulse(mask, 0, duration_us)
        return pigpio.pulse(0, mask, duration_us)

    for _ in range(timing.repeats):
        for bit in bits:
            high = timing.one_high_us if bit else timing.zero_high_us
            low = timing.one_low_us if bit else timing.zero_low_us
            pulses.append(pulse(1, high))
            pulses.append(pulse(0, low))
        pulses.append(pulse(1, timing.trailer_high_us))
        pulses.append(pulse(0, timing.frame_gap_us))

    pi.wave_clear()
    pi.wave_add_generic(pulses)
    wave_id = pi.wave_create()
    if wave_id < 0:
        raise RuntimeError(f"pigpio konnte die Sendewelle nicht erzeugen: {wave_id}")
    return wave_id


def send_pager(args: argparse.Namespace) -> None:
    timing = Timing(repeats=args.repeats)
    payload = payload_for(args.pager)
    print(f"Pager {args.pager}: {' '.join(f'{x:02X}' for x in payload)}")
    print(f"Frequenz: 433,92 MHz | Wiederholungen: {timing.repeats}")
    print(f"Polarität: {'invertiert' if args.invert else 'direkt'}")
    if not args.yes:
        answer = input("Pager jetzt auslösen? [j/N] ").strip().lower()
        if answer not in {"j", "ja", "y", "yes"}:
            print("Abgebrochen.")
            return

    pi = pigpio.pi()
    if not pi.connected:
        raise RuntimeError("Keine Verbindung zu pigpiod. Starte: sudo systemctl start pigpiod")
    radio = CC1101(args.spi_bus, args.spi_device)
    wave_id = -1
    aborted = False

    def stop_now(_signum: int, _frame: object) -> None:
        nonlocal aborted
        aborted = True
        pi.wave_tx_stop()

    # signal.signal() is only legal in Python's main thread. The Leitstellen-
    # software may call this function from its background pager worker.
    old_sigint = None
    if threading.current_thread() is threading.main_thread():
        old_sigint = signal.signal(signal.SIGINT, stop_now)
    try:
        radio.reset()
        part = radio.read_status(PARTNUM)
        version = radio.read_status(VERSION)
        if part != 0x00 or version != 0x14:
            raise RuntimeError(
                f"Unerwarteter CC1101: PARTNUM=0x{part:02X}, VERSION=0x{version:02X}"
            )

        pi.set_mode(args.gpio, pigpio.OUTPUT)
        idle_level = int(args.invert)
        pi.write(args.gpio, idle_level)
        radio.configure_async_ook(args.power)
        radio.strobe(SIDLE)
        radio.strobe(SFTX)
        radio.strobe(SCAL)
        time.sleep(0.002)
        wave_id = build_wave(pi, args.gpio, payload, timing, args.invert)

        radio.strobe(STX)
        if not radio.wait_state(0x13):  # TX
            raise RuntimeError("CC1101 erreicht den TX-Zustand nicht.")

        pi.wave_send_once(wave_id)
        deadline = time.monotonic() + 2.0
        while pi.wave_tx_busy() and not aborted:
            if time.monotonic() > deadline:
                raise TimeoutError("Senden aus Sicherheitsgründen nach 2 Sekunden beendet.")
            time.sleep(0.01)

        if aborted:
            print("\nSenden abgebrochen.")
        else:
            print(f"Pager {args.pager} wurde ausgelöst.")
    finally:
        pi.wave_tx_stop()
        radio.strobe(SIDLE)
        pi.write(args.gpio, 0)
        if wave_id >= 0:
            pi.wave_delete(wave_id)
        radio.close()
        pi.stop()
        if old_sigint is not None:
            signal.signal(signal.SIGINT, old_sigint)


def trigger_pager(
    pager: int,
    *,
    gpio: int = 24,
    spi_bus: int = 0,
    spi_device: int = 0,
    power: int = 0x60,
    repeats: int = 30,
    invert: bool = True,
) -> None:
    """Programmatic API for a background worker in the Leitstellensoftware."""
    if not 1 <= repeats <= 30:
        raise ValueError("Wiederholungszahl muss zwischen 1 und 30 liegen.")
    args = argparse.Namespace(
        pager=pager,
        gpio=gpio,
        spi_bus=spi_bus,
        spi_device=spi_device,
        power=power,
        repeats=repeats,
        invert=invert,
        yes=True,
    )
    send_pager(args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Retekess TD175P Pager 1–30 auslösen")
    parser.add_argument("pager", type=int, choices=range(1, 31), help="Pagernummer 1–30")
    parser.add_argument("--gpio", type=int, default=24, help="BCM-GPIO an CC1101 GDO0 (Standard: 24)")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=30, choices=range(1, 31))
    parser.add_argument(
        "--power",
        type=lambda value: int(value, 0),
        default=0x60,
        help="CC1101 PATABLE-Wert; Standard 0x60 (erfolgreich getestete Einstellung)",
    )
    parser.set_defaults(invert=True)
    polarity = parser.add_mutually_exclusive_group()
    polarity.add_argument(
        "--invert",
        dest="invert",
        action="store_true",
        help="TX-Signal invertieren (Standard)",
    )
    polarity.add_argument(
        "--no-invert",
        dest="invert",
        action="store_false",
        help="TX-Signal ohne Invertierung ausgeben",
    )
    parser.add_argument("--yes", action="store_true", help="Bestätigungsfrage überspringen")
    args = parser.parse_args()
    try:
        send_pager(args)
        return 0
    except (ValueError, RuntimeError, TimeoutError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
