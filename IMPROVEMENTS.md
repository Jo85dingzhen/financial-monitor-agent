# AI Financial Agent - 聚类功能改进总结

## 📋 改进概览

根据 Speaker 1 和 Speaker 3 在会议中提出的需求，本次更新实现了以下三项核心改进：

### ✅ 1. 聚类质量验证模块 (Clustering Quality Validator)

**需求来源**: Speaker 1 提出的"聚类质量检查"需求

**实现位置**: `aligners.py` - `ClusterQualityValidator` 类

**主要功能**:
- **簇内相似度计算**: 使用 TF-IDF + Cosine Similarity 计算每个事件簇内文章的平均相似度
- **簇间距离计算**: 计算不同事件簇之间的距离，检测是否有过度接近的簇（可能需要合并）
- **质量问题检测**: 自动识别以下问题
  - 簇内相似度过低（<0.3）→ 建议拆分
  - 簇间距离过小（>0.7 相似度）→ 建议合并
  - 单文章簇过多 → 聚类过细
- **质量评分**: 生成 0-100 分的总体质量分数
  - 80+ 分: 优秀
  - 60-80 分: 良好
  - <60 分: 需改进

**使用方式**:
```python
from aligners import ClusterQualityValidator

validator = ClusterQualityValidator()
quality_report = validator.validate_clustering(events, verbose=True)

print(f"总体质量分数: {quality_report['overall_score']}/100")
print(f"质量问题: {quality_report['quality_issues']}")
```

**自动集成**: 在 `analyst_demo.py` 的 `cluster_articles()` 方法中，质量验证会自动运行并打印报告。

---

### ✅ 2. 规则驱动聚类算法 (Rule-Based Clustering)

**需求来源**: Speaker 1 提出的"可控性"需求 - 不要黑盒，要可解释的分步流程

**实现位置**: `analyst_demo.py` - `RuleBasedClusterer` 类

**分步流程**:
1. **Step 1: 关键词提取 + TF-IDF 向量化**
   - 使用 `sklearn.TfidfVectorizer` 提取文章特征
   - 生成 200 维的 TF-IDF 向量

2. **Step 2: 相似度矩阵计算**
   - 使用 Cosine Similarity 计算所有文章两两之间的相似度

3. **Step 3: 基于规则的层次聚类**
   - 从每篇文章单独成簇开始
   - 贪婪合并相似度最高且满足规则的簇对
   - 规则包括:
     - 相似度阈值检查（默认 0.4）
     - 时间差异检查（不同月份的宏观数据不合并）
     - 公司主体检查（不同公司不合并，除非相似度 >0.6）

4. **Step 4: 分类和评分**
   - 基于关键词匹配确定事件分类（Macro, Monetary, etc.）
   - 使用 `calculate_pdf_aligned_score()` 计算分数

**对比 LLM 聚类**:
| 特性 | LLM 聚类 | 规则聚类 |
|------|---------|---------|
| 可控性 | ⚠️ 低（黑盒） | ✅ 高（规则透明） |
| 准确性 | ✅ 高（语义理解） | 🟡 中（关键词匹配） |
| 速度 | ⚠️ 慢（API调用） | ✅ 快（本地计算） |
| 成本 | ⚠️ 有（API费用） | ✅ 无 |

**使用方式**:
```python
analyst = AnalystAgent()

# 方法 1: LLM 聚类（默认）
events_llm = analyst.cluster_articles(articles, use_rule_based=False)

# 方法 2: 规则聚类
events_rule = analyst.cluster_articles(articles, use_rule_based=True)
```

---

### ✅ 3. 国内/国际地域标签 (Region Detection)

**需求来源**: Speaker 3 提出的"分类框架中添加国内/国际层"

**实现位置**: `analyst_demo.py` - `TAXONOMY_DEFINITIONS` + `detect_region()` 函数

**扩展的分类定义**:
每个分类现在包含以下新字段:
- `region`: "both" (支持国内外) / "domestic" / "international"
- `domestic_keywords`: 国内关键词列表（如: "中国, 央行, A股"）
- `international_keywords`: 国际关键词列表（如: "美国, 美联储, 美股"）

**地域检测逻辑**:
```python
def detect_region(articles, category_key):
    # 统计国内/国际关键词出现次数
    if domestic_count > intl_count * 2:
        return "domestic"  # 国内 🇨🇳
    elif intl_count > domestic_count * 2:
        return "international"  # 国际 🌍
    elif domestic_count > 0 and intl_count > 0:
        return "mixed"  # 混合 🌐
    else:
        return "unknown"
```

**示例输出**:
```
🇨🇳 2025年中国工业企业利润增长
   分类: Macro_Economy
   地域: domestic

🌍 美联储维持利率不变
   分类: Monetary_Liquidity
   地域: international

🌐 全球半导体供应链调整
   分类: Industry_Tech
   地域: mixed
```

**Dashboard 显示**:
在 `_print_dashboard()` 方法中，地域标签会显示为:
```
基准分:10.0 | 权威分:8.5 | 覆盖加成:0.4 | 地域:🇨🇳 国内
```

---

## 🧪 测试方法

运行测试脚本:
```bash
python test_improvements.py
```

测试选项:
1. 测试聚类质量验证
2. 对比 LLM vs 规则聚类
3. 测试地域标签检测
4. 运行所有测试

---

## 📊 改进效果对比

### 改进前 (v1)
- ❌ 无聚类质量检查，不知道结果好坏
- ❌ 纯 LLM 黑盒，无法解释聚类逻辑
- ❌ 无地域区分，国内外事件混在一起

### 改进后 (v2)
- ✅ 自动质量验证，生成 0-100 分评分
- ✅ 提供规则驱动选项，可透明可控
- ✅ 自动检测地域标签，国内/国际/混合清晰标识

---

## 🎯 满足需求对照表

| 需求 | 提出者 | 实现状态 | 实现方式 |
|------|--------|---------|---------|
| 聚类质量检查 | Speaker 1 | ✅ 完全实现 | ClusterQualityValidator 类 |
| 可控性（非黑盒） | Speaker 1 | ✅ 完全实现 | RuleBasedClusterer 分步算法 |
| 分类框架 | Speaker 3 | ✅ 已实现 | TAXONOMY_DEFINITIONS（v1已有） |
| 国内/国际分层 | Speaker 3 | ✅ 完全实现 | region 字段 + detect_region() |

---

## 📝 技术栈

新增依赖:
- `scikit-learn`: TF-IDF 向量化和相似度计算
  ```bash
  pip install scikit-learn
  ```

已有依赖:
- `openai`: LLM API 调用
- `rich`: 终端美化输出
- `pydantic`: 数据模型验证

---

## 🚀 下一步优化建议

1. **质量验证自动修正**
   - 当检测到质量问题时，自动触发重新聚类

2. **混合聚类模式**
   - 结合 LLM 和规则的优势
   - 先用规则快速初筛，再用 LLM 精确分类

3. **地域权重调整**
   - 根据地域调整事件评分（如国内宏观事件权重更高）

4. **聚类参数自适应**
   - 根据文章数量自动调整相似度阈值

---

## 📞 联系方式

如有问题或建议，请联系开发团队。

**版本**: v2.0
**更新日期**: 2026-01-29
**更新内容**: 实现三大聚类改进功能
