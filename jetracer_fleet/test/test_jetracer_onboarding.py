import pathlib
import sys
import unittest

import yaml


SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from jetracer_onboarding import (  # noqa: E402
    DiscoveryGate,
    ParkingAllocator,
    robot_name_from_tf_key,
)


class RobotNameFromTfKeyTests(unittest.TestCase):

    def test_accepts_matching_namespace(self):
        self.assertEqual(
            robot_name_from_tf_key('jetracer_alpha/tf', 'jetracer_'),
            'jetracer_alpha'
        )

    def test_tolerates_leading_slash(self):
        self.assertEqual(
            robot_name_from_tf_key('/jetracer_5/tf', 'jetracer_'),
            'jetracer_5'
        )

    def test_rejects_other_topics_and_namespaces(self):
        self.assertIsNone(robot_name_from_tf_key('bot1/tf', 'jetracer_'))
        self.assertIsNone(
            robot_name_from_tf_key('jetracer_alpha/tf_static', 'jetracer_')
        )
        self.assertIsNone(
            robot_name_from_tf_key('site/jetracer_alpha/tf', 'jetracer_')
        )


class ParkingAllocatorTests(unittest.TestCase):

    def test_assigns_each_space_once_and_is_idempotent(self):
        allocator = ParkingAllocator(['inventory', 'diamond'])
        self.assertEqual(allocator.reserve('jetracer_a'), 'inventory')
        self.assertEqual(allocator.reserve('jetracer_a'), 'inventory')
        self.assertEqual(allocator.reserve('jetracer_b'), 'diamond')
        self.assertIsNone(allocator.reserve('jetracer_c'))

    def test_failed_admission_can_release_a_space(self):
        allocator = ParkingAllocator(['inventory'])
        allocator.reserve('jetracer_a')
        allocator.release('jetracer_a')
        self.assertEqual(allocator.reserve('jetracer_b'), 'inventory')


class DiscoveryGateTests(unittest.TestCase):

    def test_deduplicates_pending_and_active_robots(self):
        gate = DiscoveryGate(5.0)
        self.assertTrue(gate.offer('jetracer_a', now=10.0))
        self.assertFalse(gate.offer('jetracer_a', now=10.0))
        gate.admitted('jetracer_a')
        self.assertFalse(gate.offer('jetracer_a', now=100.0))

    def test_retries_only_after_backoff(self):
        gate = DiscoveryGate(5.0)
        self.assertTrue(gate.offer('jetracer_a', now=10.0))
        gate.failed('jetracer_a', now=10.0)
        self.assertFalse(gate.offer('jetracer_a', now=14.9))
        self.assertTrue(gate.offer('jetracer_a', now=15.0))


class FleetConfigContractTests(unittest.TestCase):

    def test_every_allocatable_space_is_a_charger_and_parking_spot(self):
        package = pathlib.Path(__file__).resolve().parents[1]
        config = yaml.safe_load(
            (package / 'config/fleet/jetracer_fleet_config.yaml').read_text()
        )
        building = yaml.safe_load(
            (package / 'maps/jetracer/jetracer.building.yaml').read_text()
        )
        parking_spots = config['rmf_fleet']['parking_spots']
        vertices = building['levels']['L1']['vertices']
        params_by_name = {
            vertex[3]: vertex[4]
            for vertex in vertices
            if len(vertex) >= 5
        }

        self.assertEqual(config['rmf_fleet']['robots'], {})
        self.assertEqual(len(parking_spots), 5)
        for spot in parking_spots:
            self.assertIn(spot, params_by_name)
            self.assertEqual(params_by_name[spot]['is_parking_spot'], [4, True])
            self.assertEqual(params_by_name[spot]['is_charger'], [4, True])


if __name__ == '__main__':
    unittest.main()
