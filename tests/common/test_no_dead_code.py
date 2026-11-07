# -*- coding: utf-8 -*-
""" 回归：全仓扫描"return/raise 后同层不可达语句"死代码。

背景：task2/src/entity_sentence_eval.py 曾因在 main 中段插入模块级 import，
结果构建/落盘代码全部落入 prf() 内 return 之后成为死代码——评测脚本静默零产出
（exit 0 且不写产物），链条与审计均不可见。本测试把该缺陷模式固化为静态检查。
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCAN_GLOBS = ["task*/src/*.py", "common/*.py", "tests/*.py"]


def unreachable_after_return(path: Path) -> list[str]:
    hits = []
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            self._block(node.body, f"def {node.name}")
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def _block(self, stmts, ctx):
            returned = False
            for s in stmts:
                if returned:
                    hits.append(f"{path.relative_to(REPO)}:{s.lineno} [{ctx}] "
                                f"return后不可达语句: {type(s).__name__}")
                self._recurse(s, ctx)
                if isinstance(s, (ast.Return, ast.Raise)):
                    returned = True

        def _recurse(self, s, ctx):
            if isinstance(s, (ast.If, ast.For, ast.While, ast.With)):
                for field in ("body", "orelse"):
                    blk = getattr(s, field, None)
                    if blk:
                        self._block(blk, ctx)
            elif isinstance(s, ast.Try):
                for field in ("body", "orelse", "finalbody"):
                    blk = getattr(s, field, None)
                    if blk:
                        self._block(blk, ctx)
                for h in s.handlers:
                    self._block(h.body, ctx)

    V().visit(tree)
    return hits


class TestNoDeadCode(unittest.TestCase):
    def test_no_unreachable_after_return(self):
        files = sorted(set(f for g in SCAN_GLOBS for f in REPO.glob(g)))
        self.assertGreater(len(files), 20, "扫描范围异常：源文件数过少")
        hits = [h for f in files for h in unreachable_after_return(f)]
        self.assertEqual(hits, [], "发现 return 后不可达死代码（静默零产出风险）:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
