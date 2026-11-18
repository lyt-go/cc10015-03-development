# 多维分析实验平台

面向实验设计、指标计算、样本分析、效果评估与结论发布的数据分析实验平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 实验设计 | `experiment` | 实验方案 | 方案编号、实验名称、对照组说明 |
| 样本分群 | `sample_group` | 样本分群 | 分群编号、分群名称、筛选条件 |
| 指标定义 | `metric_def` | 指标定义 | 指标编号、指标名称、计算公式 |
| AB结果分析 | `ab_result` | 分析报告 | 报告编号、实验编号、分析指标 |
| 分群对比 | `segment_compare` | 对比任务 | 任务编号、分群A、分群B |
| 多维下钻 | `drill_down` | 下钻维度 | 维度编号、维度名称、下钻层级 |
| 数据筛选 | `data_filter` | 筛选规则 | 规则编号、数据来源、筛选字段 |
| 归因分析 | `attr_analysis` | 归因任务 | 任务编号、目标指标、候选因子 |
| 异常检测 | `anomaly_detect` | 检测规则 | 规则编号、监控指标、检测算法 |
| 预测模型 | `forecast_model` | 模型配置 | 模型编号、预测对象、历史窗口 |
| 数据导出 | `data_export` | 导出任务 | 任务编号、数据来源、导出格式 |
| 同期群追踪 | `cohort_track` | 同期群定义 | 群组编号、群组名称、首次行为 |
| 可视化配置 | `chart_config` | 图表配置 | 图表编号、图表类型、数据来源 |
| 洞察报告 | `insight_report` | 洞察报告 | 报告编号、分析主题、数据来源 |
| 数据新鲜度 | `data_freshness` | 新鲜度监控 | 监控编号、数据表名、最新分区 |
| 口径注册 | `metric_alias` | 口径版本 | 版本编号、指标编号、变更说明 |
| 实验因子 | `expr_factor` | 因子配置 | 因子编号、因子名称、因子层级 |
| 评估看板 | `evaluate_board` | 看板配置 | 看板编号、看板名称、关联实验 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 评估看板聚合快照（V003）

评估看板不再直接返回随机指标，而是按看板配置聚合出一份“看板聚合快照”：

| 数据表 | 用途 |
| --- | --- |
| `ab_result` | AB 对比结果表（实验 × 指标 × 口径版本） |
| `retention_matrix` | 留存矩阵表（实验 × 指标 × 分组 × 周期） |
| `board_snapshot` | 看板聚合快照（状态、口径模式、完成/未完成实验、上一完整快照） |
| `board_snapshot_card` | 快照内的指标卡片（每卡只绑定一个已生效登记口径） |
| `experiment_snapshot` | 卡片展开后的按实验快照（源口径、统一口径、换算系数） |
| `board_snapshot_stage` | 聚合阶段记录，恢复时按未完成实验续写 |
| `board_verification` | V003 核对留档（指纹、步骤、结论） |

接口（前缀 `/api/evaluate_board`）：

- `GET /snapshots`、`GET /snapshots/{id}`、`GET /snapshots/{id}/cards/{card_id}`：
  列表入口、详情面板、卡片展开共用同一个视图构造函数，结果一致。
- `POST /snapshots/refresh`、`POST /run`：按看板配置生成快照，`fail_experiments`
  可模拟聚合失败；失败时保留上一完整快照，`POST /snapshots/{id}/recover` 按未完成
  实验续写。
- `POST /snapshots/{id}/verify`：依次核对“快照生成统一 → 按实验列 → 按实验口径映射
  → 检查事务残留后回滚”，并写一条留档；`GET /snapshots/{id}/verifications` 读取留档。
- `GET /calibers`：已发布快照消费的口径目录；指标定义模块通过
  `GET /api/metric_def/calibers` 读取同一份目录，并在登记时拒绝与快照口径不一致的
  口径版本或未登记的统计粒度。

同一指标在不同实验使用不同口径版本时，采用“按看板统一口径重算”：卡片取最新已生效
登记口径，实验快照保留源口径与换算系数，并在卡片的实验差异说明里记录差异。

领域：数据工程
子方向：数据分析与数据应用
