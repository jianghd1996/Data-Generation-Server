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
