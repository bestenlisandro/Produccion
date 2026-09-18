from production_besten.application.ports import UnitOfWorkFactory
from production_besten.domain.product_definition import (
    CreateProductDefinitionRevision,
    CreateProductionBatch,
    CreateProject,
    CreateRequiredOperation,
    CreateRequiredOperationPhase,
    DefineBatchRoute,
    DefinitionMutationResult,
    ProductDefinitionRevisionResult,
)


class _Service:
    method: str

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command):
        command.validate()
        with self._factory() as unit_of_work:
            return getattr(unit_of_work, self.method)(command)


class CreateProjectService(_Service):
    method = "create_project"


class CreateProductionBatchService(_Service):
    method = "create_production_batch"


class DefineBatchRouteService(_Service):
    method = "define_batch_route"


class CreateRequiredOperationService(_Service):
    method = "create_required_operation"


class CreateRequiredOperationPhaseService(_Service):
    method = "create_required_operation_phase"


class CreateProductDefinitionRevisionService(_Service):
    method = "create_product_definition_revision"
