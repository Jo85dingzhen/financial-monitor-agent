# 报告版本控制使用指南 ✅

## 🎯 功能说明

每次运行 `main_v2.py` 都会生成**唯一的版本存档**，永不覆盖，方便对比不同运行结果。

---

## 📁 文件命名格式

### 1. 版本存档（序号递增）

```
Financial_Briefing_2026-01-29_01.md    # 第 1 次运行
Financial_Briefing_2026-01-29_02.md    # 第 2 次运行
Financial_Briefing_2026-01-29_03.md    # 第 3 次运行
...
Financial_Briefing_2026-01-29_15.md    # 第 15 次运行
```

**格式**: `Financial_Briefing_YYYY-MM-DD_序号.md`
- 序号：两位数字（01, 02, 03...）
- 自动递增，从当天现有最大序号 +1

### 2. 最新版本（固定名称）

```
Financial_Briefing_2026-01-29_LATEST.md
```

- 每次运行自动更新为最新内容
- 方便快速查看当天最新结果
- 集成到自动化流程时使用固定路径

### 3. 审计日志（对应版本）

```
audit_log_2026-01-29_01.json           # 对应版本 01
audit_log_2026-01-29_02.json           # 对应版本 02
audit_log_2026-01-29_LATEST.json       # 最新版本
```

---

## 🚀 使用示例

### 运行主程序

```bash
python main_v2.py
```

**第 1 次运行输出**:
```
✅ 报告已发布 (版本 01):
  • 版本存档: daily_reports_v2\Financial_Briefing_2026-01-29_01.md
  • 最新版本: daily_reports_v2\Financial_Briefing_2026-01-29_LATEST.md
```

**第 2 次运行输出**:
```
✅ 报告已发布 (版本 02):
  • 版本存档: daily_reports_v2\Financial_Briefing_2026-01-29_02.md
  • 最新版本: daily_reports_v2\Financial_Briefing_2026-01-29_LATEST.md
```

### 查看所有版本

```python
from publisher_v2 import PublisherAgentV2

publisher = PublisherAgentV2(output_dir="daily_reports_v2")

# 查看今天所有版本
publisher.list_reports(date="2026-01-29")
```

**输出示例**:
```
╭──────────────────────────── 📋 报告版本列表 (4 份) ─────────────────────────────╮
│ 文件名                                          │    大小 │ 修改时间           │
├─────────────────────────────────────────────────┼─────────┼────────────────────┤
│ Financial_Briefing_2026-01-29_LATEST.md         │  8.5 KB │ 2026-01-29 18:10:33│
│ Financial_Briefing_2026-01-29_03.md             │  8.5 KB │ 2026-01-29 18:10:33│
│ Financial_Briefing_2026-01-29_02.md             │  7.2 KB │ 2026-01-29 16:45:20│
│ Financial_Briefing_2026-01-29_01.md             │  6.8 KB │ 2026-01-29 14:30:05│
╰─────────────────────────────────────────────────┴─────────┴────────────────────╯
```

---

## 📊 对比不同版本

### 方法 1: VS Code 可视化对比

1. 在 VS Code 中右键点击第一个文件 → **"选择以进行比较"**
2. 右键点击第二个文件 → **"与已选项目比较"**
3. 并排查看差异，修改内容会高亮显示

### 方法 2: 命令行对比

**Windows**:
```bash
fc daily_reports_v2\Financial_Briefing_2026-01-29_01.md ^
   daily_reports_v2\Financial_Briefing_2026-01-29_02.md
```

**Linux/Mac**:
```bash
diff daily_reports_v2/Financial_Briefing_2026-01-29_01.md \
     daily_reports_v2/Financial_Briefing_2026-01-29_02.md
```

### 方法 3: Git Diff（如果在 Git 仓库中）

```bash
git diff --no-index \
  daily_reports_v2/Financial_Briefing_2026-01-29_01.md \
  daily_reports_v2/Financial_Briefing_2026-01-29_02.md
```

---

## 🗂️ 文件管理

### 查看特定日期的所有版本

**Windows**:
```bash
dir daily_reports_v2\Financial_Briefing_2026-01-29_*.md
```

**Linux/Mac**:
```bash
ls daily_reports_v2/Financial_Briefing_2026-01-29_*.md
```

### 只保留 LATEST 文件

如果想清理所有历史版本：

```bash
# Windows
del daily_reports_v2\Financial_Briefing_2026-01-29_??.md
del daily_reports_v2\audit_log_2026-01-29_??.json

# Linux/Mac
rm daily_reports_v2/Financial_Briefing_2026-01-29_[0-9][0-9].md
rm daily_reports_v2/audit_log_2026-01-29_[0-9][0-9].json
```

### 自动清理旧版本（Python 脚本）

```python
import os
import glob
from datetime import datetime, timedelta

def cleanup_old_versions(days_to_keep=7):
    """删除 N 天前的旧版本（保留 LATEST）"""
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)

    pattern = "daily_reports_v2/Financial_Briefing_*.md"
    for f in glob.glob(pattern):
        if "LATEST" in f:
            continue  # 保留 LATEST

        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        if mtime < cutoff_date:
            print(f"删除: {os.path.basename(f)}")
            os.remove(f)
            # 同时删除对应的 JSON 日志
            json_file = f.replace(".md", ".json").replace("Financial_Briefing_", "audit_log_")
            if os.path.exists(json_file):
                os.remove(json_file)

# 保留最近 7 天
cleanup_old_versions(days_to_keep=7)
```

---

## 💡 使用场景

### 场景 1: 参数调优对比

```bash
# 第 1 次运行: 使用 LLM 聚类
python main_v2.py
# → Financial_Briefing_2026-01-29_01.md

# 修改 CONFIG["use_rule_based_clustering"] = True
# 第 2 次运行: 使用规则聚类
python main_v2.py
# → Financial_Briefing_2026-01-29_02.md

# 对比两个版本，看哪种聚类效果更好
```

### 场景 2: 不同时间段数据对比

```bash
# 上午 9:00 运行
python main_v2.py  # → _01.md

# 下午 3:00 运行（可能有新数据）
python main_v2.py  # → _02.md

# 对比查看新增了哪些事件
```

### 场景 3: 验证算法改进

```bash
# 修改前
python main_v2.py  # → _01.md (验证率 50%)

# 修改 aligners.py 对齐算法
# 修改后
python main_v2.py  # → _02.md (验证率 90%)

# 对比验证通过率的提升
```

---

## 🎯 快速访问技巧

### 1. 始终使用 LATEST 查看最新

```bash
# 快速打开最新报告
code daily_reports_v2/Financial_Briefing_*_LATEST.md
```

### 2. 序号便于识别

- `_01` = 第 1 次运行
- `_02` = 第 2 次运行
- `_15` = 第 15 次运行

一眼就能看出运行顺序和次数。

### 3. 自动化集成

在定时任务或脚本中使用固定的 LATEST 路径：

```python
import os
from datetime import datetime

def get_latest_report():
    """获取今天最新报告的路径"""
    date = datetime.now().strftime("%Y-%m-%d")
    return f"daily_reports_v2/Financial_Briefing_{date}_LATEST.md"

# 发送邮件、上传到服务器等
latest = get_latest_report()
if os.path.exists(latest):
    with open(latest, 'r', encoding='utf-8') as f:
        content = f.read()
        # 处理内容...
```

---

## 📝 文件结构示例

```
ai financial agent/
├── daily_reports_v2/
│   ├── Financial_Briefing_2026-01-29_01.md      # 版本 1
│   ├── Financial_Briefing_2026-01-29_02.md      # 版本 2
│   ├── Financial_Briefing_2026-01-29_03.md      # 版本 3
│   ├── Financial_Briefing_2026-01-29_LATEST.md  # 最新版（= 版本 3）
│   │
│   ├── audit_log_2026-01-29_01.json             # 版本 1 日志
│   ├── audit_log_2026-01-29_02.json             # 版本 2 日志
│   ├── audit_log_2026-01-29_03.json             # 版本 3 日志
│   └── audit_log_2026-01-29_LATEST.json         # 最新版日志
```

---

## ❓ 常见问题

### Q: 如何重置版本号从 01 开始？

**A**: 删除当天所有旧版本，下次运行会自动从 01 开始：

```bash
# Windows
del daily_reports_v2\Financial_Briefing_2026-01-29_??.md

# 下次运行会生成 _01.md
```

### Q: 版本号会超过 99 吗？

**A**: 会。序号会自动扩展到 3 位数（100, 101...），格式始终保持两位数显示。

### Q: 如何恢复到某个历史版本？

**A**: 复制历史版本为 LATEST：

```bash
# Windows
copy daily_reports_v2\Financial_Briefing_2026-01-29_01.md ^
     daily_reports_v2\Financial_Briefing_2026-01-29_LATEST.md

# Linux/Mac
cp daily_reports_v2/Financial_Briefing_2026-01-29_01.md \
   daily_reports_v2/Financial_Briefing_2026-01-29_LATEST.md
```

### Q: 可以手动指定版本号吗？

**A**: 不建议。系统会自动分配递增的版本号，手动创建可能导致冲突。

---

## ⚙️ 配置

无需额外配置，版本控制功能**自动启用**。

如需修改输出目录：

```python
# main_v2.py
CONFIG = {
    "output_dir": "daily_reports_v2",  # 修改这里
    # ... 其他配置
}
```

---

## ✨ 优势对比

| 特性 | 时间戳命名 | 序号命名（当前）|
|------|-----------|----------------|
| 可读性 | ⚠️ 一般（14-30-05） | ✅ 优秀（01, 02, 03）|
| 排序 | ✅ 自动按时间 | ✅ 自动按版本 |
| 识别 | ⚠️ 需要看时间 | ✅ 一眼看出顺序 |
| 简洁性 | ⚠️ 较长 | ✅ 简短 |
| 对比 | ⚠️ 难找对应版本 | ✅ 容易选择版本 |

---

**状态**: ✅ 已实现并测试
**版本**: V2.1
**更新日期**: 2026-01-29

**立即运行 `python main_v2.py` 即可体验！** 🚀
