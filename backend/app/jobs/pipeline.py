"""Run the whole offline pipeline: import -> download -> embed -> relations -> finalize -> ONNX export."""
import argparse

from ..config import get_settings
from . import download, embed, export_onnx, finalize, import_csv, relations_import


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--limit", type=int, help="process at most N new images (smoke test)")
    args = parser.parse_args(argv)
    limit = ["--limit", str(args.limit)] if args.limit else []
    steps = [
        ("import", lambda: import_csv.main([])),
        ("download", lambda: 0 if args.skip_download else download.main(limit)),
        ("embed", lambda: embed.main(limit)),
        ("relations", lambda: relations_import.main([])),
        ("finalize", lambda: finalize.main([])),
        ("export_onnx", lambda: 0 if get_settings().encoder_backend == "hash" else export_onnx.main([])),
    ]
    for name, step in steps:
        print(f"=== {name} ===", flush=True)
        code = step()
        if code not in (0, None):
            print(f"step {name} failed with exit code {code}")
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
