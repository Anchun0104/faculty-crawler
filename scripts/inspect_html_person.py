from __future__ import annotations

import argparse
import gzip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    with gzip.open(args.snapshot, "rb") as handle:
        html = handle.read().decode("utf-8", errors="replace")
    lowered = html.casefold()
    for name in args.names:
        position = lowered.find(name.casefold())
        print(f"===== {name} @ {position} =====")
        if position >= 0:
            print(html[max(0, position - 800):position + 1600])


if __name__ == "__main__":
    main()
