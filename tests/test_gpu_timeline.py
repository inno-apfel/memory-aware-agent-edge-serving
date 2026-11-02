import unittest
from scripts.analyze_gpu_timeline import merge,duration,overlap,union_duration,bin_durations,stream_gpu_overlap


class TimelineTests(unittest.TestCase):
    def test_overlapping_gpu_streams_not_double_counted(self):
        spans=merge([(0,4),(2,7),(9,12)],1,10)
        self.assertEqual(spans,[[1,7],[9,10]])
        self.assertEqual(duration(spans),7)

    def test_cpu_wait_overlapping_gpu_is_not_independent_overhead(self):
        gpu=[[1,5],[7,9]];sync=[[0,8]]
        self.assertEqual(overlap(gpu,sync),5)
        self.assertEqual(duration(sync)-overlap(gpu,sync),3)

    def test_streaming_union_and_bins_clip_crossing_intervals(self):
        self.assertEqual(union_duration(iter([(0,4),(2,7),(9,12)]),1,10),7)
        self.assertEqual(bin_durations([[1,7],[9,10]],0,10,3),[2,3,1,1])
        self.assertEqual(stream_gpu_overlap(iter([(0,4),(2,7),(9,12)]),[[2,6]],1,10),(7,4))
