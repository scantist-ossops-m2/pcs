from unittest import TestCase
from lxml import etree

from pcs_test.tools.assertions import assert_report_item_list_equal
from pcs_test.tools import fixture

from pcs.common import reports
from pcs.lib.cib.resource import primitive
from pcs.lib.resource_agent import (
    const,
    ResourceAgentFacade,
    ResourceAgentMetadata,
    ResourceAgentName,
    ResourceAgentParameter,
)


def _fixture_metadata(name, parameters):
    return ResourceAgentMetadata(
        name=name,
        agent_exists=True,
        ocf_version=const.OCF_1_0,
        shortdesc=None,
        longdesc=None,
        parameters=parameters,
        actions=[],
    )


def _fixture_parameter(name, required, deprecated_by):
    return ResourceAgentParameter(
        name,
        shortdesc=None,
        longdesc=None,
        type="string",
        default=None,
        enum_values=None,
        required=required,
        advanced=False,
        deprecated=bool(deprecated_by),
        deprecated_by=deprecated_by,
        deprecated_desc=None,
        unique_group=None,
        reloadable=False,
    )


def _fixture_agent():
    return ResourceAgentFacade(
        _fixture_metadata(
            ResourceAgentName("standard", "provider", "type"),
            [
                _fixture_parameter("optional1_new", False, []),
                _fixture_parameter("optional1_old", False, ["optional1_new"]),
                _fixture_parameter("optional2_new", False, []),
                _fixture_parameter("optional2_old", False, ["optional2_new"]),
                _fixture_parameter("required1_new", True, []),
                _fixture_parameter("required1_old", True, ["required1_new"]),
                _fixture_parameter("required2_new", True, []),
                _fixture_parameter("required2_old", True, ["required2_new"]),
                _fixture_parameter("action", False, []),
            ],
        )
    )


def _fixture_agent_deprecated_loop():
    return ResourceAgentFacade(
        _fixture_metadata(
            ResourceAgentName("standard", "provider", "type"),
            [
                _fixture_parameter("loop1", True, ["loop1"]),
                _fixture_parameter("loop2a", True, ["loop2b"]),
                _fixture_parameter("loop2b", True, ["loop2a"]),
                _fixture_parameter("loop3a", True, ["loop3b"]),
                _fixture_parameter("loop3b", True, ["loop3c"]),
                _fixture_parameter("loop3c", True, ["loop3a"]),
            ],
        )
    )


def _fixture_stonith():
    return ResourceAgentFacade(
        _fixture_metadata(
            ResourceAgentName("stonith", None, "type"),
            [
                _fixture_parameter("required", True, []),
                _fixture_parameter("optional", False, []),
                _fixture_parameter("action", True, []),
            ],
        )
    )


def _fixture_void(stonith=False):
    return ResourceAgentFacade(
        ResourceAgentMetadata(
            ResourceAgentName("stonith", None, "type")
            if stonith
            else ResourceAgentName("standard", "provider", "type"),
            agent_exists=False,
            ocf_version=const.OCF_1_0,
            shortdesc=None,
            longdesc=None,
            parameters=[],
            actions=[],
        )
    )


class ValidateResourceInstanceAttributesCreate(TestCase):
    # pylint: disable=no-self-use
    def test_set_empty_string(self):
        options = [
            "required1_new",
            "required2_old",
            "optional1_new",
            "optional1_old",
            "unknown",
        ]
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {name: "" for name in options},
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required2_old",
                    replaced_by=["required2_new"],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="optional1_old",
                    replaced_by=["optional1_new"],
                ),
            ],
        )

    def test_set_all_required_params_one_deprecated_one_new(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "required1_new": "A",
                    "required2_old": "B",
                },
                etree.Element("resources"),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required2_old",
                    replaced_by=["required2_new"],
                ),
            ],
        )

    def test_set_all_required_and_optional_params_one_deprecated_one_new(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "required1_new": "A",
                    "required2_old": "B",
                    "optional1_new": "C",
                    "optional2_old": "D",
                },
                etree.Element("resources"),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required2_old",
                    replaced_by=["required2_new"],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="optional2_old",
                    replaced_by=["optional2_new"],
                ),
            ],
        )

    def test_set_all_required_and_optional_params_both_deprecated_and_new(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "required1_new": "A",
                    "required1_old": "B",
                    "required2_new": "C",
                    "required2_old": "D",
                    "optional1_new": "E",
                    "optional1_old": "F",
                    "optional2_new": "G",
                    "optional2_old": "H",
                },
                etree.Element("resources"),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required1_old",
                    replaced_by=["required1_new"],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required2_old",
                    replaced_by=["required2_new"],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="optional1_old",
                    replaced_by=["optional1_new"],
                ),
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="optional2_old",
                    replaced_by=["optional2_new"],
                ),
            ],
        )

    def test_set_unknown_params(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "required1_new": "A",
                    "required2_new": "B",
                    "unknown1": "C",
                    "unknown2": "D",
                },
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown1", "unknown2"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
            ],
        )

    def test_set_unknown_params_forced(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "required1_new": "A",
                    "required2_new": "B",
                    "unknown1": "C",
                    "unknown2": "D",
                },
                etree.Element("resources"),
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.INVALID_OPTIONS,
                    option_names=["unknown1", "unknown2"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
            ],
        )

    def test_missing_required(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {},
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="resource",
                    option_names=["required1_new", "required1_old"],
                    deprecated_names=["required1_old"],
                ),
                fixture.error(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="resource",
                    option_names=["required2_new", "required2_old"],
                    deprecated_names=["required2_old"],
                ),
            ],
        )

    def test_missing_required_forced(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {},
                etree.Element("resources"),
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    option_type="resource",
                    option_names=["required1_new", "required1_old"],
                    deprecated_names=["required1_old"],
                ),
                fixture.warn(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    option_type="resource",
                    option_names=["required2_new", "required2_old"],
                    deprecated_names=["required2_old"],
                ),
            ],
        )

    def test_deprecation_loop(self):
        # Meta-data are broken - there are obsoleting loops. The point of the
        # test is to make sure pcs does not crash or loop forever. Error
        # reports are not that important, since meta-data are broken.
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent_deprecated_loop(),
                {
                    "loop3b": "value",
                },
                etree.Element("resources"),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="loop3b",
                    replaced_by=["loop3c"],
                ),
            ],
        )

    def test_stonith_reports(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_stonith(),
                {
                    "unknown": "option",
                },
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown"],
                    allowed=["action", "optional", "required"],
                    option_type="stonith",
                    allowed_patterns=[],
                ),
                fixture.error(
                    reports.codes.REQUIRED_OPTIONS_ARE_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_names=["required"],
                ),
            ],
        )

    def test_resource_action_not_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_agent(),
                {
                    "action": "reboot",
                    "required1_new": "value",
                    "required2_new": "value",
                },
                etree.Element("resources"),
            ),
            [],
        )

    def test_stonith_action_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_stonith(),
                {
                    "action": "reboot",
                    "required": "value",
                },
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.DEPRECATED_OPTION,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )

    def test_stonith_action_deprecated_forced(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_stonith(),
                {
                    "action": "reboot",
                    "required": "value",
                },
                etree.Element("resources"),
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )

    def test_stonith_action_not_set(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_stonith(),
                {
                    "required": "value",
                },
                etree.Element("resources"),
            ),
            [],
        )

    def test_void_checks_for_empty_strings(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_void(),
                {
                    "param1": "",
                    "param2": "value2",
                },
                etree.Element("resources"),
            ),
            [],
        )

    def test_void_stonith_check_for_action(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_create(
                _fixture_void(stonith=True),
                {
                    "param1": "",
                    "action": "reboot",
                    "param2": "value2",
                },
                etree.Element("resources"),
            ),
            [
                fixture.error(
                    reports.codes.DEPRECATED_OPTION,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )


class ValidateResourceInstanceAttributesUpdate(TestCase):
    _NAME = "a-resource"

    def _fixture_resources(self, parameters):
        resources_el = etree.Element("resources")
        primitive_el = etree.SubElement(
            resources_el, "primitive", dict(id=self._NAME)
        )
        nvset_el = etree.SubElement(primitive_el, "instance_attributes")
        for name, value in parameters.items():
            etree.SubElement(nvset_el, "nvpair", dict(name=name, value=value))
        return resources_el

    def test_remove_required_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "required2_old": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="resource",
                    option_names=["required2_new", "required2_old"],
                    deprecated_names=["required2_old"],
                ),
            ],
        )

    def test_remove_required_new(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "required1_new": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.REQUIRED_OPTION_OF_ALTERNATIVES_IS_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="resource",
                    option_names=["required1_new", "required1_old"],
                    deprecated_names=["required1_old"],
                ),
            ],
        )

    def test_remove_required_deprecated_set_new(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "required2_old": "",
                    "required2_new": "B",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [],
        )

    def test_remove_required_new_set_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "required1_old": "A",
                    "required1_new": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="required1_old",
                    replaced_by=["required1_new"],
                ),
            ],
        )

    def test_set_optional(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "optional1_new": "A",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [],
        )

    def test_remove_optional(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "optional1_new": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                    }
                ),
            ),
            [],
        )

    def test_dont_report_previously_missing_required(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "optional1_new": "A",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                    }
                ),
            ),
            [],
        )

    def test_set_unknown_params(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "unknown1": "C",
                    "unknown2": "D",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                        "unknown1": "c",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown2"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
            ],
        )

    def test_remove_unknown_params(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "unknown1": "",
                    "unknown2": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                        "unknown1": "C",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown2"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
            ],
        )

    def test_unknown_params_forced(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "unknown1": "",
                    "unknown2": "D",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "A",
                        "required2_old": "B",
                        "unknown1": "C",
                    }
                ),
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.INVALID_OPTIONS,
                    option_names=["unknown2"],
                    allowed=[
                        "action",
                        "optional1_new",
                        "optional1_old",
                        "optional2_new",
                        "optional2_old",
                        "required1_new",
                        "required1_old",
                        "required2_new",
                        "required2_old",
                    ],
                    option_type="resource",
                    allowed_patterns=[],
                ),
            ],
        )

    def test_deprecation_loop(self):
        # Meta-data are broken - there are obsoleting loops. The point of the
        # test is to make sure pcs does not crash or loop forever. Error
        # reports are not that important, since meta-data are broken.
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent_deprecated_loop(),
                {
                    "loop3b": "value",
                },
                self._NAME,
                self._fixture_resources({}),
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="resource",
                    option_name="loop3b",
                    replaced_by=["loop3c"],
                ),
            ],
        )

    def test_stonith_reports(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "required": "",
                    "unknown": "value",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required": "A",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.INVALID_OPTIONS,
                    force_code=reports.codes.FORCE,
                    option_names=["unknown"],
                    allowed=["action", "optional", "required"],
                    option_type="stonith",
                    allowed_patterns=[],
                ),
                fixture.error(
                    reports.codes.REQUIRED_OPTIONS_ARE_MISSING,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_names=["required"],
                ),
            ],
        )

    def test_resource_action_not_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_agent(),
                {
                    "action": "reboot",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required1_new": "value",
                        "required2_new": "value",
                    }
                ),
            ),
            [],
        )

    def test_stonith_action_deprecated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "action": "reboot",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "action": "offon",
                        "required": "value",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.DEPRECATED_OPTION,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )

    def test_stonith_action_deprecated_forced(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "action": "reboot",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "action": "offon",
                        "required": "value",
                    }
                ),
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.DEPRECATED_OPTION,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )

    def test_stonith_action_add(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "action": "reboot",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "required": "value",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.DEPRECATED_OPTION,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )

    def test_stonith_action_empty(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "action": "",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "action": "reboot",
                        "required": "value",
                    }
                ),
            ),
            [],
        )

    def test_stonith_action_not_updated(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_stonith(),
                {
                    "optional": "value",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "action": "reboot",
                        "required": "value",
                    }
                ),
            ),
            [],
        )

    def test_void_stonith_check_for_action(self):
        assert_report_item_list_equal(
            primitive.validate_resource_instance_attributes_update(
                _fixture_void(stonith=True),
                {
                    "param1": "",
                    "action": "reboot",
                    "param2": "value2",
                },
                self._NAME,
                self._fixture_resources(
                    {
                        "action": "reboot",
                        "required": "value",
                    }
                ),
            ),
            [
                fixture.error(
                    reports.codes.DEPRECATED_OPTION,
                    force_code=reports.codes.FORCE,
                    option_type="stonith",
                    option_name="action",
                    replaced_by=["pcmk_off_action", "pcmk_reboot_action"],
                ),
            ],
        )


class ValidateUniqueInstanceAttributes(TestCase):
    # pylint: disable=protected-access
    cib = etree.fromstring(
        """
        <resources>
            <primitive class="ocf" provider="pacemaker" type="pcstest" id="R1">
                <instance_attributes>
                    <nvpair name="addr" value="127.0.0.1" />
                    <nvpair name="port" value="53" />
                    <nvapir name="something" value="else" />
                    <nvpair name="unique" value="value1"/>
                </instance_attributes>
            </primitive>
            <primitive class="ocf" provider="pacemaker" type="pcstest2" id="R2">
                <instance_attributes>
                    <nvpair name="addr" value="127.0.0.1" />
                    <nvpair name="port" value="53" />
                    <nvapir name="something" value="else" />
                    <nvpair name="unique" value="value1"/>
                </instance_attributes>
            </primitive>
            <clone id="G1-clone">
                <group id="G1">
                    <primitive class="ocf" provider="pacemaker" type="pcstest"
                        id="R3"
                    >
                        <instance_attributes>
                            <nvpair name="addr" value="127.0.0.1" />
                            <nvpair name="port" value="53" />
                            <nvapir name="something" value="else" />
                        </instance_attributes>
                    </primitive>
                </group>
            </clone>
        </resources>
        """
    )

    @staticmethod
    def _fixture_metadata():
        def _parameter(name, unique_group):
            return ResourceAgentParameter(
                name,
                shortdesc=None,
                longdesc=None,
                type="string",
                default=None,
                enum_values=None,
                required=False,
                advanced=False,
                deprecated=False,
                deprecated_by=None,
                deprecated_desc=None,
                unique_group=unique_group,
                reloadable=False,
            )

        return ResourceAgentMetadata(
            name=ResourceAgentName("ocf", "pacemaker", "pcstest"),
            agent_exists=True,
            ocf_version=const.OCF_1_0,
            shortdesc=None,
            longdesc=None,
            parameters=[
                _parameter("addr", "connection"),
                _parameter("port", "connection"),
                _parameter("something", None),
                _parameter("unique", "one-attr"),
            ],
            actions=[],
        )

    def test_no_report_on_different_values(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"addr": "127.0.0.2", "port": "54", "unique": "value2"},
                self.cib,
            ),
            [],
        )

    def test_no_report_when_not_all_values_in_group_are_same(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"addr": "127.0.0.2", "port": "53", "unique": "value2"},
                self.cib,
            ),
            [],
        )

    def test_report_same_values_from_same_agent_only(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"addr": "127.0.0.1", "port": "53", "unique": "value1"},
                self.cib,
            ),
            [
                fixture.error(
                    reports.codes.RESOURCE_INSTANCE_ATTR_GROUP_VALUE_NOT_UNIQUE,
                    force_code=reports.codes.FORCE,
                    group_name="connection",
                    instance_attrs_map={"addr": "127.0.0.1", "port": "53"},
                    agent_name="ocf:pacemaker:pcstest",
                    resource_id_list=["R1", "R3"],
                ),
                fixture.error(
                    reports.codes.RESOURCE_INSTANCE_ATTR_VALUE_NOT_UNIQUE,
                    force_code=reports.codes.FORCE,
                    instance_attr_name="unique",
                    instance_attr_value="value1",
                    agent_name="ocf:pacemaker:pcstest",
                    resource_id_list=["R1"],
                ),
            ],
        )

    def test_report_same_values_from_same_agent_only_forced(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"addr": "127.0.0.1", "port": "53", "unique": "value1"},
                self.cib,
                force=True,
            ),
            [
                fixture.warn(
                    reports.codes.RESOURCE_INSTANCE_ATTR_GROUP_VALUE_NOT_UNIQUE,
                    group_name="connection",
                    instance_attrs_map={"addr": "127.0.0.1", "port": "53"},
                    agent_name="ocf:pacemaker:pcstest",
                    resource_id_list=["R1", "R3"],
                ),
                fixture.warn(
                    reports.codes.RESOURCE_INSTANCE_ATTR_VALUE_NOT_UNIQUE,
                    instance_attr_name="unique",
                    instance_attr_value="value1",
                    agent_name="ocf:pacemaker:pcstest",
                    resource_id_list=["R1"],
                ),
            ],
        )

    def test_not_defined_values(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"addr": "127.0.0.2"},
                self.cib,
            ),
            [],
        )

    def test_ignore_own_values_on_update(self):
        assert_report_item_list_equal(
            primitive._validate_unique_instance_attributes(
                self._fixture_metadata(),
                {"unique": "value1"},
                self.cib,
                resource_id="R1",
            ),
            [],
        )
