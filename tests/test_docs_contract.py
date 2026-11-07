# -*- coding: utf-8 -*-
"""
文档-代码契约测试

目的：防止「说明书里写的命令，代码里并不存在」。
这类漂移最危险 —— AI 照着说明书写明的东西去执行，必然失败，然后开始自由发挥。

扫描对象：
    AGENTS.md
    .claude/skills/*/SKILL.md

规则：
    1. 文中出现的每个 *.py 文件名，必须能在仓库里找到
    2. skill 里不得出现写死的 `cd <绝对路径>`（应该由调用方决定工作目录）
    3. AGENTS.md 引用的相对路径（docs/...、conf/...）必须存在

运行：
    .venv\\Scripts\\python -m unittest discover -s tests -v
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git"}


def repo_py_basenames() -> set[str]:
    """仓库里所有 .py 的文件名（不含路径）"""
    out = set()
    for p in REPO.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.add(p.name)
    return out


def instruction_files() -> list[Path]:
    files = []
    agents = REPO / "AGENTS.md"
    if agents.exists():
        files.append(agents)
    skills = REPO / ".claude" / "skills"
    if skills.is_dir():
        files.extend(sorted(skills.glob("*/SKILL.md")))
    return files


class TestInstructionFilesExist(unittest.TestCase):
    def test_at_least_agents_md(self):
        names = [p.name for p in instruction_files()]
        self.assertIn("AGENTS.md", names)


class TestPyReferencesResolve(unittest.TestCase):
    """说明书里提到的每个 .py 都必须真实存在"""

    def test_all_referenced_py_exist(self):
        known = repo_py_basenames()
        missing = []
        for f in instruction_files():
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"[\w./\\-]+\.py\b", text):
                token = m.group()
                base = Path(token.replace("\\", "/")).name
                if base in known:
                    continue
                # 允许显式标注为「未实现 / 待建」
                line = text.splitlines()[text[: m.start()].count("\n")]
                if any(k in line for k in ("未实现", "待建", "TODO", "将实现", "不存在")):
                    continue
                missing.append(f"{f.relative_to(REPO).as_posix()}: {token}")
        self.assertEqual(missing, [], "说明书引用了不存在的脚本：\n  " + "\n  ".join(missing))


class TestNoHardcodedCwd(unittest.TestCase):
    """说明书里不应写死绝对路径的 cd —— 工作目录应由调用方决定"""

    def test_no_absolute_cd_in_instructions(self):
        offenders = []
        for f in instruction_files():
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bcd\s+[a-zA-Z]:[\\/]", line):
                    offenders.append(f"{f.relative_to(REPO).as_posix()}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "说明书里有写死的 cd 路径：\n  " + "\n  ".join(offenders))


class TestAgentsMdPathsResolve(unittest.TestCase):
    """AGENTS.md 里引用的仓库相对路径必须存在"""

    PATTERNS = [
        r"`(docs/[\w\u4e00-\u9fff./-]+\.md)`",
        r"`(conf/[\w\u4e00-\u9fff./-]+)`",
        r"`(src/[\w\u4e00-\u9fff./-]+\.py)`",
    ]

    def test_referenced_paths_exist(self):
        agents = REPO / "AGENTS.md"
        if not agents.exists():
            self.skipTest("没有 AGENTS.md")
        text = agents.read_text(encoding="utf-8")
        missing = []
        for pat in self.PATTERNS:
            for m in re.finditer(pat, text):
                rel = m.group(1)
                if not (REPO / rel).exists():
                    missing.append(rel)
        self.assertEqual(sorted(set(missing)), [], "AGENTS.md 引用了不存在的路径")


if __name__ == "__main__":
    unittest.main(verbosity=2)
