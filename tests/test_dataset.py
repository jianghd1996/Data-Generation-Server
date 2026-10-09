import tempfile
import unittest
from pathlib import Path
from data_generation_server.dataset import plan_jobs, check_catalog, command_for
from data_generation_server.shots import shot_setup


class DatasetTests(unittest.TestCase):
    def test_six_combinations_per_pair_and_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, hdri = root / 'person.glb', root / 'sky.hdr'
            model.touch(); hdri.touch()
            catalog = {'root': str(root), 'objects': [], 'people': [{'id': 'person', 'path': str(model)}],
                       'scenes': [{'id': 'scene', 'environment': 'courtyard', 'preset': 1}],
                       'backgrounds': [{'id': 'sky', 'path': str(hdri)}]}
            plan = plan_jobs(catalog, root / 'out')
            self.assertEqual(len(plan['jobs']), 6)
            self.assertEqual(len({item['output'] for item in plan['jobs']}), 6)
            self.assertEqual({(job['shot'], job['orientation']) for job in plan['jobs']},
                {(shot, orientation) for shot in ('near', 'medium', 'far') for orientation in ('landscape', 'portrait')})
            command = command_for(plan['jobs'][0], plan['settings'], '/blender', str(root))
            self.assertIn('--person-chest', command)
            self.assertIn('--scene-preset', command)
            self.assertFalse(check_catalog(catalog, 11)['quantity_ok'])
            with self.assertRaises(ValueError): plan_jobs(catalog, root, approved_only=True)

    def test_framing_distances_and_person_targets(self):
        for width, height in ((1280, 720), (720, 1280)):
            person = [shot_setup('person', shot, 2, 0.6, width, height, 35, 4.5, 12, 5) for shot in ('near', 'medium', 'far')]
            self.assertGreater(person[0][0], person[1][0])
            self.assertGreater(person[1][0], person[2][0])
            self.assertLess(person[0][1], person[1][1])
            self.assertEqual(person[2][1], 4.5)
            obj = [shot_setup('object', shot, 2, 1, width, height, 35, 4.5, 12, 5)[1] for shot in ('near', 'medium', 'far')]
            self.assertLess(obj[0], obj[1])
            self.assertLess(obj[1], obj[2])


if __name__ == '__main__': unittest.main()

class MultiGpuTests(unittest.TestCase):
    def test_gpu_isolation_and_queue(self):
        from unittest.mock import patch
        import threading
        from data_generation_server.dataset import run_jobs
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = [{'id': str(i), 'output': str(root / str(i))} for i in range(8)]
            plan = {'jobs': jobs, 'settings': {}, 'root': str(root)}
            barrier = threading.Barrier(4)
            seen, lock = [], threading.Lock()
            def execute(command, **kwargs):
                gpu = kwargs['env']['CUDA_VISIBLE_DEVICES']
                with lock:
                    first = gpu not in [item[0] for item in seen]
                    seen.append((gpu, command[0]))
                if first: barrier.wait(timeout=5)
            def complete(job, settings):
                with lock: return any(item[1] == job['id'] for item in seen)
            with patch('data_generation_server.dataset.command_for', side_effect=lambda job, *args: [job['id']]), patch('data_generation_server.dataset.subprocess.run', side_effect=execute), patch('data_generation_server.dataset.job_complete', side_effect=complete):
                self.assertEqual(run_jobs(plan, '/blender', root / 'report.json', ['0', '1', '2', '3']), 0)
            self.assertEqual(len(seen), 8)
            self.assertEqual({gpu for gpu, _ in seen}, {'0', '1', '2', '3'})
            self.assertEqual(len({identity for _, identity in seen}), 8)
