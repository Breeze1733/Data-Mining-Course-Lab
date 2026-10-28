# task2/inputs

本目录存放从 task1 预处理输出复制的输入快照。数据文件不入 git，只保留本说明。

生成/刷新：

```powershell
.\prepare_inputs.ps1 -Task1Dir ..\task1\data\processed -Config .\config.json
```

约定：

- 只复制、不改写；不要手动编辑或增删 JSONL。
- 快照文件集合由 `config.json` 的 `input.sources` 决定，不固定为三个文件；`required=false` 的来源缺失时只警告。
- `manifest.json` 由脚本生成，记录每个来源的 `source_kind`、`id_field`、字节数、SHA-256、记录数与接受数；`extract_entities.py` 启动时校验本次使用文件的哈希。
- 记录数不是契约：请从 `manifest.json` 或运行后的 `outputs/extract_summary.json` 读取实际值，不要假设固定篇数。
- `scenic_area` 的取值也是开放集合；新增景区无需改代码，补 `resources/poi_gazetteer.csv` 可提高精度，不补则走通用后缀兜底并告警。
- task1 数据更新后重新运行脚本；只想处理子集时用 `--area`、`--limit`、`--record-id`、`--sources`。
- 单独提交 task2 时，记得把本目录的数据文件一起打包。
