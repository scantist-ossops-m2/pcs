from typing import (
    Dict,
    List,
    Union,
)

from pcs.common import reports
from pcs.lib.env import LibraryEnvironment
from pcs.lib.errors import LibraryError
from pcs.lib.resource_agent import (
    ResourceAgentFacade,
    ResourceAgentMetadata,
    UnableToGetAgentMetadata,
    UnsupportedOcfVersion,
)
from pcs.lib.resource_agent import const as ra_const
from pcs.lib.resource_agent import resource_agent_error_to_report_item
from pcs.lib.resource_agent.facade import ResourceAgentFacadeFactory


def _get_property_facade_list(
    report_processor: reports.ReportProcessor,
    factory: ResourceAgentFacadeFactory,
) -> List[ResourceAgentFacade]:
    pacemaker_daemons = [
        ra_const.PACEMAKER_BASED,
        ra_const.PACEMAKER_CONTROLD,
        ra_const.PACEMAKER_SCHEDULERD,
    ]
    cluster_property_facade_list = []
    for daemon in pacemaker_daemons:
        try:
            cluster_property_facade_list.append(
                factory.facade_from_pacemaker_daemon_name(daemon)
            )
        except (UnableToGetAgentMetadata, UnsupportedOcfVersion) as e:
            report_processor.report_list(
                [
                    resource_agent_error_to_report_item(
                        e, reports.ReportItemSeverity.error()
                    )
                ]
            )
    if report_processor.has_errors:
        raise LibraryError()
    return cluster_property_facade_list


# backward compatibility layer - export cluster property metadata in the legacy
# format
def _cluster_property_metadata_to_dict(
    metadata: ResourceAgentMetadata,
) -> Dict[str, Dict[str, Union[bool, str, List[str]]]]:
    banned_props = ["dc-version", "cluster-infrastructure"]
    readable_names = {
        "batch-limit": "Batch Limit",
        "no-quorum-policy": "No Quorum Policy",
        "symmetric-cluster": "Symmetric",
        "stonith-enabled": "Stonith Enabled",
        "stonith-action": "Stonith Action",
        "cluster-delay": "Cluster Delay",
        "stop-orphan-resources": "Stop Orphan Resources",
        "stop-orphan-actions": "Stop Orphan Actions",
        "start-failure-is-fatal": "Start Failure is Fatal",
        "pe-error-series-max": "PE Error Storage",
        "pe-warn-series-max": "PE Warning Storage",
        "pe-input-series-max": "PE Input Storage",
        "enable-acl": "Enable ACLs",
    }
    property_definition = {}
    for parameter in metadata.parameters:
        if parameter.name in banned_props:
            continue
        cluster_property: Dict[str, Union[bool, str, List[str]]] = {
            "name": parameter.name,
            "shortdesc": parameter.shortdesc or "",
            "longdesc": parameter.longdesc or "",
            "type": parameter.type,
            "default": parameter.default or "",
            "advanced": parameter.advanced,
            "readable_name": readable_names.get(parameter.name, parameter.name),
            "source": metadata.name.type,
        }
        if parameter.enum_values is not None:
            cluster_property["enum"] = parameter.enum_values
            cluster_property["type"] = "enum"
        property_definition[parameter.name] = cluster_property
    return property_definition


def get_cluster_properties_definition(env: LibraryEnvironment):
    facade_factory = ResourceAgentFacadeFactory(
        env.cmd_runner(), env.report_processor
    )
    property_dict = {}
    for facade in _get_property_facade_list(
        env.report_processor, facade_factory
    ):
        property_dict.update(
            _cluster_property_metadata_to_dict(facade.metadata)
        )
    return property_dict
