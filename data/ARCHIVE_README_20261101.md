# 给 C 同学的实验数据交接

本包可直接转发。包含原始 CSV、完整请求/任务日志、最新报告、全部六份正式 Nsight 原生采集、Graph 开关对照，以及当前代码快照。**不包含模型、运行时二进制、Python 环境或体积较大的 SQLite 导出。**

## 建议阅读顺序

1. `reports/最新瓶颈报告_含GPU时间线.pdf`：前5页保留10月31日诊断，第6–8页为11月1日时间线、Graph开关对照和Phase 2建议。
2. `data/diagnostic-20261031/clean-r1/`：主要数据，K=1/2/4/8，各64任务。
3. `data/diagnostic-20261031/clean-context/`：长上下文探测，K=1/8，各32任务。
4. `data/gpu-timeline-20261101/`：定位运行时发射/同步开销的补充实验。
5. `CSV_INDEX.csv`：全部CSV的完整路径、行数、字段和有效性说明。

`reports/v2任务质量修复与重跑报告_20261028.md` 保留当时的实验说明，其中“尚未推送/合并”为历史状态；v2工作负载与质量修复后来已合并main。本次新增监测与GPU分析代码目前仍是未推送的工作区快照。

## memory.csv 和 GPU CSV 在哪里

| 用途 | 路径 | 说明 |
|---|---|---|
| 主实验进程/内存 | `data/diagnostic-20261031/clean-r1/k{1,2,4,8}/memory.csv` | 共4份；原格式，字节单位；cpu_pct中100%为一个逻辑CPU |
| 主实验GPU | 同一目录的 `gpu.csv` | 共4份；设备利用率、显存、功率、时钟等 |
| 长上下文进程/内存 | `data/diagnostic-20261031/clean-context/k{1,8}/memory.csv` | 共2份 |
| 长上下文GPU | 同一目录的 `gpu.csv` | 共2份 |
| 每核及服务线程CPU | 各主实验目录的 `cpu_cores.csv`、`cpu_threads.csv` | 只使用collector_version=2的clean组 |
| Linux内存压力/换页 | 各主实验目录的 `pressure.jsonl` | PSI、vmstat、swap及可用RAM |
| Windows宿主机 | `data/diagnostic-20261031/windows-host-v2.jsonl`、`windows-paging.jsonl` | guest指标不能替代宿主机指标；最初一组覆盖不完整 |
| 10月28日参考基线 | `data/baseline-v2-20261028/repeat{1,2,3}/k{1,2,4}/memory.csv` | 共9份；每组16任务，种子42，与64任务主实验不同 |
| 参考基线GPU | `data/baseline-v2-20261028/gpu-repeat{1,2,3}.csv` | 共3份，每份覆盖一整轮三个K；按时间戳对齐，不能当作某个K专用文件 |

每个运行目录同时保留 `requests.jsonl`、`tasks.jsonl`、`events.jsonl`、`timeline.json`、`summary.json`、`run_manifest.json`（如该运行器产生）。独立run_tasks时间线实验由根目录plan和每组summary记录配置，不一定有run_manifest。

## 如何对齐与解释

- 不能只按 `k1` 或 `run_id=k1` 拼接数据；使用完整目录路径标识一次运行。
- 请求日志的ready/dispatch/end是相对实验起点的秒数；`timeline.json` 提供origin_wall，用 `origin_wall + 相对秒` 对齐CSV的墙钟时间。
- memory.csv中的RSS/USS不是GPU显存、KV cache或内存带宽；sys_avail是WSL内可用内存。GPU CSV是整块设备的采样，其他图形程序也可能贡献利用率。
- gpu.csv的utilization.memory是内存活动时间比例，不是显存容量或理论带宽利用率；memory.used/free为MiB。WSL SM时钟不一致、power.limit为N/A的字段不要用于判定降频。
- 原始失败全部保留。主clean数据320任务、317个质量通过、480次请求正常返回；10月28日参考基线144/144通过。二者负载种子/规模不同，不能直接混算或用耗时宣称性能提升。

## GPU 时间线与开关对照

- `data/gpu-timeline-20261101/suite/graph-k{1,2,8}.nsys-rep`：完整16任务的Graph级采集，含API和GPU Graph时间。
- `data/gpu-timeline-20261101/suite/node-k{1,2,8}.nsys-rep`：预热后约3秒的节点级采集。
- 同目录 `analysis.json`：时间区间并集、CPU/GPU重叠、API计数、100ms时间线及采集警告。
- 同目录 `graph-k*-baseline/`、`graph-k*-traced/`、`node-k*-baseline/`、`node-k*-traced/`：完整请求/任务及耗时/生成token记录。
- `data/gpu-timeline-20261101/intervention/`：无Nsight注入的默认Graph与关闭Graph对照，K=1/2，含环境变量、服务日志及全部输出。
- 本轮使用冻结v2 seed=42的16任务，不能与seed=20261031的64任务跨场景直接比较耗时。
- Nsight原生文件用Nsight Systems打开即可查看；如需重算，先导出SQLite（本包不重复包含SQLite）：

```bash
nsys export --type=sqlite --output=graph-k2.sqlite graph-k2.nsys-rep
python -m scripts.analyze_gpu_timeline SQLITE_DIRECTORY --output analysis.json
```

CUDA同步等待可能和GPU工作重叠，不能把两段耗时直接相加。有Graph-ID关联/可能缺失事件的采集警告，细节见报告。Graph级K=8曾叠加离线分析造成宿主机低内存，不用它作干净的采集开销对照；节点级随后单独执行。Graph开关干预只测一次，不代表最终最优K或统计显著性。

## 哪些记录不作主结论

`data/diagnostic-20261031/mixed-r1/`、`mixed-r2/`、`context-r1/`、`warmup/` 为探索/预热记录。其旧版cpu_cores.csv百分比无效，目录内有CPU_CORE_INVALID.txt；其他指标保留，但部分区间受背景图形负载或环境切换影响，不与clean组混算。`measurement-corrections.json`、`background-environment.json` 和 `audit-final.json` 有说明。与任务无关的完整宿主机进程清单未打包。

Nsight的初次smoke试跑没有有效URL，不用于模型成绩；本包提供正式suite和intervention，排除原因保留于audit.json。旧的失败v1负载、mock功能测试结果未混入本包真实主数据。

## 代码和复现

`code/` 是当前工作区源码快照，含生成器、FIFO、监测、分析与测试；新监测和GPU分析改动尚未推送GitHub。请在现有仓库checkout中对照使用，不把本包当完整Git克隆。`analysis-scripts/` 是本机编排/报告脚本，保留本机路径约定，复跑前需调整路径并核对服务PID。

`SHA256SUMS.json` 用于逐文件校验；`git-state.txt` 记录打包时的提交和未提交文件。只核对或绘图可直接读数据，无需启动模型；采集新实验时模型与运行时配置应和团队冻结的预算保持一致。
