"""Service startup scheduling invariants, independent of market/secret access."""
import unittest
from unittest.mock import Mock, patch

from process_scheduling import normalize_service_priority


class ServiceSchedulingTests(unittest.TestCase):
    def test_background_process_must_be_verified_as_normal(self):
        adapter = Mock()
        adapter.read.side_effect = [dict(cpu_class=0x4000, memory_priority=2),
                                    dict(cpu_class=0x20, memory_priority=5)]
        result = normalize_service_priority(adapter=adapter)
        self.assertEqual(result['state'], 'NORMAL_VERIFIED')
        self.assertTrue(result['changed'])
        adapter.apply_normal.assert_called_once()

    def test_already_normal_process_does_not_report_a_change(self):
        adapter = Mock()
        adapter.read.return_value = dict(cpu_class=0x20, memory_priority=5)
        self.assertFalse(normalize_service_priority(adapter=adapter)['changed'])

    def test_ignored_cpu_or_memory_changes_cannot_pass_verification(self):
        for state in (dict(cpu_class=0x4000, memory_priority=5), dict(cpu_class=0x20, memory_priority=2)):
            adapter = Mock()
            adapter.read.return_value = state
            with self.assertRaisesRegex(OSError, 'NOT_NORMAL'):
                normalize_service_priority(adapter=adapter)

    def test_windows_api_failure_is_not_silently_accepted(self):
        adapter = Mock()
        adapter.read.return_value = dict(cpu_class=0x4000, memory_priority=2)
        adapter.apply_normal.side_effect = OSError('fixture')
        with self.assertRaises(OSError):
            normalize_service_priority(adapter=adapter)

    def test_unauthorized_role_never_changes_scheduling_or_loads_secrets(self):
        import vps_private_runtime as runtime
        with patch.object(runtime, 'authorized', return_value=False), \
             patch('process_scheduling.normalize_service_priority') as normalize, \
             patch.object(runtime, 'load_config') as load:
            self.assertEqual(runtime.run_worker('collector'), 5)
        normalize.assert_not_called()
        load.assert_not_called()

    def test_authorized_start_normalizes_before_loading_secrets(self):
        import vps_private_runtime as runtime
        receipt = dict(state='NORMAL_VERIFIED', changed=True)
        with patch.object(runtime, 'authorized', return_value=True), \
             patch('process_scheduling.normalize_service_priority', return_value=receipt) as normalize, \
             patch.object(runtime, 'write_receipt') as write, \
             patch.object(runtime, 'load_config', side_effect=RuntimeError('fixture-stop-before-vault')):
            with self.assertRaisesRegex(RuntimeError, 'fixture-stop-before-vault'):
                runtime.run_worker('collector')
        normalize.assert_called_once()
        write.assert_called_once_with('collector.scheduling.json', receipt)

    def test_failed_normalization_stops_before_loading_secrets(self):
        import vps_private_runtime as runtime
        with patch.object(runtime, 'authorized', return_value=True), \
             patch('process_scheduling.normalize_service_priority', side_effect=OSError('fixture')), \
             patch.object(runtime, 'load_config') as load:
            with self.assertRaises(OSError):
                runtime.run_worker('radar')
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
