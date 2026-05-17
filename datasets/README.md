# Datasets

本目录是工矿企业风险预警智能体训练与知识库构建所需**静态数据**的唯一根目录。运行时产生的可变状态（记忆库、向量库、AgentFS、上传等）放在仓库根目录的 `var/` 中，请勿将两者混用。

## 目录约定

```
datasets/
├── raw/
│   └── public/                   # 公开数据原始表（CSV/XLSX）
│       ├── 数据补充/             # 补充表（行数较多，含主键ID）
│       ├── 数据参考/             # 参考表（每表 ~100 行抽样）
│       ├── 新数据/               # 行政处罚 / 文书 / 检查相关原始表
│       ├── 企业相关表导出/       # 企业主数据导出宽表
│       └── 事故数据（不一定都是火灾的）.xlsx
├── interim/
│   └── merged/
│       └── new_已清洗.xlsx       # 预合并训练宽表（80016 行 × 214 列）
├── processed/                    # 预留：特征矩阵 / parquet 缓存
└── demo/                         # 模型迭代回放批次（小型 JSON，纳入版本控制）
```

## 与 `config.yaml` 的对应

| 配置项 | 默认值 |
|--------|--------|
| `data.public_data_root` | `datasets/raw/public` |
| `data.raw_data_path` | `datasets/raw/public/数据补充` |
| `data.reference_data_path` | `datasets/raw/public/数据参考` |
| `data.merged_data_path` | `datasets/interim/merged/new_已清洗.xlsx` |
| `iteration.data_source.demo_dir` | `datasets/demo` |

## 获取数据

1. 将官方 `公开数据(1).zip` 解压。
2. 把解压后的「数据补充 / 数据参考 / 新数据 / 企业相关表导出 / 事故数据*.xlsx」全部移入 `datasets/raw/public/` 对应子目录。
3. 把 `new_已清洗.xlsx` 移到 `datasets/interim/merged/`。
4. 完成后更新 `datasets/manifest.yaml` 中的 `updated_at` 与统计字段。

## 注意事项

- `raw/` 与 `interim/` 的内容是**只读训练数据**，所有特征工程结果不要写回此目录，应输出到 `datasets/processed/` 或 `artifacts/`。
- 不要把运行时 JSON（`short_term.json` / `warning_experience.json` 等）放在这里，它们属于 `var/memory/`。
- 单文件 > 100 MB 时优先评估是否拆分或迁出 Git。
