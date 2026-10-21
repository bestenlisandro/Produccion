from __future__ import annotations

from typing import Protocol

from production_besten.domain.master_data import MasterDataCommand, MasterDataResult


class MasterDataUnitOfWork(Protocol):
    def __enter__(self) -> "MasterDataUnitOfWork": ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
    def execute(self, command: MasterDataCommand) -> MasterDataResult: ...
    def snapshot(self, organization_id, plant_id) -> dict: ...


class MasterDataUnitOfWorkFactory(Protocol):
    def __call__(self) -> MasterDataUnitOfWork: ...


class MasterDataCommandService:
    def __init__(self, factory: MasterDataUnitOfWorkFactory) -> None:
        self.factory = factory

    def execute(self, command: MasterDataCommand) -> MasterDataResult:
        with self.factory() as unit_of_work:
            return unit_of_work.execute(command)


class MasterDataQueryService:
    def __init__(self, factory: MasterDataUnitOfWorkFactory) -> None:
        self.factory = factory

    def snapshot(self, organization_id, plant_id) -> dict:
        with self.factory() as unit_of_work:
            return unit_of_work.snapshot(organization_id, plant_id)
