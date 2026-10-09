import tempfile
import unittest
from pathlib import Path
from data_generation_server.dataset import plan_jobs, check_catalog, command_for, inventory
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

    def test_people_polycount_dedup_and_old_catalog_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'people/pack/extracted'
            folder.mkdir(parents=True)
            paths = []
            for name in ('rp_mei_posed_001_100k.fbx', 'rp_mei_posed_001_30k.fbx', 'rp_mei_posed_001_100k.obj', 'rp_dennis_posed_004_100k.fbx'):
                path = folder / name
                path.write_text(name)
                paths.append(path)
            previous = {'people': [{'id': p.name, 'path': str(p), 'review': 'approved'} for p in paths]}
            catalog = inventory(root, previous)
            self.assertEqual(len(catalog['people']), 2)
            self.assertTrue(all(x['review'] == 'approved' for x in catalog['people']))
            self.assertEqual(len(inventory(root, catalog)['people']), 2)

    def test_renderpeople_rigged_variants_are_one_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'people/pack'
            folder.mkdir(parents=True)
            for suffix in ('u3d', 'ue4', 'yup_a', 'yup_t', 'zup_a', 'zup_t'):
                (folder / f'rp_eric_rigged_001_{suffix}.fbx').write_text(suffix)
            catalog = inventory(root)
            self.assertEqual(len(catalog['people']), 1)
            self.assertTrue(catalog['people'][0]['path'].endswith('_zup_a.fbx'))

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


class SamplingTests(unittest.TestCase):
    def test_independent_video_environment_and_determinism(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'object.blend'; model.touch()
            skies = []
            for i in range(4):
                path = root / f'sky{i}.hdr'; path.touch()
                skies.append({'id': f'sky{i}', 'path': str(path)})
            catalog = {'root': str(root), 'objects': [{'id': 'object', 'path': str(model)}], 'people': [],
                       'scenes': [{'id': f'scene{i}', 'environment': 'courtyard', 'preset': i} for i in range(4)], 'backgrounds': skies}
            a = plan_jobs(catalog, root / 'output', combinations=3)
            self.assertEqual(a, plan_jobs(catalog, root / 'output', combinations=3))
            self.assertEqual(len(a['jobs']), 18)
            self.assertEqual(len({j['output'] for j in a['jobs']}), 18)
            self.assertGreater(len({(j['scene']['id'], j['background']['id']) for j in a['jobs'][:6]}), 1)
            paired = plan_jobs(catalog, root / 'paired', environment_sampling='per-combination')
            self.assertEqual(len({(j['scene']['id'], j['background']['id']) for j in paired['jobs']}), 1)
            with self.assertRaises(ValueError): plan_jobs(catalog, root, external_scenes_only=True)


class PreviewTests(unittest.TestCase):
    def test_all_pairs_single_image_flags_and_resume(self):
        import json
        from data_generation_server.dataset import preview_jobs, job_complete
        from data_generation_server.preview_gallery import write_gallery
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model.glb'; model.touch()
            sky = root / 'sky.hdr'; sky.touch()
            scene = root / 'scene.blend'; scene.touch()
            catalog = {'root': str(root), 'objects': [{'id': 'object', 'path': str(model)}],
                       'people': [{'id': 'person', 'path': str(model)}],
                       'scenes': [{'id': 'external', 'path': str(scene)}, {'id': 'court', 'environment': 'courtyard', 'preset': 0}],
                       'backgrounds': [{'id': 'sky1', 'path': str(sky)}, {'id': 'sky2', 'path': str(sky)}]}
            plan = preview_jobs(catalog, root / 'previews')
            self.assertEqual(len(plan['jobs']), 8)
            self.assertEqual(plan['settings']['frames'], 1)
            job = plan['jobs'][0]
            command = command_for(job, plan['settings'], '/blender', str(root))
            for flag in ('--no-video', '--no-save-scene', '--auto-place'): self.assertIn(flag, command)
            gallery = write_gallery(plan, root / 'previews')
            self.assertTrue(gallery.is_file())
            output = Path(job['output']); output.mkdir()
            flags = command[3:]
            config = dict(plan['settings'], model=str(model), hdri=str(sky), shot='far', selected_orientation='landscape',
                          subject_heading=0, subject_size=2, person_chest=.65, person_knee=.28,
                          seed=42, scene=str(scene), scene_preset=0, subject_position=[0,0,0], auto_place=True)
            (output / 'render-config.json').write_text(json.dumps(config))
            (output / 'SUCCESS.json').write_text(json.dumps({'frames':1, 'video_encoded':False}))
            self.assertFalse(job_complete(job, plan['settings']))
            for folder, filename in [('rgb','rgb_0001.png'),('mask','mask_0001.png'),('depth','depth_0001.exr')]:
                (output / folder).mkdir()
                (output / folder / filename).touch()
            self.assertTrue(job_complete(job, plan['settings']))
