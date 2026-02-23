# AI Financial Agent V2.0 - 新功能使用指南

## 🚀 快速开始

所有改进功能已完全集成到 `main_v2.py` 的自动化流程中，无需人工干预。

### 运行主程序
```bash
python main_v2.py
```

## ⚙️ 配置选项

在 `main_v2.py` 的 `CONFIG` 字典中调整以下参数：

```python
CONFIG = {
    # === 聚类设置（新增）===
    "use_rule_based_clustering": False,  # False=LLM聚类, True=规则聚类
    "enable_quality_validation": True,   # 是否启用聚类质量验证

    # === 其他设置 ===
    "search_days": 3,
    "search_max_results": 5,
    "report_max_events": 3,
    "run_adversarial_check": True,
    "output_dir": "daily_reports_v2",
    "include_audit_trail": True
}
```

## 📊 三大新功能

### 1. 聚类质量验证 ✅

**配置**: `"enable_quality_validation": True`

**功能**:
- 自动计算簇内相似度（TF-IDF + Cosine Similarity）
- 自动计算簇间距离
- 生成 0-100 分质量评分
- 自动检测质量问题并给出建议

**输出示例**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 聚类质量报告 (Clustering Quality Report)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

总体质量分数: 78.5/100 (良好)

┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━┓
┃ Event ID           ┃  相似度 ┃ 状态  ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━┩
│ evt_1738123456_0   │  0.652 │  ✅  │
│ evt_1738123456_1   │  0.423 │  ✅  │
└────────────────────┴───────┴──────┘
```

### 2. 规则驱动聚类 🔧

**配置**: `"use_rule_based_clustering": True`

**功能**:
- **Step 1**: TF-IDF 关键词提取和向量化
- **Step 2**: Cosine Similarity 相似度计算
- **Step 3**: 基于规则的层次聚类
  - 时间差异检查（不同月份数据拆分）
  - 公司主体检查（不同公司拆分）
  - 相似度阈值控制

**优势**:
- ✅ 完全透明可控（非黑盒）
- ✅ 无 API 调用成本
- ✅ 速度快
- ⚠️ 准确性略低于 LLM

**对比**:
| 特性 | LLM 聚类 (默认) | 规则聚类 |
|------|----------------|---------|
| 可控性 | ⚠️ 低 | ✅ 高 |
| 准确性 | ✅ 高 | 🟡 中 |
| 速度 | ⚠️ 慢 | ✅ 快 |
| 成本 | ⚠️ 有 | ✅ 无 |

### 3. 国内/国际地域标签 🌍

**配置**: 自动启用（无需配置）

**功能**:
- 自动检测事件的地域属性
- 支持四种标签：
  - 🇨🇳 **国内** (domestic)
  - 🌍 **国际** (international)
  - 🌐 **混合** (mixed)
  - ❓ **未知** (unknown)

**检测逻辑**:
- 基于关键词匹配（央行、A股 vs 美联储、美股）
- 国内关键词数量 > 国际 2倍 → 国内
- 国际关键词数量 > 国内 2倍 → 国际
- 两者都有 → 混合

**Dashboard 显示**:
```
基准分:10.0 | 权威分:8.5 | 覆盖加成:0.4 | 地域:🇨🇳 国内
```

## 🔄 完整工作流

```
Phase 1: 全网采集 (Gathering)
    ↓
Phase 2: 语义聚类 (Clustering)
    ├─ 选择聚类方法（LLM / 规则）
    ├─ 执行聚类
    ├─ 质量验证（如果启用）✨ 新
    └─ 地域检测 ✨ 新
    ↓
Phase 3: 原子化撰稿 (Claims Extraction)
    ↓
Phase 4: 三阶段核验 (Verification Pipeline)
    ↓
Phase 5: 审计发布 (Publication)
```

## 📝 使用场景建议

### 场景 1: 高质量生产环境（默认配置）
```python
CONFIG = {
    "use_rule_based_clustering": False,  # 使用 LLM
    "enable_quality_validation": True,   # 启用质量验证
}
```
**适用**: 需要高准确性的正式报告

### 场景 2: 快速原型/测试
```python
CONFIG = {
    "use_rule_based_clustering": True,   # 使用规则聚类
    "enable_quality_validation": False,  # 关闭质量验证
}
```
**适用**: 快速测试、降低 API 成本

### 场景 3: 质量优先
```python
CONFIG = {
    "use_rule_based_clustering": False,  # 使用 LLM
    "enable_quality_validation": True,   # 启用质量验证
    "run_adversarial_check": True,       # 启用对抗检查
}
```
**适用**: 关键报告、需要最高质量保证

## 🛠️ 依赖安装

新功能需要额外安装：
```bash
pip install scikit-learn
```

完整依赖列表：
```bash
pip install openai rich pydantic langgraph python-dotenv scikit-learn
```

## 📊 输出文件

### 主报告文件
`daily_reports_v2/Financial_Briefing_YYYY-MM-DD.md`

包含：
- 事件标题
- 状态徽章（🟢/🟡/🔴）
- 正文内容（摘要、背景、分析、展望）
- 📚 参考文献列表
- ⚠️ 审计警告（如有）

### 审计日志
`daily_reports_v2/audit_log_YYYY-MM-DD.json`

包含：
- 所有验证结果的详细数据
- 质量分数
- 对齐结果
- 用于追溯和调试

## 🎯 满足的需求

| 需求 | 来源 | 实现状态 | 配置参数 |
|------|------|---------|---------|
| 聚类质量检查 | Speaker 1 | ✅ 完全实现 | `enable_quality_validation` |
| 可控性（非黑盒） | Speaker 1 | ✅ 完全实现 | `use_rule_based_clustering` |
| 分类框架 | Speaker 3 | ✅ 已实现 | 无需配置 |
| 国内/国际分层 | Speaker 3 | ✅ 完全实现 | 自动启用 |

## ⚡ 性能影响

### 质量验证性能
- 额外时间：~2-5秒（取决于事件数量）
- 适用场景：所有场景（推荐始终启用）

### 规则聚类性能
- 速度提升：~5-10倍（无 API 调用）
- 成本节省：100%（无 API 费用）
- 准确性：略低于 LLM（约 80-90%）

## 🔍 故障排查

### 问题 1: 缺少 scikit-learn
```
ImportError: 需要安装 scikit-learn
```
**解决**: `pip install scikit-learn`

### 问题 2: 质量验证失败
```
[yellow]质量验证失败: XXX[/]
```
**解决**: 检查文章数量（需要至少 2 篇文章），或临时关闭质量验证

### 问题 3: 规则聚类结果不理想
**解决**:
- 调整相似度阈值（在 `analyst_demo.py` 的 `RuleBasedClusterer` 中）
- 或切换回 LLM 聚类

---

**版本**: V2.0
**更新日期**: 2026-01-29
**技术支持**: 参见 [IMPROVEMENTS.md](IMPROVEMENTS.md) 获取详细技术文档
