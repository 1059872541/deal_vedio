# -*- coding: utf-8 -*-
"""仓库根目录的启动器。

`.venv/Scripts/python vedio.py <动词> ...`  —— 不用切目录、不用设 PYTHONPATH。

之所以不直接 `python -m vedio`：包在 `src/` 下（和 util/、jianying_export/ 一致），
根目录没有 `vedio/`，所以需要一个薄启动器把 `src` 放进 sys.path。

将来做成 `pip install -e .` 之后这个文件就可以删了。
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vedio.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
