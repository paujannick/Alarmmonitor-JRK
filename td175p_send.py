#!/usr/bin/env python3
"""Send a Retekess TD175P pager alarm through a CC1101 module on Raspberry Pi."""

from __future__ import annotations

import argparse
import time

import RPi.GPIO as GPIO
import spidev

# CC1101 command strobes/registers used for packet transmission.
CC1101_IOCFG0 = 0x02
CC1101_FIFOTHR = 0x03
CC1101_PKTLEN = 0x06
CC1101_PKTCTRL1 = 0x07
CC1101_PKTCTRL0 = 0x08
CC1101_FSCTRL1 = 0x0B
CC1101_FREQ2 = 0x0D
CC1101_FREQ1 = 0x0E
CC1101_FREQ0 = 0x0F
CC1101_MDMCFG4 = 0x10
CC1101_MDMCFG3 = 0x11
CC1101_MDMCFG2 = 0x12
CC1101_DEVIATN = 0x15
CC1101_MCSM0 = 0x18
CC1101_FOCCFG = 0x19
CC1101_BSCFG = 0x1A
CC1101_AGCCTRL2 = 0x1B
CC1101_AGCCTRL1 = 0x1C
CC1101_AGCCTRL0 = 0x1D
CC1101_FREND0 = 0x22
CC1101_FSCAL3 = 0x23
CC1101_FSCAL2 = 0x24
CC1101_FSCAL1 = 0x25
CC1101_FSCAL0 = 0x26
CC1101_TEST2 = 0x2C
CC1101_TEST1 = 0x2D
CC1101_TEST0 = 0x2E
CC1101_PATABLE = 0x3E
CC1101_TXFIFO = 0x3F
CC1101_SRES = 0x30
CC1101_STX = 0x35
CC1101_SIDLE = 0x36
CC1101_SFTX = 0x3B

# Conservative 433.92 MHz OOK/ASK packet profile for short TD175P alarm frames.
CC1101_CONFIG = {
    CC1101_IOCFG0: 0x06,
    CC1101_FIFOTHR: 0x47,
    CC1101_PKTLEN: 0x04,
    CC1101_PKTCTRL1: 0x04,
    CC1101_PKTCTRL0: 0x00,
    CC1101_FSCTRL1: 0x06,
    CC1101_FREQ2: 0x10,
    CC1101_FREQ1: 0xB0,
    CC1101_FREQ0: 0x71,
    CC1101_MDMCFG4: 0xF5,
    CC1101_MDMCFG3: 0x83,
    CC1101_MDMCFG2: 0x30,
    CC1101_DEVIATN: 0x15,
    CC1101_MCSM0: 0x18,
    CC1101_FOCCFG: 0x16,
    CC1101_BSCFG: 0x6C,
    CC1101_AGCCTRL2: 0x03,
    CC1101_AGCCTRL1: 0x40,
    CC1101_AGCCTRL0: 0x91,
    CC1101_FREND0: 0x11,
    CC1101_FSCAL3: 0xE9,
    CC1101_FSCAL2: 0x2A,
    CC1101_FSCAL1: 0x00,
    CC1101_FSCAL0: 0x1F,
    CC1101_TEST2: 0x81,
    CC1101_TEST1: 0x35,
    CC1101_TEST0: 0x09,
}


def pager_bcd(pager: int) -> int:
    if not 1 <= pager <= 30:
        raise ValueError("Pagernummer muss zwischen 1 und 30 liegen.")
    return ((pager // 10) << 4) | (pager % 10)


def payload_for(pager: int) -> list[int]:
    return [pager_bcd(pager), 0x00, 0x92, 0x02]


def strobe(spi: spidev.SpiDev, command: int) -> None:
    spi.xfer2([command])


def write_register(spi: spidev.SpiDev, address: int, value: int) -> None:
    spi.xfer2([address, value & 0xFF])


def configure_radio(spi: spidev.SpiDev, power: int) -> None:
    strobe(spi, CC1101_SRES)
    time.sleep(0.01)
    for address, value in CC1101_CONFIG.items():
        write_register(spi, address, value)
    spi.xfer2([CC1101_PATABLE | 0x40, power & 0xFF])


def send_once(spi: spidev.SpiDev, payload: list[int]) -> None:
    strobe(spi, CC1101_SIDLE)
    strobe(spi, CC1101_SFTX)
    spi.xfer2([CC1101_TXFIFO | 0x40, *payload])
    strobe(spi, CC1101_STX)
    time.sleep(0.025)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pager", type=int, help="TD175P-Pagernummer 1-30")
    parser.add_argument("--gpio", type=int, default=24, help="GDO0-Pin (BCM); wird zur Initialisierung gesetzt")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--power", type=lambda value: int(value, 0), default=0xC0)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--no-invert", action="store_true", help="Kompatibilitätsoption; CC1101-Profil bleibt unverändert")
    parser.add_argument("--yes", action="store_true", help="Bestätigt bewusstes Senden")
    args = parser.parse_args()

    if not args.yes:
        parser.error("Senden muss mit --yes bestätigt werden.")
    payload = payload_for(args.pager)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.gpio, GPIO.IN)
    spi = spidev.SpiDev()
    spi.open(args.spi_bus, args.spi_device)
    spi.max_speed_hz = 500_000
    spi.mode = 0
    try:
        configure_radio(spi, args.power)
        for _ in range(max(1, args.repeats)):
            send_once(spi, payload)
            time.sleep(0.08)
    finally:
        strobe(spi, CC1101_SIDLE)
        spi.close()
        GPIO.cleanup(args.gpio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
