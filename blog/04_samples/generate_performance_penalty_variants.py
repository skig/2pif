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
    r"(typedef\s+struct\s*\{\n)(?P<body>.*?)(\}\s*struct_example_t\s*;)",
    re.DOTALL,
)
INSTRUCTION_LINE_PATTERN = re.compile(r"^\s*[0-9a-f]+:\s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate every member-order permutation for struct_example_t and "
            "collect objdump disassembly for foo()."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="01_performance_penalty.c",
        help="Reference C source file containing typedef struct struct_example_t.",
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
        default="PERFORMANCE_PENALTY_VARIANTS",
        help="JavaScript variable name used with --format js.",
    )
    return parser.parse_args()


def extract_members(source_text: str) -> tuple[re.Match[str], list[str]]:
    match = STRUCT_PATTERN.search(source_text)
    if not match:
        raise ValueError(
            "Could not find 'typedef struct { ... } struct_example_t;' in the source file."
        )

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
    lines.append("} struct_example_t;")
    return "\n".join(lines)


def member_order_key(members: tuple[str, ...]) -> str:
    return "".join(member.split()[-1].rstrip(";") for member in members)


def run_command(command: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def extract_foo_disassembly(output: str) -> tuple[str, int]:
    lines = []
    in_foo = False

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if line.endswith("<foo>:"):
            in_foo = True
            lines.append(line)
            continue

        if not in_foo:
            continue

        if not line.strip():
            continue

        if INSTRUCTION_LINE_PATTERN.match(line):
            lines.append(line)

    if not lines:
        raise ValueError("Could not find foo() disassembly in objdump output.")

    instruction_count = sum(1 for line in lines if INSTRUCTION_LINE_PATTERN.match(line))
    return "\n".join(lines), instruction_count


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
            variant_o = temp_dir / f"{variant_id}.o"
            variant_c.write_text(variant_source, encoding="utf-8")

            compile_result = run_command(
                ["gcc", "-O3", "-c", str(variant_c), "-o", str(variant_o)],
                cwd=source_path.parent,
            )
            if compile_result.returncode != 0:
                raise RuntimeError(
                    f"gcc failed for permutation {variant_id}:\n{compile_result.stderr.strip()}"
                )

            objdump_result = run_command(
                ["objdump", "--disassemble=foo", str(variant_o)],
                cwd=source_path.parent,
            )
            if objdump_result.returncode != 0:
                raise RuntimeError(
                    f"objdump failed for permutation {variant_id}:\n{objdump_result.stderr.strip()}"
                )

            asm_text, instruction_count = extract_foo_disassembly(objdump_result.stdout)
            variants.append(
                {
                    "id": variant_id,
                    "order": [member.split()[-1].rstrip(";") for member in permutation],
                    "struct_text": build_struct_text(permutation),
                    "asm_text": asm_text,
                    "instruction_count": instruction_count,
                }
            )

    variants.sort(key=lambda item: (item["instruction_count"], item["id"]))
    return variants


def generate_report(variants: list[dict[str, object]]) -> str:
    sections = []
    for index, variant in enumerate(variants, start=1):
        sections.append(
            "\n".join(
                [
                    f"=== Variant {index:02d} ===",
                    f"Member order: {', '.join(variant['order'])}",
                    f"Instruction count: {variant['instruction_count']}",
                    variant["struct_text"],
                    "",
                    variant["asm_text"],
                ]
            )
        )
    return "\n\n".join(sections) + "\n"


def generate_js(variants: list[dict[str, object]], var_name: str) -> str:
    payload = json.dumps(variants, indent=2)
    return (
        "// Generated by blog/04_samples/generate_performance_penalty_variants.py\n"
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
