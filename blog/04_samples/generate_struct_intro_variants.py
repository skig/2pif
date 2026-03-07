#!/usr/bin/env python3

import argparse
import itertools
import json
import pathlib
import re
import subprocess
import sys
import tempfile


STRUCT_PATTERN = re.compile(
    r"(typedef\s+struct\s*\{\n)(?P<body>.*?)(\}\s*foo_t\s*;)",
    re.DOTALL,
)
MEMBER_LINE_PATTERN = re.compile(
    r"^\s*(?P<type>\w+_t)\s+(?P<name>\w+);\s*/\*\s*(?P<offset>\d+)\s+(?P<size>\d+)\s*\s*\*/$"
)
HOLE_LINE_PATTERN = re.compile(r"^\s*/\* XXX (?P<size>\d+) byte[s]? hole, try to pack \*/$")
TRAILING_PADDING_PATTERN = re.compile(r"^\s*/\* padding: (?P<size>\d+) \*/$")
SIZE_LINE_PATTERN = re.compile(
    r"^\s*/\* size: (?P<size>\d+), cachelines: (?P<cachelines>\d+), members: (?P<members>\d+) \*/$"
)

IGNORED_SUBSTRINGS = (
    "libbpf: failed to find '.BTF' ELF section",
    "pahole:",
    "last cacheline:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate every member-order permutation for foo_t, print filtered "
            "pahole output, or emit browser-ready variant data."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="struct_intro.c",
        help="Reference C source file containing typedef struct foo_t.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output file. Defaults to stdout.",
    )
    parser.add_argument(
        "--format",
        choices=("report", "js"),
        default="report",
        help="Output format: text report or JavaScript data assignment.",
    )
    parser.add_argument(
        "--var-name",
        default="STRUCT_INTRO_VARIANTS",
        help="JavaScript variable name used with --format js.",
    )
    return parser.parse_args()


def extract_members(source_text: str) -> tuple[re.Match[str], list[str]]:
    match = STRUCT_PATTERN.search(source_text)
    if not match:
        raise ValueError("Could not find 'typedef struct { ... } foo_t;' in the source file.")

    members = [
        line.strip()
        for line in match.group("body").splitlines()
        if line.strip()
    ]
    if len(members) != 4:
        raise ValueError(f"Expected exactly 4 struct members, found {len(members)}.")

    return match, members


def build_variant_source(source_text: str, match: re.Match[str], members: tuple[str, ...]) -> str:
    body = "".join(f"    {member}\n" for member in members)
    replacement = f"{match.group(1)}{body}{match.group(3)}"
    return f"{source_text[:match.start()]}{replacement}{source_text[match.end():]}"


def build_struct_text(members: tuple[str, ...]) -> str:
    lines = ["typedef struct {"]
    lines.extend(f"    {member}" for member in members)
    lines.append("} foo_t;")
    return "\n".join(lines)


def run_command(command: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def filter_pahole_output(output: str) -> str:
    kept_lines = []
    for line in output.splitlines():
        if any(fragment in line for fragment in IGNORED_SUBSTRINGS):
            continue
        kept_lines.append(line.rstrip())
    return "\n".join(kept_lines).strip()


def simplify_pahole_output(filtered_output: str) -> tuple[str, int, int]:
    simplified_lines = ["typedef struct {"]
    total_size = None
    total_holes = 0

    for line in filtered_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "typedef struct {" or stripped == "} foo_t;":
            continue

        member_match = MEMBER_LINE_PATTERN.match(line)
        if member_match:
            simplified_lines.append(
                "    "
                f"{member_match.group('type')} {member_match.group('name')};"
                f" /* offset: {member_match.group('offset')}, size: {member_match.group('size')} */"
            )
            continue

        hole_match = HOLE_LINE_PATTERN.match(line)
        if hole_match:
            hole_size = int(hole_match.group("size"))
            total_holes += hole_size
            simplified_lines.append(f"    /* padding: {hole_size} */")
            continue

        trailing_padding_match = TRAILING_PADDING_PATTERN.match(line)
        if trailing_padding_match:
            hole_size = int(trailing_padding_match.group("size"))
            total_holes += hole_size
            simplified_lines.append(f"    /* padding: {hole_size} */")
            continue

        size_match = SIZE_LINE_PATTERN.match(line)
        if size_match:
            total_size = int(size_match.group("size"))
            simplified_lines.append(
                f"    /* size: {size_match.group('size')}, "
                f"cachelines: {size_match.group('cachelines')}, "
                f"members: {size_match.group('members')} */"
            )

    simplified_lines.append("} foo_t;")

    if total_size is None:
        raise ValueError("Could not find the total size line in pahole output.")

    return "\n".join(simplified_lines), total_size, total_holes


def member_order_key(members: tuple[str, ...]) -> str:
    return "".join(member.split()[-1].rstrip(";") for member in members)


def generate_variants(source_path: pathlib.Path) -> list[dict[str, object]]:
    source_text = source_path.read_text(encoding="utf-8")
    match, members = extract_members(source_text)

    variants = []
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = pathlib.Path(temp_dir_name)

        for permutation in itertools.permutations(members):
            variant_id = member_order_key(permutation)
            variant_source = build_variant_source(source_text, match, permutation)
            variant_c = temp_dir / f"{variant_id}.c"
            variant_out = temp_dir / f"{variant_id}.out"
            variant_c.write_text(variant_source, encoding="utf-8")

            compile_result = run_command(
                ["gcc", str(variant_c), "-g", "-o", str(variant_out)],
                cwd=source_path.parent,
            )
            if compile_result.returncode != 0:
                raise RuntimeError(
                    f"gcc failed for permutation {variant_id}:\n{compile_result.stderr.strip()}"
                )

            pahole_result = run_command(
                ["pahole", "-C", "foo_t", str(variant_out)],
                cwd=source_path.parent,
            )

            filtered_output = filter_pahole_output(
                f"{pahole_result.stdout}\n{pahole_result.stderr}"
            )
            simplified_pahole, total_size, total_holes = simplify_pahole_output(filtered_output)
            variants.append(
                {
                    "id": variant_id,
                    "order": [member.split()[-1].rstrip(";") for member in permutation],
                    "struct_text": build_struct_text(permutation),
                    "pahole_text": simplified_pahole,
                    "total_size": total_size,
                    "total_holes": total_holes,
                }
            )

    variants.sort(key=lambda item: (item["total_size"], item["total_holes"], item["id"]))

    return variants


def generate_report(variants: list[dict[str, object]]) -> str:
    sections = []
    for index, variant in enumerate(variants, start=1):
        sections.append(
            "\n".join(
                [
                    f"=== Variant {index:02d} ===",
                    f"Member order: {', '.join(variant['order'])}",
                    variant["pahole_text"],
                ]
            )
        )
    return "\n\n".join(sections) + "\n"


def generate_js(variants: list[dict[str, object]], var_name: str) -> str:
    payload = json.dumps(variants, indent=2)
    return (
        "// Generated by blog/04_samples/generate_struct_intro_variants.py\n"
        f"const {var_name} = {payload};\n"
    )


def main() -> int:
    args = parse_args()
    source_path = pathlib.Path(args.source).resolve()

    if not source_path.is_file():
        print(f"Source file not found: {source_path}", file=sys.stderr)
        return 1

    try:
        variants = generate_variants(source_path)
        if args.format == "js":
            output_text = generate_js(variants, args.var_name)
        else:
            output_text = generate_report(variants)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output:
        output_path = pathlib.Path(args.output).resolve()
        output_path.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
