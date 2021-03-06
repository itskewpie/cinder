# Copyright (c) 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Tests For HostManager
"""

from oslo.config import cfg

from cinder import db
from cinder import exception
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common import timeutils
from cinder.scheduler import host_manager
from cinder import test
from cinder.tests.scheduler import fakes


CONF = cfg.CONF


class FakeFilterClass1(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class HostManagerTestCase(test.TestCase):
    """Test case for HostManager class"""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x)
                           for x in xrange(1, 5)]

    def test_choose_host_filters_not_found(self):
        self.flags(scheduler_default_filters='FakeFilterClass3')
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                          self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(scheduler_default_filters=['FakeFilterClass2'])
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]

        # Test 'volume' returns 1 correct function
        filter_classes = self.host_manager._choose_host_filters(None)
        self.assertEqual(len(filter_classes), 1)
        self.assertEqual(filter_classes[0].__name__, 'FakeFilterClass2')

    def _mock_get_filtered_hosts(self, info, specified_filters=None):
        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')

        info['got_objs'] = []
        info['got_fprops'] = []

        def fake_filter_one(_self, obj, filter_props):
            info['got_objs'].append(obj)
            info['got_fprops'].append(filter_props)
            return True

        self.stubs.Set(FakeFilterClass1, '_filter_one', fake_filter_one)
        self.host_manager._choose_host_filters(specified_filters).AndReturn(
            [FakeFilterClass1])

    def _verify_result(self, info, result):
        for x in info['got_fprops']:
            self.assertEqual(x, info['expected_fprops'])
        self.assertEqual(set(info['expected_objs']), set(info['got_objs']))
        self.assertEqual(set(result), set(info['got_objs']))

    def test_get_filtered_hosts(self):
        fake_properties = {'moo': 1, 'cow': 2}

        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()
        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                                                      fake_properties)
        self._verify_result(info, result)

    def test_update_service_capabilities(self):
        service_states = self.host_manager.service_states
        self.assertDictMatch(service_states, {})
        self.mox.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().AndReturn(31337)
        timeutils.utcnow().AndReturn(31338)
        timeutils.utcnow().AndReturn(31339)

        host1_volume_capabs = dict(free_capacity_gb=4321, timestamp=1)
        host2_volume_capabs = dict(free_capacity_gb=5432, timestamp=1)
        host3_volume_capabs = dict(free_capacity_gb=6543, timestamp=1)

        self.mox.ReplayAll()
        service_name = 'volume'
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_volume_capabs)
        self.host_manager.update_service_capabilities(service_name, 'host2',
                                                      host2_volume_capabs)
        self.host_manager.update_service_capabilities(service_name, 'host3',
                                                      host3_volume_capabs)

        # Make sure dictionary isn't re-assigned
        self.assertEqual(self.host_manager.service_states, service_states)
        # Make sure original dictionary wasn't copied
        self.assertEqual(host1_volume_capabs['timestamp'], 1)

        host1_volume_capabs['timestamp'] = 31337
        host2_volume_capabs['timestamp'] = 31338
        host3_volume_capabs['timestamp'] = 31339

        expected = {'host1': host1_volume_capabs,
                    'host2': host2_volume_capabs,
                    'host3': host3_volume_capabs}
        self.assertDictMatch(service_states, expected)

    def test_get_all_host_states(self):
        context = 'fake_context'
        topic = CONF.volume_topic

        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        self.mox.StubOutWithMock(host_manager.LOG, 'warn')
        self.mox.StubOutWithMock(host_manager.utils, 'service_is_up')

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow()),
            dict(id=4, host='host4', topic='volume', disabled=False,
                 availability_zone='zone3', updated_at=timeutils.utcnow()),
            # service on host5 is disabled
            dict(id=5, host='host5', topic='volume', disabled=True,
                 availability_zone='zone4', updated_at=timeutils.utcnow()),
        ]

        db.service_get_all_by_topic(context, topic).AndReturn(services)
        host_manager.utils.service_is_up(services[0]).AndReturn(True)
        host_manager.utils.service_is_up(services[1]).AndReturn(True)
        host_manager.utils.service_is_up(services[2]).AndReturn(True)
        host_manager.utils.service_is_up(services[3]).AndReturn(True)
        host_manager.utils.service_is_up(services[4]).AndReturn(True)
        # Disabled service
        host_manager.LOG.warn("volume service is down or disabled. "
                              "(host: host5)")

        db.service_get_all_by_topic(context, topic).AndReturn(services)
        host_manager.utils.service_is_up(services[0]).AndReturn(True)
        host_manager.utils.service_is_up(services[1]).AndReturn(True)
        host_manager.utils.service_is_up(services[2]).AndReturn(True)
        host_manager.utils.service_is_up(services[3]).AndReturn(False)
        # Stopped service
        host_manager.LOG.warn("volume service is down or disabled. "
                              "(host: host4)")
        host_manager.utils.service_is_up(services[4]).AndReturn(True)
        # Disabled service
        host_manager.LOG.warn("volume service is down or disabled. "
                              "(host: host5)")

        self.mox.ReplayAll()
        self.host_manager.get_all_host_states(context)
        host_state_map = self.host_manager.host_state_map

        self.assertEqual(len(host_state_map), 4)
        # Check that service is up
        for i in xrange(4):
            volume_node = services[i]
            host = volume_node['host']
            self.assertEqual(host_state_map[host].service,
                             volume_node)

        self.host_manager.get_all_host_states(context)
        host_state_map = self.host_manager.host_state_map

        self.assertEqual(len(host_state_map), 3)
        for i in xrange(3):
            volume_node = services[i]
            host = volume_node['host']
            self.assertEqual(host_state_map[host].service,
                             volume_node)


class HostStateTestCase(test.TestCase):
    """Test case for HostState class"""

    def test_update_from_volume_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertEqual(fake_host.free_capacity_gb, None)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.free_capacity_gb, 512)

    def test_update_from_volume_infinite_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertEqual(fake_host.free_capacity_gb, None)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'infinite',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.total_capacity_gb, 'infinite')
        self.assertEqual(fake_host.free_capacity_gb, 'infinite')

    def test_update_from_volume_unknown_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertEqual(fake_host.free_capacity_gb, None)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'unknown',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.total_capacity_gb, 'infinite')
        self.assertEqual(fake_host.free_capacity_gb, 'unknown')
