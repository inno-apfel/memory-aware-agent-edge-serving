# B 同学第一轮实现

## 当前状态

分支为 `feat/workloads-baselines`。基于上游提交
`0b4e31691dcb92551e4f06691164a005856fea82`。
真实模型服务接入按讨论暂缓。已完成模拟 HTTP 请求、服务进程内存采样、
四类工作负载、FIFO 请求级固定并发、三步任务及日志保存。
模拟结果统一标记 `MOCK_FUNCTIONAL_ONLY`，不能用于说明真实模型吞吐或内存收益。

## 安装与运行

在仓库根目录使用 Python 3.12 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-baseline.txt
.\.venv\Scripts\python.exe -m workloads.generate --seed 42 --count 16
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.run_experiment --mock --output results/my-first-run
```

输出目录必须是新目录，避免覆盖实验。脚本自动启动并退出本地模拟 HTTP 服务，
使用随机空闲端口，采样的是模拟服务进程而非实验客户端。
默认比较同一份冻结任务集的 K=1、2、4；可使用 `--concurrency 1 2 4` 指定。
`python -m src.runner` 是相同实验入口。

## 任务和调度语义

- short：整数求和，用精确答案检查结果。
- long_context：100 条固定种子生成的干扰记录，加同样的求和任务。
- long_output：要求至少 180 个单词并以 END 结束；上限 512 token。
- three_step：求和后，本地工具读取真实输出并加 7，再读取第二步输出加 3。
  每步实际回答和工具结果都会进入后续历史。工具默认等待 0.1 秒。

合成负载刻意保持语义简单，用于初步正确性验证。输入长度尚未按真实模型 tokenizer
校准，long_output 的检查也只是结构与长度检查，不能代表语义质量。
不设置 ignore_eos，不强制模型输出固定长度；usage 缺失时保留 null，chunks 不是 token。

K 只约束同时进行的模型请求。ready 队列按可执行时间、递增序号排序；
任务每步串行，工具等待不占请求名额。首次到达按冻结轨迹注入，与空闲名额独立。
工具结束后新步骤入队，可排在已等待请求之后。日志 admit 记录调度顺序，
dispatch 记录线程实际开始请求的时间，多线程实际启动可能有极小顺序差异。
未限制等待队列和活跃任务总数，这些留给后续准入控制接口；当前面向有限任务集。

## 输出文件与口径

每个 K 目录包含以下文件：

| 文件 | 内容 |
| --- | --- |
| run_manifest.json | 模式、配置、任务哈希、代码版本、代码文件哈希、依赖版本及进程 PID |
| timeline.json | 任务执行器的单调时钟起点和墙钟，可与内存采样对齐 |
| events.jsonl | 到达、准入、请求结束、工具等待和任务终结事件 |
| requests.jsonl | 每次请求的 ready、dispatch、end、排队、请求体、回答、TTFT、usage 和失败 |
| tasks.jsonl | 整任务到达及结束、完成步骤数、排队、工具等待和终态 |
| memory.csv | 服务进程树 RSS/USS、系统可用内存等，单位为字节 |
| monitor_errors.json | 采样异常；非空时不得把缺失采样解释为零内存 |
| summary.json | 完成数、终态统计、清空耗时、成功任务 P50/P95 和采样峰值 |

根目录还有工作负载副本和 comparison.json。时间单位均为秒。
请求 queue_s = dispatch − ready；HTTP 耗时包含服务端内部排队。
任务 latency_s = 结束 − 计划到达，包含注入延迟、排队、模型调用和工具等待。
tool_wait_s 是本地模拟工具的计划等待总和，调度器晚处理的时间归入后续等待。
吞吐为有限任务集从运行起点到清空的成功任务数/秒，不是稳态窗口吞吐。
P50/P95 用成功任务延迟的 nearest-rank，失败数独立报告；小样本 P95 只供功能检查。
内存峰值来自采样，可能漏掉短时尖峰，不含 GPU 显存。

失败类型包含 timeout、http_500 等 HTTP 状态、connection_error、protocol_error、
incomplete_stream、validation_failed。失败会释放名额，终止该任务的后续步骤。
默认无重试，不把网络错误推断为 OOM。
`--timeout` 是连接和读取无数据间隔超时，**不是整任务总 deadline**；持续流式返回
仍可能长时间运行。强制总 deadline 和取消服务端请求留待真实运行时接口确认后实现。

## 本轮验收

自动测试覆盖种子复现、FIFO、K 上限、三步依赖、工具等待释放名额、
排队时间、失败停止后续步骤，以及真实 HTTP 层的成功、500、超时和断流。
首次模拟实验每组 16 个任务、24 次模型请求，K=1、2、4 均完成 16 个任务，
采样错误为空。具体时间以随交付的原始日志为准，不用于选择真实模型的最佳 K。

## 真实模型接入待办

1. 与 A 确认 `llama serve` 是否为目标安装版本支持的命令；当前启动配置在
   launch_server.py 和 config.yml。运行前核对模型、精度、槽位、上下文和预算。
2. 记录运行时版本、模型文件哈希、硬件资源限制；用 tokenizer 校准含历史和模板的输入。
3. 服务启动后使用明确的本机服务 PID：

```powershell
python launch_server.py
# 另一个终端，把 <PID> 替换为实际服务进程编号
python -m scripts.run_experiment --pid <PID> --url http://127.0.0.1:9931/v1/chat/completions --output results/real-first
```

服务必须先启动；尚未验证 launch_server.py 在此机器能启动真实模型。
远程服务内存需 A 在服务器采集，目前 CLI 要求本机 PID，不能传客户端 PID 来伪装远端测量。
真实运行前还需核对 stream_options、thinking 开关等服务兼容性。主对比固定服务端配置。
后续增加更长工具延迟、开发/测试划分、重复试验和公平性分类汇总后，才选择 K_best。

## 后续 Git 操作

后续改动应在开发分支提交，再推送供团队审查：

```bash
git add .
git commit -m "Add workload generator and FIFO agent baseline"
git push -u origin feat/workloads-baselines
```

results/ 与 .venv/ 已忽略，实验日志需另行归档。提交前确保测试通过。
