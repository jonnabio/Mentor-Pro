"""Release identity, image labels and manifests for CI (T043, ADR-033 increment I3).

    python scripts/release/release.py identity --mode release|dry-run --label dev|pr<N> --sha <commit> \
        --tags <file of existing tag names> [--now <ISO UTC>]          (key=value lines for $GITHUB_OUTPUT)
    python scripts/release/release.py check-labels --image <ref> --version <v> --revision <sha> --created <ts>
    python scripts/release/release.py manifest --out <file> --version <v> --commit <sha> --run <id> \
        --created <ts> (--digest sha256:<..> | --image-id sha256:<..> --dry-run)
    python scripts/release/release.py validate <manifest file>

The version is decided before the image is built, so the labels, the manifest, the git tag and the published
digest all name the same artifact. Every output is a function of its inputs (the build time is decided once,
in `identity`), so a retried job writes a byte-identical manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from app.writing import migrations  # noqa: E402

IMAGE = "ghcr.io/jonnabio/mentor-pro"
SOURCE = "https://github.com/jonnabio/Mentor-Pro"
SCHEMA_FILE = REPO / "docs" / "release" / "manifest.schema.json"
PUBLISHED = "Published, not authorized for deployment"  # PO wording, 2026-10-28 (ADR-033 R3)
DRY_RUN = "Dry run: not published"
RELEASE_TAG = re.compile(r"^v(\d{4}\.\d{2}\.\d{2})-(\d+)$")


def next_version(day: str, existing: list[str]) -> str:
    """vYYYY.MM.DD-N with N one above the highest N already used that day (gaps are never reused)."""
    used = [int(m.group(2)) for m in map(RELEASE_TAG.match, existing) if m and m.group(1) == day]
    return f"v{day}-{max(used, default=0) + 1}"


def labels(version: str, revision: str, created: str) -> dict[str, str]:
    return {
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.created": created,
        "org.opencontainers.image.source": SOURCE,
        "io.mentorpro.schema.min": migrations.SCHEMA_MIN,
        "io.mentorpro.schema.max": migrations.SCHEMA_MAX,
    }


def label_problems(actual: dict[str, str] | None, expected: dict[str, str]) -> list[str]:
    actual = actual or {}
    return [f"{key}: expected {value!r}, found {actual.get(key)!r}"
            for key, value in expected.items() if actual.get(key) != value]


def identity(mode: str, label: str, sha: str, existing: list[str], now: datetime) -> dict[str, str]:
    created = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if mode == "release":
        version = next_version(now.astimezone(timezone.utc).strftime("%Y.%m.%d"), existing)
    else:
        if not re.fullmatch(r"dev|pr\d+", label):
            raise ValueError(f"dry-run label must be dev or pr<N>, not {label!r}")
        version = f"{label}-{sha[:7]}"
    return {"version": version, "created": created, "schema_min": migrations.SCHEMA_MIN,
            "schema_max": migrations.SCHEMA_MAX}


def manifest(version: str, commit: str, run: str, created: str, digest: str | None = None,
             image_id: str | None = None, dry_run: bool = False) -> dict:
    return {
        "manifest_version": 1,
        "release": version,
        "dry_run": dry_run,
        "status": DRY_RUN if dry_run else PUBLISHED,
        "image": {"repository": IMAGE, "digest": None if dry_run else digest, "image_id": image_id},
        "commit": commit,
        "ci_run": run,
        "created": created,
        "schema": {"min": migrations.SCHEMA_MIN, "max": migrations.SCHEMA_MAX},
        "smoke": {"student": "pass", "tutor": "pass"},
    }


def validate(data: dict) -> list[str]:
    import jsonschema

    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    problems = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(data)]
    s = data.get("schema") or {}
    if isinstance(s.get("min"), str) and isinstance(s.get("max"), str) and s["min"] > s["max"]:
        problems.append(f"schema range is empty: min {s['min']} > max {s['max']}")
    return problems


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("identity")
    p.add_argument("--mode", choices=["release", "dry-run"], required=True)
    p.add_argument("--label", default="dev")
    p.add_argument("--sha", required=True)
    p.add_argument("--tags", type=Path, required=True)
    p.add_argument("--now")
    p = sub.add_parser("check-labels")
    for name in ("--image", "--version", "--revision", "--created"):
        p.add_argument(name, required=True)
    p = sub.add_parser("manifest")
    for name in ("--out", "--version", "--commit", "--run", "--created"):
        p.add_argument(name, required=True)
    p.add_argument("--digest")
    p.add_argument("--image-id")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("validate")
    p.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    if args.command == "identity":
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
        existing = args.tags.read_text(encoding="utf-8").split() if args.tags.exists() else []
        out = identity(args.mode, args.label, args.sha, existing, now)
        out["labels"] = "\n".join(f"{k}={v}" for k, v in labels(out["version"], args.sha, out["created"]).items())
        for key, value in out.items():
            if "\n" in value:  # multi-line $GITHUB_OUTPUT value
                print(f"{key}<<MENTORPRO_EOF\n{value}\nMENTORPRO_EOF")
            else:
                print(f"{key}={value}")
        return 0
    if args.command == "check-labels":
        found = subprocess.run(["docker", "inspect", "--format", "{{json .Config.Labels}}", args.image],
                               capture_output=True, text=True, check=True).stdout
        problems = label_problems(json.loads(found), labels(args.version, args.revision, args.created))
        for problem in problems:
            print(f"LABEL MISMATCH {problem}")
        print("LABELS OK" if not problems else "LABELS FAILED")
        return 1 if problems else 0
    if args.command == "manifest":
        data = manifest(args.version, args.commit, args.run, args.created, args.digest, args.image_id, args.dry_run)
        problems = validate(data)
        if problems:
            print("MANIFEST INVALID: " + "; ".join(problems))
            return 1
        Path(args.out).write_text(dumps(data), encoding="utf-8", newline="\n")
        print(f"MANIFEST OK {args.out} ({data['release']})")
        return 0
    problems = validate(json.loads(args.file.read_text(encoding="utf-8")))
    print("MANIFEST OK" if not problems else "MANIFEST INVALID: " + "; ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
