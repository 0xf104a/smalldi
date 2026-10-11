"""
Checks the documentation: runs its Python examples, validates its mermaid diagrams and its relative links.

Every ```python block of README.md and docs/*.md that imports smalldi and doesn't call `input(` runs in its
own process, from a temporary directory, with `src` on `sys.path`. Every ```mermaid block of docs/*.md is
parsed by mermaid under Node, through check_mermaid.mjs next to this script, which needs `mermaid` and
`jsdom` resolvable from the repository root. Every relative Markdown link of README.md and docs/*.md must
point to an existing file. The exit status is non-zero when any check fails.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MERMAID_SCRIPT = Path(__file__).resolve().with_name("check_mermaid.mjs")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.IGNORECASE)
EXAMPLE_TIMEOUT = 300


@dataclass
class Block:
    file: Path
    line: int
    language: str
    code: str

    @property
    def location(self) -> str:
        return f"{self.file.relative_to(ROOT)}:{self.line}"


def documents() -> list[Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def parse(path: Path) -> tuple[list[Block], list[tuple[int, str]]]:
    """
    Splits a Markdown file into its fenced blocks and its remaining lines.

    :param path: the Markdown file
    :return: the fenced blocks, and the (line number, text) pairs outside fences
    """
    blocks: list[Block] = []
    prose: list[tuple[int, str]] = []
    opened: tuple[int, str, list[str]] | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if opened is None:
            if line.startswith("```"):
                opened = (number, line[3:].strip().lower(), [])
            else:
                prose.append((number, line))
        elif line.startswith("```"):
            start, language, code = opened
            blocks.append(Block(path, start, language, "\n".join(code) + "\n"))
            opened = None
        else:
            opened[2].append(line)
    if opened is not None:
        raise ValueError(f"{path.relative_to(ROOT)}:{opened[0]}: unterminated code fence")
    return blocks, prose


def is_example(block: Block) -> bool:
    return (block.language == "python"
            and ("import smalldi" in block.code or "from smalldi" in block.code)
            and "input(" not in block.code)


def run_example(block: Block) -> bool:
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / f"{block.file.stem}_{block.line}.py"
        script.write_text(block.code, encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run([sys.executable, str(script)], cwd=directory, env=env,
                                capture_output=True, text=True, timeout=EXAMPLE_TIMEOUT)
    if result.returncode == 0:
        print(f"OK   example {block.location}")
        return True
    print(f"FAIL example {block.location}: exit status {result.returncode}")
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return False


def check_mermaid(blocks: list[Block]) -> bool:
    payload = [{"file": str(block.file.relative_to(ROOT)), "line": block.line, "code": block.code}
               for block in blocks]
    result = subprocess.run(["node", str(MERMAID_SCRIPT)], input=json.dumps(payload), cwd=ROOT,
                            capture_output=True, text=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0


def check_links(path: Path, prose: list[tuple[int, str]]) -> bool:
    ok = True
    for number, line in prose:
        for match in LINK.finditer(line):
            target = match.group(1)
            if URL_SCHEME.match(target):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            if (path.parent / file_part).is_file():
                print(f"OK   link {path.relative_to(ROOT)}:{number} -> {target}")
            else:
                print(f"FAIL link {path.relative_to(ROOT)}:{number} -> {target}: no such file")
                ok = False
    return ok


def main() -> int:
    failures = 0
    mermaid_blocks: list[Block] = []
    for path in documents():
        blocks, prose = parse(path)
        for block in blocks:
            if is_example(block) and not run_example(block):
                failures += 1
            if block.language == "mermaid" and path.parent == ROOT / "docs":
                mermaid_blocks.append(block)
        if not check_links(path, prose):
            failures += 1
    if mermaid_blocks and not check_mermaid(mermaid_blocks):
        failures += 1
    print(f"{failures} failing check(s)" if failures else "all documentation checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
