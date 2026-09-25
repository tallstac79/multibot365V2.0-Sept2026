"""Benchmark transport failures must never appear as a perfect smaller corpus."""
import unittest
from tools.ocr_bench import align_batch, score

class BatchIntegrity(unittest.TestCase):
    frames = [dict(p='run/a.png', c='receipt'), dict(p='run/b.png', c='receipt')]

    def test_failed_batch_retains_all_failures(self):
        outputs=align_batch(self.frames,dict(status='FAIL',detail='screen locked'))
        self.assertEqual(len(outputs),2)
        self.assertTrue(all(not score(fr,out)[0] for fr,out in zip(self.frames,outputs)))

    def test_truncated_batch_cannot_shift_later_truth(self):
        outputs=align_batch(self.frames,dict(status='PASS',bench=dict(frames=[dict(p='run/b.png',c='receipt')])))
        self.assertEqual(len(outputs),2)
        self.assertTrue(all(out.get('error') for out in outputs))

    def test_reordered_frames_are_matched_by_identity(self):
        outputs=align_batch(self.frames,dict(status='PASS',bench=dict(frames=[dict(p='run/b.png',c='receipt'),dict(p='run/a.png',c='receipt')])))
        self.assertEqual([o['p'] for o in outputs],[f['p'] for f in self.frames])

    def test_duplicate_or_wrong_class_fails(self):
        outputs=align_batch(self.frames,dict(status='PASS',bench=dict(frames=[dict(p='run/a.png',c='receipt')]*2)))
        self.assertTrue(all(out.get('error') for out in outputs))
        outputs=align_batch(self.frames,dict(status='PASS',bench=dict(frames=[dict(p='run/a.png',c='grid'),dict(p='run/b.png',c='receipt')])))
        self.assertEqual(outputs[0]['error'],'batch_frame_class_mismatch')
