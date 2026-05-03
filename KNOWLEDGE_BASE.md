# 知识库更新与维护说明

## 一、知识库文件清单

系统运行时自动生成并维护以下 6 个核心 Markdown 知识库文件：

| 文件名 | 用途 | 更新频率 |
|--------|------|---------|
| `工矿风险预警智能体合规执行书.md` | 国家法规、合规红线、禁止操作 | 法规变更时 |
| `部门分级审核SOP.md` | 四级风险审核部门、责任人、流程 | 组织架构调整时 |
| `工业物理常识及传感器时间序列逻辑.md` | 传感器参数、异常规则、物理关联 | 技术更新时 |
| `企业已具备的执行条件.md` | 应急设备、人员资质、处置标准 | 标准修订时 |
| `类似事故处理案例.md` | 历史事故案例、处置流程、整改措施 | 每次事件后 |
| `预警历史经验与短期记忆摘要.md` | 运行时自动写入的处置经验 | 实时更新 |

## 二、更新方式

### 1. 通过 API 更新

```bash
# 写入知识库
curl -X POST http://localhost:8000/api/v1/knowledge/write \
  -H "Content-Type: application/json" \
  -d '{"filename": "类似事故处理案例.md", "content": "# 新增案例\n..."}'

# 追加内容
curl -X POST http://localhost:8000/api/v1/knowledge/append \
  -H "Content-Type: application/json" \
  -d '{"filename": "预警历史经验与短期记忆摘要.md", "content": "## 新记录\n..."}'
```

### 2. 通过前端更新

访问 Streamlit 前端（`http://localhost:8501`）→ 知识库管理页面，选择文件后编辑保存。

### 3. 直接修改文件

知识库文件存储于 `AgentFS` 虚拟文件系统中，也可通过 SQLite 直接操作：

```bash
sqlite3 data/agentfs.db
SELECT path FROM metadata WHERE path LIKE 'knowledge_base/%';
```

## 三、版本控制

### 生成快照

每次重要修改后，建议生成 Git 快照：

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/snapshot?commit_message=更新合规条款"
```

### 查看历史

```bash
cd data/agentfs_git
git log --oneline
```

### 回滚版本

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/rollback/<commit_id>
```

## 四、内容规范

### Markdown 表格规范

使用标准 Markdown 表格语法：

```markdown
| 列A | 列B | 列C |
|-----|-----|-----|
| 1   | 2   | 3   |
```

系统提供的 `MarkdownTablePrettifier` 可将 CSV 自动转换为 Markdown 表格。

### 内容质量要求

1. **准确性**：法规条款需引用最新有效版本
2. **完整性**：案例需包含原因、流程、措施三要素
3. **结构化**：使用标题层级（# ## ###）组织内容，便于 RAG 分块检索
4. **可追溯**：每次更新注明更新时间、更新人、更新原因

## 五、RAG 检索优化

为提升长期记忆检索效果，建议：

1. **控制段落长度**：每个段落 200-500 字，避免过长
2. **使用明确标题**：标题包含关键词，便于相似度匹配
3. **定期重建索引**：知识库大幅更新后，重启服务重建向量索引
4. **关键词标注**：在关键段落末尾添加 `[关键词: xxx, yyy]` 标签

## 六、维护责任

| 知识库文件 | 维护责任人 | 审核人 |
|-----------|-----------|--------|
| 合规执行书 | 法规专员 | 法务部门 |
| 部门分级审核 SOP | 行政管理人员 | 安全监管负责人 |
| 工业物理常识 | 技术工程师 | 技术管理负责人 |
| 企业执行条件 | 安全工程师 | 安全监管负责人 |
| 类似事故案例 | 事故调查员 | 技术管理负责人 |
| 历史经验摘要 | 系统自动 | 系统自动 |

## 七、常见问题

**Q: 知识库文件损坏如何恢复？**
A: 通过 Git Commit ID 回滚到历史版本，或使用 SQLite 备份恢复。

**Q: 新增知识库文件如何纳入系统？**
A: 将文件写入 `knowledge_base/` 目录，并在 `config.yaml` 的 `harness.memory.long_term.knowledge_files` 中添加路径，重启服务即可。

**Q: 如何验证知识库检索效果？**
A: 调用 `/api/v1/prediction/predict` 时观察返回的 `suggestions` 中是否包含相关知识库内容，或在前端决策详情页查看检索来源。
