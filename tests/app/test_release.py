"""Release identity, labels, manifests and the CI release rules (T043, ADR-033 increment I3).

No network, registry or Docker: the helpers are pure functions, and the workflow is checked as text for the
rules that must never regress (publication only on pushes to main, least privilege, mandatory Docker tests).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.writing import migrations

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "release"))
import release  # noqa: E402

WORKFLOW = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
SHA = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 11, 2, 15, 4, 5, tzinfo=timezone.utc)


# ------------------------------------------------------------------ schema range in code

def test_schema_range_follows_the_migrations():
    numbers = [m.split("_", 1)[0] for m in migrations.MIGRATIONS]
    assert numbers == sorted(numbers) and migrations.MIGRATIONS[0] == migrations.STUDENT_ATTEMPTS
    assert migrations.SCHEMA_MAX == numbers[-1]
    assert migrations.SCHEMA_MIN in numbers and migrations.SCHEMA_MIN <= migrations.SCHEMA_MAX


def test_migrate_range_needs_no_database():
    env = {"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}  # no DATABASE_URL at all
    out = subprocess.run([sys.executable, "-m", "app.writing.migrate", "range"], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == {"min": migrations.SCHEMA_MIN, "max": migrations.SCHEMA_MAX}


# ------------------------------------------------------------------ version allocation

@pytest.mark.parametrize("existing, expected", [
    ([], "v2026.11.02-1"),
    (["v2026.11.02-1"], "v2026.11.02-2"),
    (["v2026.11.02-1", "v2026.11.02-3"], "v2026.11.02-4"),  # a burned or missing number is never reused
    (["v2026.11.01-7", "v0.1.0", "v2026.11.02-x", "testing"], "v2026.11.02-1"),  # other days and names ignored
])
def test_next_version(existing, expected):
    assert release.next_version("2026.11.02", existing) == expected


def test_identity_release_and_dry_run():
    out = release.identity("release", "dev", SHA, ["v2026.11.02-1"], NOW)
    assert out == {"version": "v2026.11.02-2", "created": "2026-11-02T15:04:05Z",
                   "schema_min": migrations.SCHEMA_MIN, "schema_max": migrations.SCHEMA_MAX}
    assert release.identity("dry-run", "pr19", SHA, [], NOW)["version"] == "pr19-0123456"
    assert release.identity("dry-run", "dev", SHA, ["v2026.11.02-1"], NOW)["version"] == "dev-0123456"
    with pytest.raises(ValueError):
        release.identity("dry-run", "main", SHA, [], NOW)


def test_identity_cli_writes_github_output(tmp_path):
    tags = tmp_path / "tags.txt"
    tags.write_text("v2026.11.02-1\nv0.1.0\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "release" / "release.py"), "identity", "--mode",
                          "release", "--sha", SHA, "--tags", str(tags), "--now", "2026-11-02T15:04:05Z"],
                         capture_output=True, text=True, check=True).stdout
    assert "version=v2026.11.02-2\n" in out and "created=2026-11-02T15:04:05Z\n" in out
    block = re.search(r"labels<<MENTORPRO_EOF\n(.*?)\nMENTORPRO_EOF", out, re.S).group(1).splitlines()
    assert "org.opencontainers.image.version=v2026.11.02-2" in block
    assert f"io.mentorpro.schema.max={migrations.SCHEMA_MAX}" in block and f"org.opencontainers.image.revision={SHA}" \
        in block


# ------------------------------------------------------------------ labels

def test_labels_carry_the_identity_and_code_schema_range():
    expected = release.labels("v2026.11.02-1", SHA, "2026-11-02T15:04:05Z")
    assert expected["io.mentorpro.schema.min"] == migrations.SCHEMA_MIN
    assert expected["io.mentorpro.schema.max"] == migrations.SCHEMA_MAX
    assert release.label_problems(dict(expected), expected) == []
    wrong = {**expected, "io.mentorpro.schema.max": "0002"}
    del wrong["org.opencontainers.image.revision"]
    problems = release.label_problems(wrong, expected)
    assert len(problems) == 2 and any("schema.max" in p for p in problems)
    assert len(release.label_problems(None, expected)) == len(expected)  # an unlabelled image fails every label


# ------------------------------------------------------------------ manifests

def published():
    return release.manifest("v2026.11.02-1", SHA, "40790275976", "2026-11-02T15:04:05Z", digest=DIGEST)


def test_published_and_dry_run_manifests_are_valid():
    data = published()
    assert release.validate(data) == []
    assert data["status"] == "Published, not authorized for deployment"
    assert data["schema"] == {"min": migrations.SCHEMA_MIN, "max": migrations.SCHEMA_MAX}
    dry = release.manifest("dev-0123456", SHA, "1", "2026-11-02T15:04:05Z", image_id="sha256:" + "b" * 64,
                           dry_run=True)
    assert release.validate(dry) == [] and dry["image"]["digest"] is None and dry["status"] == "Dry run: not published"


@pytest.mark.parametrize("change", [
    lambda m: m.update(status="Published"),  # the PO wording is exact
    lambda m: m["image"].update(digest=None),  # a published release names its digest
    lambda m: m.update(release="dev-0123456"),  # a dry-run name cannot be published
    lambda m: m.update(dry_run=True),  # a dry run cannot carry the published wording or a digest
    lambda m: m.update(commit="abc"),
    lambda m: m["schema"].update(min="0002"),  # empty range
    lambda m: m.update(extra="field"),
    lambda m: m["smoke"].update(tutor="fail"),
])
def test_invalid_manifests_are_rejected(change):
    data = published()
    change(data)
    assert release.validate(data)


def test_manifest_is_byte_identical_on_retry(tmp_path):
    args = ["manifest", "--version", "v2026.11.02-1", "--commit", SHA, "--run", "7", "--created",
            "2026-11-02T15:04:05Z", "--digest", DIGEST]
    assert release.main([*args, "--out", str(tmp_path / "a.json")]) == 0
    assert release.main([*args, "--out", str(tmp_path / "b.json")]) == 0
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    assert release.main(["validate", str(tmp_path / "a.json")]) == 0
    bad = [*args[:-1], "not-a-digest", "--out", str(tmp_path / "c.json")]
    assert release.main(bad) == 1 and not (tmp_path / "c.json").exists()


# ------------------------------------------------------------------ the workflow rules

def job(name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", WORKFLOW, re.M | re.S)
    assert match, name
    return match.group(1)


MAIN_PUSH = "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def test_pull_requests_into_dev_run_ci():
    assert re.search(r"pull_request:\n\s+branches: \[main, dev\]", WORKFLOW)
    assert re.search(r"push:\n\s+branches: \[dev, main\]", WORKFLOW)


def test_main_runs_are_serialized_and_never_cancelled():
    assert "group: ci-${{ github.ref }}" in WORKFLOW
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in WORKFLOW


def test_docker_tests_stay_mandatory_and_all_suites_run():
    tests = job("tests")
    assert 'MENTORPRO_REQUIRE_DOCKER: "1"' in tests
    assert "pytest -q -p no:warnings tests/ace tests/curriculum tests/app" in tests
    assert "validate_skills.py" in tests


def test_publication_and_release_only_on_pushes_to_main():
    build = job("docker-build")
    assert build.count("if: env.RELEASE == 'true'") == 2  # refuse-taken-version and publish
    assert re.search(r"- name: Log in to GitHub Container Registry\n\s+if: " + re.escape(MAIN_PUSH), build)
    assert "release=true" in job("identity") and f'"${{{{ github.ref }}}}" = refs/heads/main' in job("identity")
    assert f"if: {MAIN_PUSH}" in job("release")
    assert WORKFLOW.count("docker push") == 1 and "docker push" in build
    assert WORKFLOW.count("gh release create") == 1 and WORKFLOW.count("git push origin") == 1
    assert "git push --force" not in WORKFLOW and "-f origin" not in WORKFLOW and "git tag -d" not in WORKFLOW


def grants(text, grant):
    """YAML permission lines only, not comments that mention them."""
    return len(re.findall(rf"^\s+{grant}(\s+#.*)?$", text, re.M))


def test_least_privilege():
    assert re.search(r"^permissions:\n  contents: read\n", WORKFLOW, re.M)
    assert grants(WORKFLOW, "contents: write") == 1 and grants(job("release"), "contents: write") == 1
    assert grants(WORKFLOW, "packages: write") == 1 and grants(job("docker-build"), "packages: write") == 1
    assert "packages: read" in job("identity") and "contents: write" not in job("identity")


def test_build_once_with_identity_labels_and_checks():
    build = job("docker-build")
    assert build.count("uses: docker/build-push-action") == 1 and "push: false" in build
    assert "labels: ${{ needs.identity.outputs.labels }}" in build
    order = [build.index(s) for s in ("check-labels", "Smoke test container startup", "Smoke test tutor entrypoint",
                                      "Refuse a version that is already taken", "Publish smoke-tested image")]
    assert order == sorted(order)  # labels checked and both smoke tests passed before anything is published
    assert "upload-artifact" in build and "--dry-run" in build


def test_release_wording_in_the_workflow():
    assert '--notes "Published, not authorized for deployment"' in job("release")
    assert release.PUBLISHED == "Published, not authorized for deployment"
