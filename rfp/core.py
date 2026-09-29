"""Deterministic storage, parsing, matching, and rendering."""
import json
import re
from datetime import date
from pathlib import Path

BANNER = "HONESTY BOUNDARY: Matches are heuristic keyword/category rules, not semantic understanding. Fixtures are synthetic. This tool assists drafting, does not verify truth, and does not guarantee tender success."
CATEGORIES = ("capabilities", "certifications", "past_projects")
RULES = (
    {"id": "security", "category": "certifications", "keywords": ["security", "certification"], "scope": "in_scope"},
    {"id": "delivery", "category": "capabilities", "keywords": ["delivery", "implementation"], "scope": "in_scope"},
    {"id": "experience", "category": "past_projects", "keywords": ["project", "experience"], "scope": "in_scope"},
    {"id": "orbital", "category": "capabilities", "keywords": ["orbital", "launch"], "scope": "out_of_scope"},
)

class RFPError(ValueError):
    """Base named input error."""
class SchemaError(RFPError):
    """Malformed fact entry."""
class VersionError(RFPError):
    """Invalid version operation."""
class StorageError(RFPError):
    """Corrupt persistent storage."""
class TenderError(RFPError):
    """Malformed tender document."""


def dumps(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def validate(entry):
    if not isinstance(entry, dict):
        raise SchemaError("entry must be an object")
    required = {"id", "statement", "category", "source_reference", "date_verified", "expiry", "keywords"}
    if set(entry) != required:
        raise SchemaError("fields must be exactly: " + ", ".join(sorted(required)))
    for key in ("id", "statement", "source_reference"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise SchemaError(key + " must be nonempty text")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", entry["id"]):
        raise SchemaError("id must contain letters, digits, underscores or hyphens")
    if entry["category"] not in CATEGORIES:
        raise SchemaError("unknown category")
    for key in ("date_verified", "expiry"):
        try:
            if not isinstance(entry[key], str) or date.fromisoformat(entry[key]).isoformat() != entry[key]:
                raise ValueError()
        except ValueError:
            raise SchemaError(key + " must be an ISO date") from None
    if entry["expiry"] < entry["date_verified"]:
        raise SchemaError("expiry precedes date_verified")
    if not isinstance(entry["keywords"], list) or not entry["keywords"] or any(not isinstance(k, str) or not re.fullmatch(r"[a-z0-9]+", k) for k in entry["keywords"]):
        raise SchemaError("keywords must be a nonempty list of lowercase single tokens")
    if any(chr(8212) in str(v) for v in entry.values()):
        raise SchemaError("em dash is prohibited")


class KnowledgeBase:
    def __init__(self, path):
        self.path = Path(path)

    def entries(self):
        if not self.path.exists():
            return []
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, list):
                raise ValueError()
            seen = {}
            for value in values:
                raw = {k: v for k, v in value.items() if k != "version"}
                validate(raw)
                expected = seen.get(value["id"], 0) + 1
                if type(value.get("version")) is not int or value["version"] != expected:
                    raise ValueError("invalid version sequence")
                seen[value["id"]] = expected
            return values
        except (ValueError, TypeError, AttributeError) as exc:
            raise StorageError("invalid knowledge base: " + str(exc)) from exc

    def add(self, entry, update=False):
        validate(entry)
        values = self.entries()
        previous = [v for v in values if v["id"] == entry["id"]]
        if bool(previous) != update:
            raise VersionError("use update for an existing id; new ids cannot be updated")
        value = dict(entry, version=len(previous) + 1)
        values.append(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(dumps(values), encoding="utf-8", newline="\n")
        temporary.replace(self.path)
        return value

    def latest(self):
        result = {}
        for entry in self.entries():
            result[entry["id"]] = entry
        return [result[key] for key in sorted(result)]


def ingest(text):
    section = "General"
    requirements = []
    seen = set()
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        numbered = re.match(r"^(\d+(?:\.\d+)*)[.)]\s+(.+)$", line)
        if heading:
            section = heading.group(1)
            current = None
        elif numbered:
            number, body = numbered.groups()
            if number in seen:
                raise TenderError("duplicate requirement number: " + number)
            seen.add(number)
            current = {"number": number, "section": section, "text": body}
            requirements.append(current)
        elif current:
            current["text"] += " " + line
    if not requirements:
        raise TenderError("no numbered requirements found")
    return requirements


def map_requirements(requirements, entries, as_of):
    try:
        if date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError()
    except (ValueError, TypeError):
        raise SchemaError("as_of must be an ISO date") from None
    result = []
    for req in requirements:
        words = tokens(req["text"])
        fired = [r for r in RULES if words.intersection(r["keywords"])]
        candidates = []
        for entry in entries:
            overlap = sorted(words.intersection(entry["keywords"]))
            if not overlap:
                continue
            compatible = [r for r in fired if r["category"] == entry["category"]]
            valid = entry["date_verified"] <= as_of <= entry["expiry"]
            band = "strong" if compatible and len(overlap) >= 2 and valid else "partial" if compatible and valid else "weak"
            candidates.append({"citation": entry["id"] + "@v" + str(entry["version"]), "statement": entry["statement"], "source_reference": entry["source_reference"], "band": band, "rules": [r["id"] for r in compatible] or ["keyword-overlap"], "overlap": overlap, "date_eligible": valid})
        candidates.sort(key=lambda c: ({"strong": 0, "partial": 1, "weak": 2}[c["band"] , -len(c["overlap"]), c["citation"]))
        strong = any(c["band"] == "strong" for c in candidates)
        action = None if strong else "mark out of scope" if any(r["scope"] == "out_of_scope" for r in fired) else "add KB entry" if fired else "request clarification"
        result.append({**req, "candidates": candidates, "gap": not strong, "suggested_action": action})
    return result


def gaps(mapping):
    return [{"number": r["number"], "text": r["text"], "suggested_action": r["suggested_action"]} for r in mapping if r["gap"]]


def draft(mapping):
    lines = [BANNER, "", "# Draft response workspace", ""]
    for req in mapping:
        lines.extend(["## " + req["number"] + ". " + req["text"], ""])
        if req["gap"]:
            lines.append("UNANSWERED: " + req["suggested_action"] + ". Evidence is insufficient.")
        else:
            for candidate in req["candidates"]:
                if candidate["band"] == "strong":
                    lines.append(candidate["statement"] + " [" + candidate["citation"] + "; source: " + candidate["source_reference"] + "]")
        lines.append("")
    return "\n".join(lines) + "\n"


def report(mapping, fmt):
    data = {"banner": BANNER, "coverage": {"total": len(mapping), "answered": sum(not r["gap"] for r in mapping), "gaps": len(gaps(mapping))}, "mapping": mapping, "gaps": gaps(mapping), "draft": draft(mapping)}
    if fmt == "json":
        return dumps(data)
    if fmt != "md":
        raise SchemaError("report format must be md or json")
    lines = [BANNER, "", "# Coverage report", "", dumps(data["coverage"]).strip(), "", "## Per-requirement mapping", ""]
    for req in mapping:
        lines.append("- " + req["number"] + " (" + req["section"] + "): " + req["text"])
        for c in req["candidates"]:
            lines.append("  - [" + c["citation"] + "] " + c["band"] + "; rules: " + ", ".join(c["rules"]) + "; source: " + c["source_reference"])
        if req["gap"]:
            lines.append("  - GAP: " + req["suggested_action"])
    lines.extend(["", "## Gap list", "", dumps(data["gaps"]).strip(), "", data["draft"]])
    return "\n".join(lines) + "\n"


def fixtures(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for identity, category, statement, keywords in (
        ("delivery", "capabilities", "SYNTHETIC: Fictional Example Workshop provides delivery and implementation support.", ["delivery", "implementation"]),
        ("security", "certifications", "SYNTHETIC: Fictional Example Workshop holds the fictional Sample Security certification.", ["security", "certification"]),
        ("experience", "past_projects", "SYNTHETIC: Fictional Example Workshop completed the fictional Sample project as evidence of experience.", ["project", "experience"]),
    ):
        entries.append({"id": identity, "category": category, "statement": statement, "keywords": keywords, "source_reference": "synthetic-record:" + identity, "date_verified": "2026-09-29", "expiry": "2027-09-29"})
    (out / "kb-entries.json").write_text(dumps(entries), encoding="utf-8", newline="\n")
    kb_path = out / "kb.json"
    expected = [dict(e, version=1) for e in entries]
    kb_path.write_text(dumps(expected), encoding="utf-8", newline="\n")
    covered = "# SYNTHETIC tender: fictional procurement\n\n## Delivery\n1. Describe delivery and implementation.\n## Assurance\n2. Describe security certification.\n## Track record\n3. Describe project experience.\n"
    planted = covered + "## Additional requirements\n4. Describe security accreditation.\n5. Provide orbital launch services.\n6. Explain the unspecified special arrangement.\n"
    (out / "covered.md").write_text(covered, encoding="utf-8", newline="\n")
    (out / "gaps.md").write_text(planted, encoding="utf-8", newline="\n")
    (out / "SYNTHETIC.txt").write_text("All company facts, source references and tenders are fictional and synthetic. No RNG is used.\n", encoding="utf-8", newline="\n")
