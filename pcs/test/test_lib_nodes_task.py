from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

from unittest import TestCase
import logging

from pcs.test.tools.assertions import (
    assert_raise_library_error,
    assert_report_item_list_equal,
)
from pcs.test.tools.custom_mock import MockLibraryReportProcessor
from pcs.test.tools.pcs_mock import mock

from pcs.common import report_codes
from pcs.lib.external import NodeAuthenticationException
from pcs.lib.env import LibraryEnvironment
from pcs.lib.node import NodeAddresses, NodeAddressesList
from pcs.lib.errors import ReportItemSeverity as severity

import pcs.lib.nodes_task as lib


@mock.patch.object(
    LibraryEnvironment,
    "cmd_runner",
    lambda self: "mock cmd runner"
)
@mock.patch.object(
    LibraryEnvironment,
    "node_communicator",
    lambda self: "mock node communicator"
)
class DistributeCorosyncConfTest(TestCase):
    def setUp(self):
        self.mock_logger = mock.MagicMock(logging.Logger)
        self.mock_reporter = MockLibraryReportProcessor()

    def assert_set_remote_corosync_conf_call(self, a_call, node_ring0, config):
        self.assertEqual("set_remote_corosync_conf", a_call[0])
        self.assertEqual(3, len(a_call[1]))
        self.assertEqual("mock node communicator", a_call[1][0])
        self.assertEqual(node_ring0, a_call[1][1].ring0)
        self.assertEqual(config, a_call[1][2])
        self.assertEqual(0, len(a_call[2]))

    @mock.patch("pcs.lib.nodes_task.corosync_live")
    def test_success(self, mock_corosync_live):
        conf_text = "test conf text"
        nodes = ["node1", "node2"]
        node_addrs_list = NodeAddressesList(
            [NodeAddresses(addr) for addr in nodes]
        )
        lib_env = LibraryEnvironment(self.mock_logger, self.mock_reporter)

        mock_corosync_live.set_remote_corosync_conf = mock.MagicMock()
        mock_corosync_live.reload_config = mock.MagicMock()

        lib.distribute_corosync_conf(lib_env, node_addrs_list, conf_text)

        corosync_live_calls = [
            mock.call.set_remote_corosync_conf(
                "mock node communicator", nodes[0], conf_text
            ),
            mock.call.set_remote_corosync_conf(
                "mock node communicator", nodes[1], conf_text
            ),
            mock.call.reload_config("mock cmd runner"),
        ]
        self.assertEqual(
            len(corosync_live_calls),
            len(mock_corosync_live.mock_calls)
        )
        self.assert_set_remote_corosync_conf_call(
            mock_corosync_live.mock_calls[0], nodes[0], conf_text
        )
        self.assert_set_remote_corosync_conf_call(
            mock_corosync_live.mock_calls[1], nodes[1], conf_text
        )
        self.assertEqual(
            corosync_live_calls[2],
            mock_corosync_live.mock_calls[2]
        )

        assert_report_item_list_equal(
            self.mock_reporter.report_item_list,
            [
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_DISTRIBUTION_STARTED,
                    {}
                ),
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_ACCEPTED_BY_NODE,
                    {"node": nodes[0]}
                ),
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_ACCEPTED_BY_NODE,
                    {"node": nodes[1]}
                ),
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_RELOADED,
                    {}
                ),
            ]
        )

    @mock.patch("pcs.lib.nodes_task.corosync_live")
    def test_one_node_down(self, mock_corosync_live):
        conf_text = "test conf text"
        nodes = ["node1", "node2"]
        node_addrs_list = NodeAddressesList(
            [NodeAddresses(addr) for addr in nodes]
        )
        lib_env = LibraryEnvironment(self.mock_logger, self.mock_reporter)

        mock_corosync_live.set_remote_corosync_conf = mock.MagicMock()
        def raiser(comm, node, conf):
            if node.ring0 == nodes[1]:
                raise NodeAuthenticationException(
                    nodes[1], "command", "HTTP error: 401"
                )
        mock_corosync_live.set_remote_corosync_conf.side_effect = raiser
        mock_corosync_live.reload_config = mock.MagicMock()

        assert_raise_library_error(
            lambda: lib.distribute_corosync_conf(
                lib_env, node_addrs_list, conf_text
            ),
            (
                severity.ERROR,
                report_codes.NODE_COMMUNICATION_ERROR_NOT_AUTHORIZED,
                {
                    "node": nodes[1],
                    "command": "command",
                    "reason" : "HTTP error: 401",
                }
            ),
            (
                severity.ERROR,
                report_codes.NODE_COROSYNC_CONFIG_SAVE_ERROR,
                {
                    "node": nodes[1],
                }
            )
        )

        corosync_live_calls = [
            mock.call.set_remote_corosync_conf(
                "mock node communicator", nodes[0], conf_text
            ),
            mock.call.set_remote_corosync_conf(
                "mock node communicator", nodes[1], conf_text
            ),
        ]
        self.assertEqual(
            len(corosync_live_calls),
            len(mock_corosync_live.mock_calls)
        )
        self.assert_set_remote_corosync_conf_call(
            mock_corosync_live.mock_calls[0], nodes[0], conf_text
        )
        self.assert_set_remote_corosync_conf_call(
            mock_corosync_live.mock_calls[1], nodes[1], conf_text
        )
        mock_corosync_live.reload_config.assert_not_called()

        assert_report_item_list_equal(
            self.mock_reporter.report_item_list,
            [
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_DISTRIBUTION_STARTED,
                    {}
                ),
                (
                    severity.INFO,
                    report_codes.COROSYNC_CONFIG_ACCEPTED_BY_NODE,
                    {"node": nodes[0]}
                ),
            ]
        )
