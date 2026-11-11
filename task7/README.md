# 实验 7 旅游规划 Agent

提交结果取自 2026 年 11 月 7 日入库的一批在线 LLM 实测，14/14 达到该批功能断言。12 个场景使用混合意图解析，S1 和 S5 出现意图回退。13 个支持景区的场景调用图谱工具并完成 LLM 润色。报告分析了回退、封闭景点和跨景区归属的局限。

[evidence/online/](evidence/online/) 保存该批原始汇总、行程及 14 份轨迹。历史汇总中的输出路径沿用采集时的写法，实际轨迹在同级 `traces_llm/`。评阅可直接核对归档。

如需在线试用，在 `task7/` 将 `config.example.json` 复制为 `config.json`，填写 API Key 和可用模型。模板的 `base_url` 为 `https://api.breeze.qzz.io/v1`。从仓库根目录运行：

```text
python task7/src/agent_cli.py
python task7/src/run_tests.py --llm
```

第二条命令可另行运行在线场景，产物写入 Git 忽略的 `local/agent_llm/`。归档批次供正式报告使用。
