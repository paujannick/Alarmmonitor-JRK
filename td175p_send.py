def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retekess TD175P Pager 1–30 auslösen"
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
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument(
        "--repeats",
        type=int,
        default=30,
        choices=range(1, 31),
    )
    parser.add_argument(
        "--power",
        type=lambda value: int(value, 0),
        default=0x12,
        help="CC1101 PATABLE-Wert; Standard 0x12",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Bestätigungsfrage überspringen",
    )

    args = parser.parse_args()

    try:
        send_pager(args)
        return 0
    except (ValueError, RuntimeError, TimeoutError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
