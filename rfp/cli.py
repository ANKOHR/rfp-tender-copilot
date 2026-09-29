"""Command-line entry point."""
import argparse
import json
import sys
from pathlib import Path
from .core import BANNER, KnowledgeBase, RFPError, SchemaError, dumps, fixtures, ingest, map_requirements, gaps, draft, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=BANNER)
    parser.add_argument("--kb", default="workspace/kb.json", help="versioned KB JSON path")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("kb-add", help="add a fact from a JSON object file")
    add.add_argument("file")
    add.add_argument("--update", action="store_true")
    sub.add_parser("kb-list")
    incoming = sub.add_parser("ingest")
    incoming.add_argument("file")
    for command in ("map", "gaps", "draft", "report"):
        p = sub.add_parser(command)
        p.add_argument("file", help="original markdown/text tender")
        p.add_argument("--as-of", required=True, help="explicit ISO evaluation date")
        if command == "report":
            p.add_argument("--format", choices=("md", "json"), default="md")
    fixture = sub.add_parser("fixtures")
    fixture.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        kb = KnowledgeBase(args.kb)
        if args.command == "fixtures":
            fixtures(args.out)
            output = BANNER + "\nSynthetic fixtures written.\n"
        elif args.command == "kb-add":
            try:
                entry = json.loads(Path(args.file).read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SchemaError("invalid entry JSON") from exc
            output = dumps(kb.add(entry, args.update))
        elif args.command == "kb-list":
            output = dumps(kb.entries())
        else:
            requirements = ingest(Path(args.file).read_text(encoding="utf-8"))
            if args.command == "ingest":
                output = dumps(requirements)
            else:
                mapping = map_requirements(requirements, kb.latest(), args.as_of)
                output = dumps(mapping) if args.command == "map" else dumps(gaps(mapping)) if args.command == "gaps" else draft(mapping) if args.command == "draft" else report(mapping, args.format)
        sys.stdout.write(output)
        return 0
    except (RFPError, OSError) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2
