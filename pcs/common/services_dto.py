from typing import (
    List,
    Optional,
)

from dataclasses import dataclass

from pcs.common.interface.dto import DataTransferObject


@dataclass(frozen=True)
class ServiceStatusDto(DataTransferObject):
    service: str
    installed: Optional[bool]
    enabled: Optional[bool]
    running: Optional[bool]


@dataclass(frozen=True)
class ServicesInfoResultDto(DataTransferObject):
    services: List[ServiceStatusDto]
