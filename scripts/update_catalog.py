"""Refresh the bundled snapshot without installing AstrBot."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import BUNDLED_PATH, CatalogStore, atomic_save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BUNDLED_PATH)
    args = parser.parse_args()
    # Reuse runtime validation, including protections against incomplete pages.
    import asyncio
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        store = CatalogStore(Path(directory) / "catalog.json")
        result = asyncio.run(store.refresh())
        if store.last_error:
            raise SystemExit(store.last_error)
        atomic_save(args.output, store.data)
        print(result)


if __name__ == "__main__":
    main()
