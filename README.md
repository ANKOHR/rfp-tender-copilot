# RFP/Tender Copilot

Every answer in your tender response links back to a verified fact, or it gets flagged as a gap before you submit.

A working Python CLI for versioned company facts, tender requirements, transparent evidence matching, gap reporting and cited response workspaces. "Verified" means a user supplied a verification date and source reference. The software does not verify the fact or fetch the source.

## Quickstart

Python 3.10 or newer. CPU only, standard library runtime, no model or GPU dependencies. Run from this repository:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m rfp fixtures --out workspace/fixtures
python -m rfp --kb workspace/fixtures/kb.json report workspace/fixtures/covered.md --as-of 2026-09-29 --format md
python -m rfp --kb workspace/fixtures/kb.json report workspace/fixtures/gaps.md --as-of 2026-09-29 --format json
python -m rfp --kb workspace/fixtures/kb.json draft workspace/fixtures/gaps.md --as-of 2026-09-29
```

If the Python Scripts directory is absent from PATH, use `python -m rfp`. The installed `rfp` command has the same arguments as `python -m rfp`. Use `rfp --help` and `rfp <command> --help`. Global `--kb` must precede the subcommand. Redirect report or draft stdout to a file to save the workspace. Files contain LF newlines; stdout redirection may use your shell's encoding/newline defaults.

Expected fixture coverage: covered tender 3/3 answered, 0 gaps; gap tender 3/6 answered, 3 gaps. All fixtures are synthetic. No external downloads are used by fixture generation. No RNG is used, so no seed is needed.

## Command catalogue

| Command | Behavior |
| --- | --- |
| `kb-add <entry.json> [--update]` | Validate and append an immutable fact version to `--kb` |
| `kb-list` | List all historical versions as JSON |
| `ingest <file>` | Parse markdown or plain text into numbered requirements and section context |
| `map <file> --as-of YYYY-MM-DD` | List every requirement with all overlapping candidates, ranked and explained |
| `gaps <file> --as-of YYYY-MM-DD` | List all requirements without strong evidence and their suggested actions |
| `draft <file> --as-of YYYY-MM-DD` | Produce a cited markdown response workspace with explicit UNANSWERED placeholders |
| `report <file> --as-of YYYY-MM-DD --format md\|json` | Coverage, full mapping, citations, gaps and draft with honesty banner |
| `fixtures --out <dir>` | Write deterministic fictional facts and two synthetic tenders |

Fixture generation writes its five named files in the selected directory, replacing those files on repeat runs. Use a dedicated directory. KB writes use atomic replacement; this local tool supports a single writer, not concurrent database transactions. Keep version-controlled backups for audit use.

## Knowledge base catalogue

Entry input is a JSON object with exactly these fields:

```json
{
  "id": "delivery",
  "statement": "SYNTHETIC: Fictional Example Workshop provides delivery and implementation support.",
  "category": "capabilities",
  "source_reference": "synthetic-record:delivery",
  "date_verified": "2026-09-29",
  "expiry": "2027-09-29",
  "keywords": ["delivery", "implementation"]
}
```

Categories are `capabilities`, `certifications`, `past_projects`. IDs contain letters, digits, underscores or hyphens. Statements and references must be nonempty text. Dates are strict ISO dates, expiry cannot precede verification. Keywords are nonempty lists of lowercase alphanumeric single tokens. Unknown or missing fields raise `SchemaError`. Storage corruption raises `StorageError`. Duplicate adds or updates of unknown IDs raise `VersionError`. Malformed tenders raise `TenderError`. CLI input errors exit with status 2 and name the error on stderr.

`kb-add` creates version 1. `kb-add --update` appends the next version with the same ID. Earlier versions are preserved. `kb-list` includes all versions; mapping uses only the latest version per ID, even if that version is expired. Citations such as `delivery@v1` refer to an actual stored version, accompanied by its source reference. The explicit evaluation date keeps results repeatable and makes future/expired evidence ineligible for strong answers. The KB is editable JSON on disk, not a tamper-proof ledger.

## Tender ingestion

Markdown headings set section context; otherwise context is `General`. Lines starting with `1.` or `1)` create requirements; hierarchical numbers such as `1.2.` are supported. Following nonblank lines continue the requirement until another requirement or heading. Duplicate numbers, prohibited em dash characters and documents without numbered requirements fail explicitly. Unnumbered introductory prose is not a requirement. Number every requirement before ingestion, and review parsing output. Tables, PDF, Word, bullet-only documents and complex numbering are outside this parser's scope.

## Matching rules and confidence bands

Matching uses lowercase alphanumeric tokens from requirement text. It does not use section headings as evidence, embeddings, language models, stemming or synonyms. KB keywords are declared by the user. A candidate requires at least one exact overlapping KB keyword. All such candidates are listed, including weak and expired ones.

| Rule | Trigger tokens (any) | Category | Scope |
| --- | --- | --- | --- |
| security | security, certification | certifications | in scope |
| delivery | delivery, implementation | capabilities | in scope |
| experience | project, experience | past_projects | in scope |
| orbital | orbital, launch | capabilities | out of scope |

Rules are declared in `rfp/core.py`. A candidate records compatible fired rule IDs, or `keyword-overlap` if no category rule applies, its overlapping tokens, and date eligibility.

| Band | Transparent criteria |
| --- | --- |
| strong | At least two overlapping KB keywords, a compatible fired category rule, and verification <= evaluation date <= expiry |
| partial | At least one overlap, compatible rule and eligible dates, but fewer than two overlapping tokens |
| weak | Overlap exists, but category rule compatibility or eligible dates are absent |

Ranking is strong, partial, weak, then descending overlap count, then ascending citation string. Only strong candidates contribute verbatim KB statements to the draft. Multiple strong candidates are all cited; human review must resolve contradictions or irrelevant matches. Candidate confidence is rule strength, not a probability of truth or suitability. Fixed KB, tender and explicit date produce byte-identical serialized mappings, drafts and reports through the Python API and repeat CLI runs in the same environment.

## Gap and draft catalogue

Every parsed requirement remains in the mapping. No strong match means a gap. Suggested action precedence: a fired out-of-scope rule gives `mark out of scope`; another fired rule gives `add KB entry`; no fired rule gives `request clarification`. Suggestions need human review and are not procurement decisions.

The planted gaps are requirement 4 (security accreditation, partial match, add KB entry), 5 (orbital launch, mark out of scope), and 6 (unspecified arrangement, request clarification). Gap sections contain `UNANSWERED` and no drafted claim. Answered sections reproduce only strong evidence statements and cite every statement's version and source reference. No generated connective claims or promises are added.

## Architecture

```text
entry JSON -> schema validation -> append-only versions in local KB JSON
                                             |
                                      latest per ID
                                             |
markdown/text -> numbered requirements -> explicit-date rule matcher
                                             |
                                   ranked evidence candidates
                                             |
                        gap actions + cited draft workspace
                                             |
                            markdown / JSON coverage report
```

The standard-library core is separate from argparse CLI orchestration. Reports include the exact mapping snapshot and draft, so reviewers can trace the rendered claims. There are no network calls, model services or source verification services.

## HONESTY BOUNDARY

The tool assists drafting; it does not write winning bids and does not verify truth. Matches are heuristic keyword/category rules, not semantic understanding. The draft never presents a gap as answered, and citations point to real KB versions. All supplied companies, facts, source references and tenders are fictional, synthetic and labelled. A stored source reference is not proof that its contents were checked. This tool does not guarantee tender success or verify facts. Human reviewers must check evidence, suitability, completeness, contradictions and final submission requirements.

Every markdown and JSON report carries a banner stating that matches are heuristic and fixtures are synthetic. Drafts carry the same banner. A strong match does not establish full requirement satisfaction: negation, context and obligations can defeat keyword matching. Review every proposed response before using it.

## Verification

The pytest suite covers immutable versions, named schema/storage errors, tender parsing, expected confidence bands, candidate ranking, date eligibility, planted gap actions, real citations, UNANSWERED behavior, fixture determinism, repeat mapping/draft bytes, CLI smoke tests and complete fixture report runs. Runtime artifacts belong in ignored `workspace/`. No publishing is performed by this build.
