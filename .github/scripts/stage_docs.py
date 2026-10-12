"""
Stages the documentation site sources: copies the pages the site is built from into `_docs/`, the `docs_dir` of
`zensical.toml`, so that the Markdown files stay where GitHub renders them and the site gets the same pages.

README.md becomes the landing page `index.md`, CHANGELOG.md and llms.txt keep their names at the site root, and
`docs/` is copied as the `docs/` section. Two kinds of links are rewritten in the copies only: links from `docs/`
up to README.md point to the landing page, and README links to repository files through GitHub point to the pages
in the site. `api.md`, the mkdocstrings reference of every public module, is generated here so that no file in the
repository carries mkdocstrings directives, which GitHub would show as text.

Run from any directory: `python .github/scripts/stage_docs.py`.
"""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "_docs"
GITHUB_FILE = re.compile(r"https://github\.com/0xf104a/smalldi/(?:blob|tree)/master/((?:docs/)?[\w./-]+\.md)")
README_LINK = re.compile(r"((?:\.\./)+)README\.md")
API_MODULES = [
    "smalldi",
    "smalldi.annotation",
    "smalldi.context",
    "smalldi.thread",
    "smalldi.asynchronous",
    "smalldi.container",
    "smalldi.collector",
    "smalldi.concurrency",
    "smalldi.decorator",
    "smalldi.atomic",
]


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()
    shutil.copytree(ROOT / "docs", STAGE / "docs", ignore=shutil.ignore_patterns("requirements.txt"))
    for page in (STAGE / "docs").rglob("*.md"):
        page.write_text(README_LINK.sub(r"\1index.md", page.read_text(encoding="utf-8")), encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    (STAGE / "index.md").write_text(GITHUB_FILE.sub(r"\1", readme), encoding="utf-8")
    shutil.copy(ROOT / "CHANGELOG.md", STAGE / "CHANGELOG.md")
    shutil.copy(ROOT / "llms.txt", STAGE / "llms.txt")
    sections = "\n".join(f"## `{module}`\n\n::: {module}\n" for module in API_MODULES)
    (STAGE / "api.md").write_text(f"# API reference\n\n{sections}", encoding="utf-8")


if __name__ == "__main__":
    stage()
    print(f"staged {sum(1 for _ in STAGE.rglob('*') if _.is_file())} files into {STAGE.relative_to(ROOT)}")
