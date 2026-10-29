# common：跨实验公共工具

- `report_utils.py`：课程报告 docx 生成器（统一版式：黑体标题、宋体正文小四、1.3 倍行距、首行缩进 2 字符、表格/图片/页码）。各任务的 `build_reportN.py` 通过 `sys.path` 引入。

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from report_utils import ReportBuilder
```
