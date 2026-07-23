#!/usr/bin/env python3
"""Importierbare TD175P-Funkbibliothek für Raspberry Pi und CC1101.

Bestätigte Rufstruktur:
    Pager 1..30 -> [BCD-Adresse niedrig, BCD-Adresse hoch, 0x92, 0x02]

Der Sonderruf 999 wird nach demselben dreistelligen BCD-Schema als
    0x99 0x09 0x92 0x02
übertragen. Dieser Abschaltbefehl muss am realen System noch bestätigt werden.
"""

from __future__ import annotations

import argparse
import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Final

try:
    import pigpio
except ImportError:  # Import der Bibliothek bleibt ohne Hardwarepakete möglich.
    pigpio = None  # type: ignore[assignment]

try:
    import spidev
except ImportError:
    spidev = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)

PAGER_MIN: Final = 1
PAGER_MAX: Final = 30
POWER_OFF_ALL: Final = 999

# CC1101-Konfigurationsregister
IOCFG2: Final = 0x00
IOCFG1: Final = 0x01
IOCFG0: Final = 0x02
FIFOTHR: Final = 0x03
PKTCTRL1: Final = 0x07
PKTCTRL0: Final = 0x08
FSCTRL1: Final = 0x0B
FSCTRL0: Final = 0x0C
FREQ2: Final = 0x0D
FREQ1: Final = 0x0E
FREQ0: Final = 0x0F
MDMCFG4: Final = 0x10
MDMCFG3: Final = 0x11
MDMCFG2: Final = 0x12
MDMCFG1: Final = 0x13
MDMCFG0: Final = 0x14
DEVIATN: Final = 0x15
MCSM2: Final = 0x16
MCSM1: Final = 0x17
MCSM0: Final = 0x18
FOCCFG: Final = 0x19
BSCFG: Final = 0x1A
AGCCTRL2: Final = 0x1B
AGCCTRL1: Final = 0x1C
AGCCTRL0: Final = 0x1D
FREND1: Final = 0x21
FREND0: Final = 0x22
FSCAL3: Final = 0x23
FSCAL2: Final = 0x24
FSCAL1: Final = 0x25
FSCAL0: Final = 0x26
TEST2: Final = 0x2C
TEST1: Final = 0x2D
TEST0: Final = 0x2E
PATABLE: Final = 0x3E

# CC1101-Statusregister
PARTNUM: Final = 0x30
VERSION: Final = 0x31
MARCSTATE: Final = 0x35

# CC1101-Kommandos
SRES: Final = 0x30
SCAL: Final = 0x33
STX: Final = 0x35
SIDLE: Final = 0x36
SFTX: Final = 0x3B

READ_BURST: Final = 0xC0
WRITE_BURST: Final = 0x40
MARCSTATE_TX: Final = 0x13


class TD175PError(RuntimeError):
    """Basisklasse für Fehler der Pageransteuerung."""


class HardwareUnavailableError(TD175PError):
    """Benötigte Hardware oder Systembibliothek ist nicht verfügbar."""


class RadioStateError(TD175PError):
    """Der CC1101 erreicht nicht den erwarteten Zustand."""


@dataclass(frozen=True, slots=True)
class TD175PTiming:
    """Gemessene Pulszeiten des TD175P in Mikrosekunden."""

    one_high_us: int = 640
    one_low_us: int = 195
    zero_high_us: int = 220
    zero_low_us: int = 615
    trailer_high_us: int = 220
    frame_gap_us: int = 6680
    repeats: int = 30

    def __post_init__(self) -> None:
        if not 1 <= self.repeats <= 30:
            raise ValueError("Wiederholungszahl muss zwischen 1 und 30 liegen.")


@dataclass(frozen=True, slots=True)
class TD175PConfig:
    """Hardwarekonfiguration der bestätigten Raspberry-Pi-Anbindung."""

    gpio: int = 24
    spi_bus: int = 0
    spi_device: int = 0
    spi_speed_hz: int = 4_000_000
    power: int = 0xC0
    tx_timeout_s: float = 2.0
    pigpio_host: str | None = None
    pigpio_port: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.gpio <= 31:
            raise ValueError("Ungültiger BCM-GPIO.")
        if not 0 <= self.power <= 0xFF:
            raise ValueError("PATABLE-Leistung muss zwischen 0x00 und 0xFF liegen.")
        if self.tx_timeout_s <= 0:
            raise ValueError("TX-Timeout muss größer als null sein.")


def validate_pager_command(pager: int) -> int:
    """Erlaubt Pager 1..30 und den Sonderbefehl 999."""

    if PAGER_MIN <= pager <= PAGER_MAX or pager == POWER_OFF_ALL:
        return pager
    raise ValueError("Erlaubt sind Pagernummern 1 bis 30 oder 999 zum Ausschalten.")


def encode_bcd_address(pager: int) -> bytes:
    """Codiert eine bis zu dreistellige Adresse in zwei BCD-Bytes.

    Die unteren beiden Dezimalstellen stehen im ersten Byte. Die
    Hunderterstelle steht im unteren Nibble des zweiten Bytes.
    """

    validate_pager_command(pager)
    low = (((pager // 10) % 10) << 4) | (pager % 10)
    high = (pager // 100) & 0x0F
    return bytes((low, high))


def payload_for(pager: int) -> bytes:
    """Erzeugt das vier Byte lange TD175P-Telegramm."""

    return encode_bcd_address(pager) + bytes((0x92, 0x02))


def bits_lsb_first(payload: bytes) -> tuple[int, ...]:
    """Gibt jedes Byte in der gemessenen LSB-first-Reihenfolge zurück."""

    return tuple(
        (byte >> bit_position) & 1
        for byte in payload
        for bit_position in range(8)
    )


def pulse_durations(payload: bytes, timing: TD175PTiming) -> tuple[tuple[int, int], ...]:
    """Erzeugt die HIGH-/LOW-Dauer jedes Nutzbits für Tests und Diagnose."""

    return tuple(
        (
            timing.one_high_us if bit else timing.zero_high_us,
            timing.one_low_us if bit else timing.zero_low_us,
        )
        for bit in bits_lsb_first(payload)
    )


class _CC1101:
    """Kleiner interner CC1101-Treiber für asynchrones OOK."""

    def __init__(self, config: TD175PConfig) -> None:
        if spidev is None:
            raise HardwareUnavailableError(
                "Python-Paket spidev fehlt. Installiere python3-spidev."
            )
        self._spi = spidev.SpiDev()
        self._spi.open(config.spi_bus, config.spi_device)
        self._spi.max_speed_hz = config.spi_speed_hz
        self._spi.mode = 0

    def close(self) -> None:
        self._spi.close()

    def strobe(self, command: int) -> int:
        return self._spi.xfer2([command])[0]

    def write(self, address: int, value: int) -> None:
        self._spi.xfer2([address & 0x3F, value & 0xFF])

    def write_burst(self, address: int, values: list[int]) -> None:
        self._spi.xfer2([(address & 0x3F) | WRITE_BURST, *values])

    def read_status(self, address: int) -> int:
        return self._spi.xfer2([(address & 0x3F) | READ_BURST, 0x00])[1]

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

        # OOK: Index 0 ist aus, FREND0=0x11 nutzt Index 1 für HIGH.
        self.write_burst(PATABLE, [0x00, power & 0xFF])


class TD175PSender:
    """Synchroner, threadsicherer Sender.

    Für Flask-Requests vorzugsweise über :class:`TD175PService` verwenden.
    """

    def __init__(
        self,
        config: TD175PConfig | None = None,
        timing: TD175PTiming | None = None,
    ) -> None:
        self.config = config or TD175PConfig()
        self.timing = timing or TD175PTiming()
        self._pi = None
        self._radio: _CC1101 | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._pi is not None and self._radio is not None

    def open(self) -> None:
        with self._lock:
            self._open_unlocked()

    def _open_unlocked(self) -> None:
        if self.is_open:
            return
        if pigpio is None:
            raise HardwareUnavailableError(
                "Python-Paket pigpio fehlt. Installiere python3-pigpio."
            )

        if self.config.pigpio_host is None:
            pi = pigpio.pi()
        elif self.config.pigpio_port is None:
            pi = pigpio.pi(self.config.pigpio_host)
        else:
            pi = pigpio.pi(self.config.pigpio_host, self.config.pigpio_port)

        if not pi.connected:
            pi.stop()
            raise HardwareUnavailableError(
                "pigpiod ist nicht erreichbar. Starte: "
                "sudo systemctl enable --now pigpiod"
            )

        radio: _CC1101 | None = None
        try:
            radio = _CC1101(self.config)
            radio.reset()
            part = radio.read_status(PARTNUM)
            version = radio.read_status(VERSION)
            if part != 0x00 or version != 0x14:
                raise HardwareUnavailableError(
                    f"Unerwarteter CC1101: PARTNUM=0x{part:02X}, "
                    f"VERSION=0x{version:02X}"
                )

            pi.set_mode(self.config.gpio, pigpio.OUTPUT)
            pi.write(self.config.gpio, 0)
            radio.configure_async_ook(self.config.power)
        except Exception:
            if radio is not None:
                radio.close()
            pi.write(self.config.gpio, 0)
            pi.stop()
            raise

        self._pi = pi
        self._radio = radio
        LOGGER.info(
            "TD175P-Sender bereit: GPIO%d, SPI%d.%d, Leistung 0x%02X",
            self.config.gpio,
            self.config.spi_bus,
            self.config.spi_device,
            self.config.power,
        )

    def close(self) -> None:
        with self._lock:
            if self._pi is not None:
                self._pi.wave_tx_stop()
                self._pi.write(self.config.gpio, 0)
            if self._radio is not None:
                self._radio.strobe(SIDLE)
                self._radio.close()
            if self._pi is not None:
                self._pi.stop()
            self._radio = None
            self._pi = None

    def __enter__(self) -> "TD175PSender":
        self.open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def _build_wave_unlocked(self, payload: bytes) -> int:
        assert self._pi is not None
        mask = 1 << self.config.gpio
        pulses = []

        for _ in range(self.timing.repeats):
            for high_us, low_us in pulse_durations(payload, self.timing):
                pulses.append(pigpio.pulse(mask, 0, high_us))
                pulses.append(pigpio.pulse(0, mask, low_us))
            pulses.append(pigpio.pulse(mask, 0, self.timing.trailer_high_us))
            pulses.append(pigpio.pulse(0, mask, self.timing.frame_gap_us))

        self._pi.wave_clear()
        added = self._pi.wave_add_generic(pulses)
        if added < 0:
            raise TD175PError(f"pigpio konnte die Pulse nicht übernehmen: {added}")
        wave_id = self._pi.wave_create()
        if wave_id < 0:
            raise TD175PError(f"pigpio konnte die Sendewelle nicht erzeugen: {wave_id}")
        return wave_id

    def send(self, pager: int) -> None:
        """Sendet an Pager 1..30 oder mit 999 den Abschaltbefehl."""

        validate_pager_command(pager)
        with self._lock:
            self._open_unlocked()
            assert self._pi is not None
            assert self._radio is not None

            payload = payload_for(pager)
            wave_id = -1
            started = time.monotonic()
            LOGGER.info(
                "Sende TD175P-Befehl %d, Nutzdaten %s",
                pager,
                payload.hex(" ").upper(),
            )

            try:
                self._pi.write(self.config.gpio, 0)
                self._radio.strobe(SIDLE)
                self._radio.strobe(SFTX)
                self._radio.strobe(SCAL)
                time.sleep(0.002)

                wave_id = self._build_wave_unlocked(payload)
                self._radio.strobe(STX)
                if not self._radio.wait_state(MARCSTATE_TX):
                    raise RadioStateError("CC1101 erreicht den TX-Zustand nicht.")

                self._pi.wave_send_once(wave_id)
                deadline = time.monotonic() + self.config.tx_timeout_s
                while self._pi.wave_tx_busy():
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "TD175P-Sendung wurde nach dem TX-Timeout abgebrochen."
                        )
                    time.sleep(0.005)
            finally:
                self._pi.wave_tx_stop()
                self._radio.strobe(SIDLE)
                self._pi.write(self.config.gpio, 0)
                if wave_id >= 0:
                    self._pi.wave_delete(wave_id)

            LOGGER.info(
                "TD175P-Befehl %d nach %.3f s abgeschlossen",
                pager,
                time.monotonic() - started,
            )

    def power_off_all(self) -> None:
        """Sendet den Retekess-Sonderruf 999."""

        self.send(POWER_OFF_ALL)


@dataclass(frozen=True, slots=True)
class PagerJobResult:
    pager: int
    started_at: float
    finished_at: float

    @property
    def duration_s(self) -> float:
        return self.finished_at - self.started_at


class TD175PService:
    """Nicht blockierende Einzel-Queue für die Leitstellensoftware."""

    _STOP = object()

    def __init__(self, sender: TD175PSender | None = None, queue_size: int = 100) -> None:
        self.sender = sender or TD175PSender()
        self._queue: queue.Queue[tuple[int, Future[PagerJobResult]] | object] = (
            queue.Queue(maxsize=queue_size)
        )
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="td175p-pager-worker",
                daemon=True,
            )
            self._thread.start()

    def submit(self, pager: int) -> Future[PagerJobResult]:
        """Plant den Befehl ein und kehrt sofort zurück."""

        validate_pager_command(pager)
        self.start()
        future: Future[PagerJobResult] = Future()
        try:
            self._queue.put_nowait((pager, future))
        except queue.Full as exc:
            raise TD175PError("Pager-Warteschlange ist voll.") from exc
        return future

    def power_off_all(self) -> Future[PagerJobResult]:
        return self.submit(POWER_OFF_ALL)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                pager, future = item
                if not future.set_running_or_notify_cancel():
                    continue
                started = time.time()
                try:
                    self.sender.send(pager)
                except BaseException as exc:
                    future.set_exception(exc)
                    LOGGER.exception("TD175P-Befehl %d fehlgeschlagen", pager)
                else:
                    future.set_result(
                        PagerJobResult(
                            pager=pager,
                            started_at=started,
                            finished_at=time.time(),
                        )
                    )
            finally:
                self._queue.task_done()

    def stop(self, wait: bool = True) -> None:
        with self._state_lock:
            thread = self._thread
            if thread is None:
                self.sender.close()
                return
            self._queue.put(self._STOP)
        if wait:
            thread.join(timeout=5.0)
        self.sender.close()
        with self._state_lock:
            self._thread = None

    def __enter__(self) -> "TD175PService":
        self.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.stop()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="TD175P-Bibliothek manuell testen (Pager 1–30 oder 999)"
    )
    parser.add_argument("pager", type=int)
    parser.add_argument("--gpio", type=int, default=24)
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--power", type=lambda value: int(value, 0), default=0x60)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    try:
        validate_pager_command(args.pager)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.yes:
        parser.error("Bewusstes Senden muss mit --yes bestätigt werden.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sender = TD175PSender(
        config=TD175PConfig(
            gpio=args.gpio,
            spi_bus=args.spi_bus,
            spi_device=args.spi_device,
            power=args.power,
        ),
        timing=TD175PTiming(repeats=args.repeats),
    )
    try:
        sender.send(args.pager)
    finally:
        sender.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
