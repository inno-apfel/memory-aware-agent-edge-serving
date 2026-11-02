"""Analyze Nsight SQLite wall-time unions; never add CPU waits to GPU work."""
import argparse
import json
from pathlib import Path
import sqlite3


def merge(intervals, lo, hi):
    result=[]
    for start,end in intervals:
        start=max(start,lo);end=min(end,hi)
        if end<=start:continue
        if result and start<=result[-1][1]:result[-1][1]=max(result[-1][1],end)
        else:result.append([start,end])
    return result


def duration(intervals):return sum(b-a for a,b in intervals)


def union_duration(intervals,lo,hi):
    total=0;previous=None
    for a,b in intervals:
        a=max(lo,a);b=min(hi,b)
        if b<=a:continue
        if previous and a<=previous[1]:previous[1]=max(previous[1],b)
        else:
            if previous:total+=previous[1]-previous[0]
            previous=[a,b]
    if previous:total+=previous[1]-previous[0]
    return total


def merged_stream(intervals,lo,hi):
    previous=None
    for a,b in intervals:
        a=max(lo,a);b=min(hi,b)
        if b<=a:continue
        if previous and a<=previous[1]:previous[1]=max(previous[1],b)
        else:
            if previous:yield previous
            previous=[a,b]
    if previous:yield previous


def stream_gpu_overlap(intervals,gpu,lo,hi):
    total=shared=0;i=0
    for a,b in merged_stream(intervals,lo,hi):
        total+=b-a
        while i<len(gpu) and gpu[i][1]<=a:i+=1
        j=i
        while j<len(gpu) and gpu[j][0]<b:
            shared+=max(0,min(b,gpu[j][1])-max(a,gpu[j][0]));j+=1
    return total,shared


def bin_durations(intervals,lo,hi,step):
    values=[0]*((hi-lo+step-1)//step)
    for a,b in intervals:
        a=max(a,lo);b=min(b,hi)
        while a<b:
            i=(a-lo)//step;end=min(b,lo+(i+1)*step)
            values[i]+=end-a;a=end
    return values


def overlap(a,b):
    i=j=total=0
    while i<len(a) and j<len(b):
        total+=max(0,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
        if a[i][1]<=b[j][1]:i+=1
        else:j+=1
    return total


def analyze(path):
    c=sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)
    tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    names=dict(c.execute('select id,value from StringIds'))
    activity=[]
    for name in tables:
        if not name.startswith('CUPTI_ACTIVITY_KIND_'):continue
        if any(word in name for word in ['KERNEL','MEMCPY','MEMSET','GRAPH_TRACE']):
            columns={r[1] for r in c.execute('pragma table_info('+name+')')}
            if {'start','end','deviceId'}<=columns:activity.append(name)
    if not activity:raise RuntimeError('No actual GPU activity table: '+str(path))
    lo=min(v for t in activity if (v:=c.execute('select min(start) from '+t+' where end>0').fetchone()[0]) is not None)
    hi=max(c.execute('select max(end) from '+t).fetchone()[0] for t in activity)
    lo=max(0,lo)
    stop=c.execute("select min(timestamp) from DIAGNOSTIC_EVENT where text='Profiling has stopped.'").fetchone()[0]
    if stop is not None:hi=min(hi,stop)
    sql=' union all '.join('select start,end from '+t for t in activity)+' order by start'
    gpu=merge(c.execute(sql),lo,hi)
    sync=[];api_stats=[];api_tables=[]
    for table in ['CUPTI_ACTIVITY_KIND_RUNTIME','CUPTI_ACTIVITY_KIND_DRIVER']:
        if table not in tables:continue
        api_tables.append(table)
        sync.extend(c.execute('select r.start,r.end from '+table+" r join StringIds s on r.nameId=s.id where s.value like '%Synchronize%' order by r.start"))
        api_stats.extend(dict(name=names[r[0]],count=r[1],total_s=r[2]/1e9,mean_us=r[2]/r[1]/1e3)
                         for r in c.execute('select nameId,count(*),sum(end-start) from '+table+' group by nameId'))
    api_sql=' union all '.join('select start,end from '+t for t in api_tables)+' order by start'
    api_total=union_duration(c.execute(api_sql),lo,hi)
    launch_sql=' union all '.join('select r.start,r.end from '+t+" r join StringIds s on r.nameId=s.id where s.value like '%LaunchKernel%' or s.value like '%GraphLaunch%'" for t in api_tables)+' order by start'
    launch_total,launch_busy=stream_gpu_overlap(c.execute(launch_sql),gpu,lo,hi)
    sync=merge(sorted(sync),lo,hi)
    busy=duration(gpu);wait=duration(sync);intersect=overlap(gpu,sync);span=hi-lo
    diagnostics=[dict(timestamp=r[0],severity=r[1],text=r[2]) for r in c.execute('select timestamp,severity,text from DIAGNOSTIC_EVENT where severity>=2')]
    bins=[];step=100000000
    gpu_bins=bin_durations(gpu,lo,hi,step);sync_bins=bin_durations(sync,lo,hi,step)
    for i,start in enumerate(range(lo,hi,step)):
        end=min(start+100000000,hi);window=[[start,end]]
        bins.append(dict(start_s=(start-lo)/1e9,end_s=(end-lo)/1e9,
                         gpu_pct=gpu_bins[i]/(end-start)*100,
                         sync_pct=sync_bins[i]/(end-start)*100))
    counts={t:c.execute('select count(*) from '+t+' where end>? and start<?',(lo,hi)).fetchone()[0] for t in activity}
    kernel_top=[]
    if 'CUPTI_ACTIVITY_KIND_KERNEL' in tables:
        kernel_top=[dict(name=names[r[0]],count=r[1],sum_s=r[2]/1e9)
                    for r in c.execute('select shortName,count(*),sum(end-start) from CUPTI_ACTIVITY_KIND_KERNEL group by shortName order by sum(end-start) desc limit 12')]
    result=dict(file=path.name,gpu_tables=counts,window_start_ns=lo,window_end_ns=hi,
                window_s=span/1e9,gpu_active_s=busy/1e9,gpu_active_pct=busy/span*100,
                gpu_idle_s=(span-busy)/1e9,sync_api_s=wait/1e9,sync_api_pct=wait/span*100,
                sync_overlapping_gpu_s=intersect/1e9,sync_overlapping_gpu_pct_of_sync=intersect/wait*100 if wait else None,
                sync_while_gpu_idle_s=(wait-intersect)/1e9,sync_while_gpu_idle_pct=(wait-intersect)/span*100,
                cuda_api_union_pct=api_total/span*100,
                launch_api_s=launch_total/1e9,launch_api_pct=launch_total/span*100,
                launch_while_gpu_idle_s=(launch_total-launch_busy)/1e9,
                launch_while_gpu_idle_pct=(launch_total-launch_busy)/span*100,
                api_top=sorted(api_stats,key=lambda r:-r['total_s'])[:15],kernel_top=kernel_top,
                diagnostics=diagnostics,bins=bins,
                scope='GPU first activity through last activity, clipped to profiling stop; interval unions avoid overlap double counting',
                caveat='Graph-level activity is envelope time, not kernel busy time. Warnings and capture overhead must be reviewed.')
    c.close();return result


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();files=sorted(a.input.glob('*.sqlite')) if a.input.is_dir() else [a.input]
    rows=[analyze(path) for path in files]
    a.output.write_text(json.dumps(rows,indent=2))
    for r in rows:print(r['file'],'GPU%',round(r['gpu_active_pct'],2),'sync%',round(r['sync_api_pct'],2),'overlap%',round(r['sync_overlapping_gpu_pct_of_sync'] or 0,2),'idle during sync%',round(r['sync_while_gpu_idle_pct'],2))


if __name__=='__main__':main()
