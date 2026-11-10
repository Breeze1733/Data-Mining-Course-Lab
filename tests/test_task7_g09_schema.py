# -*- coding: utf-8 -*-
"""G09：TOOL_SCHEMAS 参数声明与实际方法签名一致性（机器验证）。"""
import inspect
import unittest
import sys
from pathlib import Path

from graph_tools import TOOL_SCHEMAS, GraphTools  # noqa: E402


class SchemaSignatureTests(unittest.TestCase):
    def test_schema_params_match_signature(self):
        for schema in TOOL_SCHEMAS:
            method = getattr(GraphTools, schema["name"])
            sig = inspect.signature(method)
            declared = set(schema["params"]) 
            actual = {k for k, v in sig.parameters.items() if k not in ("self",)}
            # schema 声明的参数必须都存在于签名（可选参数由签名默认值表达）
            missing = declared - actual
            self.assertEqual(missing, set(),
                             f"{schema['name']} schema 声明了签名没有的参数: {missing}")

    def test_every_public_query_has_schema(self):
        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        for name, m in inspect.getmembers(GraphTools, inspect.isfunction):
            if name.startswith("query_") and name not in schema_names:
                self.fail(f"公开查询 {name} 未在 TOOL_SCHEMAS 注册")


if __name__ == "__main__":
    unittest.main()
