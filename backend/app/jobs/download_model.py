"""Download the SigLIP 2 checkpoint into models/ once (the API never downloads weights)."""
import argparse
import json

from huggingface_hub import snapshot_download

from ..config import get_settings

DEFAULT_REPO = "google/siglip2-base-patch16-224"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--revision", default="main")
    args = parser.parse_args(argv)
    target = get_settings().model_dir
    path = snapshot_download(args.repo, revision=args.revision, local_dir=target,
                             allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt"])
    info = {"repo": args.repo, "revision": args.revision, "path": str(path)}
    (target / "MODEL_SOURCE.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
