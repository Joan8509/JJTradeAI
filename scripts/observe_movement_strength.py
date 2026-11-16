"""Independent observation process; never imports execution or sends notices."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from movement_strength_store import capture, DEFAULT_ARCHIVE
from market_store import DEFAULT_MARKET_DATABASE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(DEFAULT_MARKET_DATABASE))
    parser.add_argument('--archive', default=str(DEFAULT_ARCHIVE))
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    # One observer per archive; Windows releases lock on process termination.
    import msvcrt
    Path(args.archive).parent.mkdir(parents=True, exist_ok=True)
    with open(str(args.archive)+'.lock', 'a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        while True:
            try:
                capture(args.source, args.archive)
            except Exception as error:
                # No secrets/provider payloads in observer errors.
                print('STRENGTH_OBSERVER_RETRY '+type(error).__name__, flush=True)
            if args.once:
                break
            time.sleep(5)


if __name__ == '__main__':
    main()
