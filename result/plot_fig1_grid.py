"""Phase 1 Figure 1 (2 panels on top, 1 wide panel below) in matplotlib, following the homework style
(Set2 colors, black edges, y-grid only, no top/left/right spines, square legend on top).
Usage: python plot_fig1_grid.py PATH_TO_UNZIPPED_PACKAGE/data
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

DATA = Path(__file__).resolve().parent.parent / "data"
E2_DIR = DATA / 'diagnostic-20261031' / 'clean-r1'   # 64 tasks, K=1,2,4,8, 1 run each
E1_DIR = DATA / 'baseline-v2-20261028'               # 16 tasks, K=1,2,4, 3 runs each

# ========================= Read the raw logs =========================
def load_run(run_dir, exp, K, rep):
    tasks = pd.read_json(run_dir / 'tasks.jsonl', lines=True)
    reqs = pd.read_json(run_dir / 'requests.jsonl', lines=True)
    reqs['completion_tokens'] = reqs['usage'].apply(lambda u: u['completion_tokens'])
    reqs = reqs.merge(tasks[['task_id', 'task_type']], on='task_id')
    for df in (tasks, reqs):
        df['exp'], df['K'], df['rep'] = exp, K, rep
    return tasks, reqs

runs = [load_run(E2_DIR / f'k{k}', 'E2', k, 1) for k in [1, 2, 4, 8]]
runs += [load_run(E1_DIR / f'repeat{r}' / f'k{k}', 'E1', k, r) for r in [1, 2, 3] for k in [1, 2, 4]]
tasks = pd.concat([t for t, _ in runs], ignore_index=True)
reqs = pd.concat([q for _, q in runs], ignore_index=True)
tasks['validated'] = (tasks['status'] == 'completed') & tasks['quality_pass'].fillna(True).astype(bool)

# ========================= Shared style =========================
cmap = plt.get_cmap('Set2')
colors = [cmap(i) for i in range(8)]
Ks = [1, 2, 4, 8]
x = np.arange(len(Ks))                      # K is plotted as evenly spaced categories

def style_axes(ax, xlabel, ylabel, ticks=True):
    ax.grid(alpha=0.5, axis='y', zorder=0)
    ax.set_axisbelow(True)
    if ticks:
        ax.set_xticks(x, [str(k) for k in Ks])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel, labelpad=1)
    ax.spines['right'].set_color('none')
    ax.spines['top'].set_color('none')
    ax.spines['left'].set_color('none')

def square_legend(ax, labels, cols, marker='s', extra=(), loc='upper left', anchor=(0.0, 1.0), ncol=1):
    handles = [Line2D([0], [0], marker=marker, color='none', markerfacecolor=c, markersize=4,
                      markeredgecolor='black', label=l) for l, c in zip(labels, cols)]
    handles += list(extra)
    ax.legend(handles=handles, bbox_to_anchor=anchor, loc=loc, ncol=ncol, fontsize=5.3, framealpha=0.9,
              columnspacing=0.8, handlelength=0.5, borderpad=0.25,
              handletextpad=0.7, labelspacing=0.15, edgecolor='white')


plt.rcParams.update({'font.size': 6.5, 'axes.labelsize': 6.5, 'xtick.labelsize': 6, 'ytick.labelsize': 6})
fig = plt.figure(figsize=(3.4, 3.7), dpi=230)
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.05], hspace=0.6, wspace=0.55)
ax_a = fig.add_subplot(gs[0, 0])
ax_b = fig.add_subplot(gs[0, 1])
ax_c = fig.add_subplot(gs[1, :])

# ===================== (a) generated tokens/s vs K (line + error bars) =====================
per_run = (reqs.groupby(['exp', 'K', 'rep'])['completion_tokens'].sum()
           / tasks.groupby(['exp', 'K', 'rep'])['end'].max()).rename('tok_s').reset_index()
a_df = per_run.groupby(['exp', 'K'])['tok_s'].agg(['mean', 'std']).reset_index()
ax = ax_a
series = [('E2', 'E2 (n=1)', colors[2]),
          ('E1', 'E1 (n=3, ±s.d.)', colors[1])]
for exp, label, c in series:
    d = a_df[a_df['exp'] == exp]
    xs = [Ks.index(k) for k in d['K']]
    ax.plot(xs, d['mean'], color=c, lw=1.4, zorder=2)
    if exp == 'E1':
        ax.errorbar(xs, d['mean'], yerr=d['std'], fmt='none', ecolor='black',
                    elinewidth=0.8, capsize=3, zorder=3)
    ax.scatter(xs, d['mean'], s=14, color=c, edgecolor='black', zorder=4)
    # values are in Table 2 / text; no point labels here to keep the panel readable
style_axes(ax, 'Concurrency cap K', 'Gen. tokens/s')
ax.set_yticks(np.arange(0, 351, 50))
square_legend(ax, [s_[1] for s_ in series], [s_[2] for s_ in series], marker='o', loc='lower right', anchor=(1.02, -0.03))
ax.set_title('(a) Throughput', loc='left', fontsize=6.5, pad=3)

# ===================== (b) continuation step: queueing vs service (log dot plot) =====================
b_df = reqs[(reqs['exp'] == 'E2') & (reqs['task_type'] == 'three_step') & (reqs['step_id'] == 1)]
b_df = b_df.groupby('K')[['queue_s', 'total']].mean().reset_index()
ax = ax_b
series = [('queue_s', 'Queueing', colors[3]), ('total', 'Service', colors[0])]
for col, label, c in series:
    ax.plot(x, b_df[col], color=c, lw=1.4, zorder=2)
    ax.scatter(x, b_df[col], s=14, color=c, edgecolor='black', zorder=3)
    for xi, yi in zip(x, b_df[col]):
        ax.text(xi, yi * 1.4, f'{yi:.2g}', ha='center', va='bottom', fontsize=4.8, color='#4D4D4D')
ax.set_yscale('log')
ax.set_ylim(0.05, 500)
ax.set_yticks([0.1, 1, 10, 100], ['0.1', '1', '10', '100'])
ax.minorticks_off()
style_axes(ax, 'Concurrency cap K', 'Seconds (log)')
square_legend(ax, [s_[1] for s_ in series], [s_[2] for s_ in series], marker='o', loc='center', anchor=(0.3, 0.5))
ax.set_title('(b) Continuation step', loc='left', fontsize=6.5, pad=3)

# ===================== (c) every task's latency (strip plot + median) =====================
c_df = tasks[tasks['exp'] == 'E2'].copy()
c_df['group'] = np.where(c_df['task_type'] == 'three_step', 'Three-step tasks', 'Single-step tasks')
ax = ax_c
classes = ['Single-step tasks', 'Three-step tasks']
offset = 0.17
rng = np.random.default_rng(0)                     # fixed seed: jitter is reproducible
for i, clss in enumerate(classes):
    for j, k in enumerate(Ks):
        d = c_df[(c_df['K'] == k) & (c_df['group'] == clss)]
        ok, bad = d[d['validated']], d[~d['validated']]
        xc = j + (i - 0.5) * 2 * offset
        jit = rng.uniform(-0.07, 0.07, len(ok))
        ax.scatter(xc + jit, ok['latency_s'], s=5, color=colors[i], edgecolor='black',
                   linewidth=0.25, alpha=0.9, zorder=2)
        if len(bad):                                   # validation failures stay visible
            ax.scatter(np.full(len(bad), xc), bad['latency_s'], s=22, marker='x',
                       color='#4D4D4D', linewidth=1, zorder=3)
        med = ok['latency_s'].median()
        ax.hlines(med, xc - 0.11, xc + 0.11, color='black', lw=1.2, zorder=4)
        ax.text(xc + 0.12, med, round(med, 1), ha='left', va='center', fontsize=4.8, color='#4D4D4D')
style_axes(ax, 'Concurrency cap K', 'Task latency (s)')
ax.set_xlim(-0.5, len(Ks) - 0.5)
ax.set_yticks(np.arange(0, 226, 50)); ax.set_ylim(-5, 262)
fail = Line2D([0], [0], marker='x', color='none', markeredgecolor='#4D4D4D', markersize=4,
              label='Failed')
med_h = Line2D([0], [0], color='black', lw=1.6, label='Median')
square_legend(ax, ['Single-step','Three-step'], colors[:2], marker='o', extra=(med_h, fail), loc='upper center', anchor=(0.5, 1.05), ncol=4)
ax.set_title('(c) Every E2 task (64 per K)', loc='left', fontsize=6.5, pad=3)

fig.savefig('figure1_col.png', dpi=300, bbox_inches='tight')
fig.savefig('figure1_col.pdf', bbox_inches='tight')
#plt.show()