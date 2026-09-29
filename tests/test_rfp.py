import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from rfp.core import (BANNER, KnowledgeBase, SchemaError, VersionError, StorageError,
                      TenderError, dumps, fixtures, ingest, map_requirements, gaps, draft, report)

AS_OF = "2026-09-29"

@pytest.fixture
def sample(tmp_path):
    fixtures(tmp_path)
    return tmp_path

@pytest.fixture
def fact(sample):
    return json.loads((sample / "kb-entries.json").read_text())[0]

def mapped(sample, name="covered.md"):
    reqs = ingest((sample / name).read_text())
    return map_requirements(reqs, KnowledgeBase(sample / "kb.json").latest(), AS_OF)

def cli(*args):
    return subprocess.run([sys.executable, "-m", "rfp", *map(str, args)], capture_output=True, text=True)

def test_immutable_versions(tmp_path, fact):
    kb = KnowledgeBase(tmp_path / "new.json")
    original = kb.add(fact)
    changed = dict(fact, statement="SYNTHETIC: Updated delivery implementation statement.")
    newer = kb.add(changed, update=True)
    assert original["version"] == 1 and newer["version"] == 2
    assert kb.entries() == [original, newer]
    assert kb.latest() == [newer]
    fact["statement"] = "caller mutation"
    newer["statement"] = "caller mutation"
    assert kb.entries()[0] == original
    assert kb.entries()[1]["statement"] == changed["statement"]

def test_version_errors(tmp_path, fact):
    kb = KnowledgeBase(tmp_path / "new.json")
    with pytest.raises(VersionError):
        kb.add(fact, update=True)
    kb.add(fact)
    with pytest.raises(VersionError):
        kb.add(fact)

@pytest.mark.parametrize("key,value", [
    ("id", ""), ("id", "bad id"), ("statement", None), ("source_reference", " "),
    ("category", "unknown"), ("date_verified", "2026-02-30"),
    ("date_verified", 2026), ("expiry", "2020-01-01"), ("expiry", "tomorrow"),
    ("keywords", []), ("keywords", ["two words"]), ("keywords", [3]),
    ("statement", "forbidden " + chr(8212)),
])
def test_schema_errors(tmp_path, fact, key, value):
    fact[key] = value
    with pytest.raises(SchemaError):
        KnowledgeBase(tmp_path / "new.json").add(fact)
    assert not (tmp_path / "new.json").exists()

@pytest.mark.parametrize("entry", [None, [], {}, {"extra": "value"}])
def test_missing_schema(tmp_path, entry):
    with pytest.raises(SchemaError):
        KnowledgeBase(tmp_path / "new.json").add(entry)

@pytest.mark.parametrize("content", ["not json", "{}", '[{"id":"broken"}]', '[null]'])
def test_corrupt_storage(tmp_path, content):
    path = tmp_path / "corrupt.json"
    path.write_text(content)
    with pytest.raises(StorageError):
        KnowledgeBase(path).entries()

def test_corrupt_version(sample):
    path = sample / "kb.json"
    entries = json.loads(path.read_text())
    entries[0]["version"] = 4
    path.write_text(dumps(entries))
    with pytest.raises(StorageError):
        KnowledgeBase(path).entries()

@pytest.mark.parametrize("name,count", [("covered.md", 3), ("gaps.md", 6)])
def test_ingest_fixtures(sample, name, count):
    requirements = ingest((sample / name).read_text())
    assert [r["number"] for r in requirements] == [str(n) for n in range(1, count + 1)]
    assert requirements[0] == {"number": "1", "section": "Delivery", "text": "Describe delivery and implementation."}
    assert requirements[1]["section"] == "Assurance"
    assert requirements[2]["section"] == "Track record"

def test_plain_text_and_continuation():
    assert ingest("1) First requirement\ncontinued\n2. Second") == [
        {"number": "1", "section": "General", "text": "First requirement continued"},
        {"number": "2", "section": "General", "text": "Second"}]
    assert ingest("## Section\n1.2. Nested requirement")[0]["number"] == "1.2"

@pytest.mark.parametrize("text", ["# No requirements", "1. First\n1. Duplicate", "1. Bad " + chr(8212)])
def test_ingest_errors(text):
    with pytest.raises(TenderError):
        ingest(text)

def test_expected_strong_matches(sample):
    mapping = mapped(sample)
    assert [r["candidates"][0]["citation"] for r in mapping] == ["delivery@v1", "security@v1", "experience@v1"]
    assert all(not r["gap"] for r in mapping)
    assert all(r["candidates"][0]["band"] == "strong" for r in mapping)
    assert [r["candidates"][0]["rules"] for r in mapping] == [["delivery"], ["security"], ["experience"]]

def test_all_gap_actions(sample):
    mapping = mapped(sample, "gaps.md")
    assert len(mapping) == 6
    assert mapping[3]["candidates"][0]["band"] == "partial"
    assert all(not any(c["band"] == "strong" for c in r["candidates"]) for r in mapping[3:])
    assert [(g["number"], g["suggested_action"]) for g in gaps(mapping)] == [
        ("4", "add KB entry"), ("5", "mark out of scope"), ("6", "request clarification")]

def test_candidate_ranking_and_weak(sample):
    entries = KnowledgeBase(sample / "kb.json").latest()
    alternate = dict(entries[0], id="aaa", keywords=["delivery", "implementation", "describe"])
    weak = dict(entries[0], id="zzz", category="past_projects")
    partial = dict(entries[0], id="bbb", keywords=["delivery"])
    candidates = map_requirements(ingest("1. Describe delivery and implementation."), entries + [weak, partial, alternate], AS_OF)[0]["candidates"]
    assert [c["citation"] for c in candidates] == ["aaa@v1", "delivery@v1", "bbb@v1", "zzz@v1"]
    assert [c["band"] for c in candidates] == ["strong", "strong", "partial", "weak"]
    assert candidates[-1]["rules"] == ["keyword-overlap"]

@pytest.mark.parametrize("as_of,band", [("2026-09-28", "weak"), ("2026-09-29", "strong"), ("2027-09-29", "strong"), ("2027-09-30", "weak")])
def test_date_eligibility(sample, as_of, band):
    result = map_requirements(ingest("1. Describe security certification."), KnowledgeBase(sample / "kb.json").latest(), as_of)[0]
    assert result["candidates"][0]["band"] == band
    assert result["gap"] == (band != "strong")

@pytest.mark.parametrize("as_of", ["bad", "2026-02-30", None])
def test_invalid_as_of(sample, as_of):
    with pytest.raises(SchemaError):
        map_requirements([], [], as_of)

def test_latest_version_only(sample, fact):
    kb = KnowledgeBase(sample / "kb.json")
    fact["keywords"] = ["retired"]
    kb.add(fact, update=True)
    mapping = mapped(sample)
    assert mapping[0]["gap"]
    assert not mapping[0]["candidates"]

def test_empty_kb_flags_every_requirement(sample):
    reqs = ingest((sample / "gaps.md").read_text())
    mapping = map_requirements(reqs, [], AS_OF)
    assert len(gaps(mapping)) == len(reqs)
    assert draft(mapping).count("UNANSWERED:") == len(reqs)

def test_draft_exact_evidence_and_placeholders(sample):
    mapping = mapped(sample, "gaps.md")
    text = draft(mapping)
    assert text.startswith(BANNER)
    assert text.count("UNANSWERED:") == 3
    for req in mapping:
        block = text.split("## " + req["number"] + ". ")[1].split("\n## ")[0]
        if req["gap"]:
            assert "UNANSWERED:" in block
            assert "[security@v1" not in block
        else:
            for c in req["candidates"]:
                assert c["statement"] + " [" + c["citation"] + "; source: " + c["source_reference"] + "]" in block
    for entry in KnowledgeBase(sample / "kb.json").entries():
        assert entry["statement"] in text
    assert "We guarantee" not in text

@pytest.mark.parametrize("fmt", ["md", "json"])
def test_report_banner_and_coverage(sample, fmt):
    output = report(mapped(sample, "gaps.md"), fmt)
    assert BANNER in output
    for citation in ["delivery@v1", "security@v1", "experience@v1"]:
        assert citation in output
    assert "UNANSWERED" in output
    if fmt == "json":
        data = json.loads(output)
        assert data["coverage"] == {"total": 6, "answered": 3, "gaps": 3}
        assert len(data["mapping"]) == 6 and len(data["gaps"]) == 3

@pytest.mark.parametrize("name", ["covered.md", "gaps.md"])
def test_mapping_and_draft_determinism(sample, name):
    first, second = mapped(sample, name), mapped(sample, name)
    assert dumps(first).encode() == dumps(second).encode()
    assert draft(first).encode() == draft(second).encode()
    assert report(first, "json").encode() == report(second, "json").encode()

def test_fixture_determinism_and_synthetic(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    fixtures(left)
    fixtures(right)
    original = {p.name: p.read_bytes() for p in left.iterdir()}
    assert original == {p.name: p.read_bytes() for p in right.iterdir()}
    fixtures(left)
    assert original == {p.name: p.read_bytes() for p in left.iterdir()}
    for content in original.values():
        assert b"synthetic" in content.lower()
        assert chr(8212).encode() not in content

@pytest.mark.parametrize("command", ["map", "gaps", "draft", "report"])
def test_cli_workflow(sample, command):
    args = ["--kb", sample / "kb.json", command, sample / "gaps.md", "--as-of", AS_OF]
    result = cli(*args)
    assert result.returncode == 0, result.stderr
    assert result.stdout == cli(*args).stdout
    if command in ("draft", "report"):
        assert BANNER in result.stdout
    elif command == "gaps":
        assert len(json.loads(result.stdout)) == 3
    else:
        assert len(json.loads(result.stdout)) == 6

@pytest.mark.parametrize("fmt", ["md", "json"])
def test_cli_report_end_to_end(tmp_path, fmt):
    fixture = cli("fixtures", "--out", tmp_path)
    assert fixture.returncode == 0 and BANNER in fixture.stdout
    result = cli("--kb", tmp_path / "kb.json", "report", tmp_path / "covered.md", "--as-of", AS_OF, "--format", fmt)
    assert result.returncode == 0, result.stderr
    assert BANNER in result.stdout and "UNANSWERED" not in result.stdout
    if fmt == "json":
        assert json.loads(result.stdout)["coverage"] == {"total": 3, "answered": 3, "gaps": 0}

def test_cli_kb_and_ingest(tmp_path, fact):
    source = tmp_path / "entry.json"
    source.write_text(dumps(fact))
    kb = tmp_path / "custom.json"
    assert cli("--kb", kb, "kb-add", source).returncode == 0
    assert json.loads(cli("--kb", kb, "kb-list").stdout)[0]["version"] == 1
    assert cli("--kb", kb, "kb-add", source, "--update").returncode == 0
    assert len(json.loads(cli("--kb", kb, "kb-list").stdout)) == 2
    fixtures(tmp_path / "fixture")
    result = cli("ingest", tmp_path / "fixture" / "gaps.md")
    assert result.returncode == 0 and len(json.loads(result.stdout)) == 6

@pytest.mark.parametrize("mode", ["missing", "malformed", "duplicate", "bad-tender"])
def test_cli_named_errors(sample, tmp_path, mode):
    if mode == "missing":
        result = cli("ingest", tmp_path / "absent.txt")
    elif mode == "malformed":
        file = tmp_path / "malformed.json"
        file.write_text("{")
        result = cli("kb-add", file)
        assert "SchemaError" in result.stderr
    elif mode == "duplicate":
        file = tmp_path / "entry.json"
        file.write_text(dumps(json.loads((sample / "kb-entries.json").read_text())[0]))
        result = cli("--kb", sample / "kb.json", "kb-add", file)
        assert "VersionError" in result.stderr
    else:
        file = tmp_path / "empty.txt"
        file.write_text("Nothing numbered")
        result = cli("ingest", file)
        assert "TenderError" in result.stderr
    assert result.returncode == 2 and result.stdout == ""

def test_no_em_dashes_in_project():
    root = Path(__file__).resolve().parents[1]
    for folder in (root / "rfp", root / "tests"):
        for path in folder.rglob("*.py"):
            assert chr(8212) not in path.read_text(encoding="utf-8")
    assert chr(8212) not in (root / "README.md").read_text(encoding="utf-8")
