# 实验原始数据与日志

这里是 2026-11-01 交接包中用户指定的三个完整数据目录，527 个原始文件。
它们包含不同时间、配置和规模的实验，不能跨场景直接合并统计。
本次未加入 11 月 3 日的内存预算实验原始数据。

| 目录 | 内容与优先入口 |
| --- | --- |
| [baseline-v2-20261028](baseline-v2-20261028/) | v2 真实模型参考基线，16任务，K=1/2/4，三次重复；进程内存、GPU监测、请求/任务/事件与配置日志 |
| [diagnostic-20261031](diagnostic-20261031/) | CPU、内存压力和 GPU 诊断；主结果使用 `clean-r1/k{1,2,4,8}/`，长上下文使用 `clean-context/k{1,8}/` |
| [gpu-timeline-20261101](gpu-timeline-20261101/) | `suite/` 六份 Nsight 原始时间线、分析、基线与被采集运行日志；`intervention/` 为 CUDA Graph 开关对照 |

## memory.csv、gpu.csv 与日志

主要监测文件在 `diagnostic-20261031/clean-r1/k*/` 和
`diagnostic-20261031/clean-context/k*/`：

- `memory.csv`：进程树内存与 CPU；RSS/USS 为字节，不是显存。
- `gpu.csv`：整张 GPU 的利用率、显存、功耗等；memory.used/free 为 MiB。
- `cpu_cores.csv` / `cpu_threads.csv`：每核与服务线程 CPU。
- `pressure.jsonl`：Linux PSI、vmstat 和 swap 等。
- `requests.jsonl` / `tasks.jsonl` / `events.jsonl` / `timeline.json`：请求、完整任务、调度与对齐信息。
- 各实验根目录的 `server.log`、console/plan/manifest/summary 等文件保留运行状态和参数。

[CSV_INDEX.csv](CSV_INDEX.csv) 提供全部 80 份监测 CSV 的路径、字段、行数及有效性标注。
索引路径以仓库根目录为基准。只有 24 份 clean 监测 CSV 标为主数据；其他是参考或探索。

## 下载 GPU 原生时间线（Git LFS）

六份 `.nsys-rep` 总计约 339 MB，用 Git LFS 保存原始文件：

```bash
# 在已经安装 Git LFS 的电脑上，于仓库目录运行：
git lfs install --local
git pull --ff-only origin main
git lfs pull
```

CSV、JSON、文本日志直接保存在普通 Git 中，可在 GitHub 浏览。
时间线文件需要下载实际 LFS 对象后再用 Nsight Systems 打开；仅有几行文本的
LFS 指针不是采集文件。网页源代码 ZIP 是否包含对象取决于仓库设置，建议使用上述命令。
如需重算，可用 `nsys export --type=sqlite` 导出；本目录未重复上传大体积 SQLite。

## 有效性与完整性

- `clean-r1`、`clean-context` 使用修正后的 CPU collector_version=2。
- `mixed-r1`、`mixed-r2`、`context-r1`、`warmup` 为探索/预热；旧每核 CPU 百分比无效。
  按 `CPU_CORE_INVALID.txt`、`measurement-corrections.json` 和各 audit 文件解释，不能与 clean 主数据混用。
- Graph 级 K=8 采集曾受离线分析占用主机内存影响；采集警告及失败均保留，不当作干净的 profiler 开销对照。
- [SHA256SUMS_20261101.json](SHA256SUMS_20261101.json) 是这三个目录的逐文件原始哈希。
  校验时从仓库根目录读取 `data/<键名>`；LFS 文件须先下载真实对象。数据禁用换行转换，保留原始字节。
- [ARCHIVE_README_20261101.md](ARCHIVE_README_20261101.md) 是原交接包说明，仅供历史上下文。
  其中 `reports/`、`code/` 等指完整 ZIP 的目录；本次只上传三个数据目录。
  原文“未推送”的状态是打包时的历史记录，监测/分析及内存实验代码现已合并 main。

无模型权重、运行时安装包、Python 环境或无关完整宿主机进程清单。
