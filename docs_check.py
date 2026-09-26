"""Fail when the docs no longer match the code. Standard library only, so it runs anywhere.

Checks README.md, CLAUDE.md and the project skill against the scripts and workflows:
  - every script has a module docstring
  - every script and workflow is mentioned in README.md and the skill
  - every env var, secret and repo variable the code reads is mentioned in README.md and the skill
  - every `module.name` the docs mention still exists in that module, and every .py path exists
  - every `python <script>.py --flag` in the docs names a real script and a flag its code handles
  - every entry point in the skill's file table is defined in that file
  - every scheduled workflow's UTC time appears in README.md

Usage: python docs_check.py     prints the problems, exit 1 if any
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
README = ROOT / 'README.md'
CLAUDE_MD = ROOT / 'CLAUDE.md'
SKILL = ROOT / '.claude/skills/automation-reel/SKILL.md'
DOCS = (README, CLAUDE_MD, SKILL)

# Set by GitHub itself, not configured by us.
PLATFORM_VARS = {'GITHUB_OUTPUT', 'GITHUB_REPOSITORY', 'GITHUB_TOKEN'}
ENV_READ = re.compile(r"""os\.environ(?:\.get)?[\[(]\s*['"]([A-Z][A-Z0-9_]+)['"]|\benv\(\s*['"]([A-Z][A-Z0-9_]+)['"]""")
WORKFLOW_VAR = re.compile(r'\$\{\{\s*(?:secrets|vars)\.([A-Z][A-Z0-9_]+)\s*\}\}')
CRON = re.compile(r"cron:\s*'(\d+) (\d+) ")
FILE_EXTS = {'py', 'yml', 'yaml', 'json', 'md', 'mp4', 'txt'}


def scripts():
    return sorted(p for p in ROOT.glob('*.py'))


def workflows():
    return sorted((ROOT / '.github/workflows').glob('*.yml'))


def top_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split('.')[0] for a in node.names)
    return names


def string_constants(tree):
    """String literals in the code, minus the module docstring, so a flag only in the usage text does not count."""
    doc = tree.body[0].value if ast.get_docstring(tree) else None
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc}


def file_table(text):
    """(path, [names]) rows of the skill's file table, whose last column lists key entry points."""
    for path, last in re.findall(r'^\| `([\w./-]+\.py)` \|.*\|([^|]*)\|\s*$', text, re.M):
        yield path, re.findall(r'`(\w+)`', last)


def check():
    problems = []
    docs = {d: d.read_text() if d.exists() else '' for d in DOCS}
    for d in DOCS:
        if not d.exists():
            problems.append(f'{d.relative_to(ROOT)} is missing')
    readme, skill = docs[README], docs[SKILL]

    modules = {}
    for path in scripts():
        tree = ast.parse(path.read_text(), str(path))
        modules[path.stem] = (path, top_level_names(tree), string_constants(tree))
        if not ast.get_docstring(tree):
            problems.append(f'{path.name} has no module docstring')
        for name, text in (('README.md', readme), ('SKILL.md', skill)):
            if path.name not in text:
                problems.append(f'{path.name} is not mentioned in {name}')

    for path in workflows():
        for name, text in (('README.md', readme), ('SKILL.md', skill)):
            if path.name not in text:
                problems.append(f'.github/workflows/{path.name} is not mentioned in {name}')
        for minute, hour in CRON.findall(path.read_text()):
            when = f'{int(hour):02d}:{int(minute):02d} UTC'
            if when not in readme:
                problems.append(f'{path.name} runs at {when} but README.md does not say so')

    env_vars = set()
    for path in scripts():
        for a, b in ENV_READ.findall(path.read_text()):
            env_vars.add(a or b)
    for path in workflows():
        env_vars.update(WORKFLOW_VAR.findall(path.read_text()))
    for var in sorted(env_vars - PLATFORM_VARS):
        for name, text in (('README.md', readme), ('SKILL.md', skill)):
            if not re.search(rf'\b{var}\b', text):
                problems.append(f'env var {var} is used in code but not mentioned in {name}')

    for doc, text in docs.items():
        rel = doc.relative_to(ROOT)
        for mod, attr in sorted(set(re.findall(r'\b([a-z_]+)\.([A-Za-z_]\w*)', text))):
            if mod in modules and attr not in FILE_EXTS and attr not in modules[mod][1]:
                problems.append(f'{rel} mentions {mod}.{attr}, which does not exist in {mod}.py')
        for ref in sorted(set(re.findall(r'(?<![\w/.-])((?:[\w.-]+/)*[a-z_]+\.py)\b', text))):
            if not (ROOT / ref).is_file():
                problems.append(f'{rel} mentions {ref}, which does not exist')
        for script, flag in sorted(set(re.findall(r'python\S* ([a-z_]+)\.py (--[a-z-]+)', text))):
            if script in modules and flag not in modules[script][2]:
                problems.append(f'{rel} documents `{script}.py {flag}`, which {script}.py does not handle')

    for path, names in file_table(skill):
        if not (ROOT / path).is_file():
            continue
        defined = top_level_names(ast.parse((ROOT / path).read_text()))
        for name in names:
            if name not in defined:
                problems.append(f'SKILL.md file table lists {name} for {path}, which does not define it')

    return problems


def main():
    problems = check()
    for p in problems:
        print(f'- {p}')
    print(f'docs_check: {len(problems)} problem(s)' if problems else 'docs_check: docs match the code')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
