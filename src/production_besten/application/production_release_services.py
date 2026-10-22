from production_besten.domain.errors import ProductDefinitionConflict


class ProductionReleaseConflict(ProductDefinitionConflict):
    pass


class ProductionReleaseVersionConflict(ProductDefinitionConflict):
    pass


class ProductionReleaseService:
    def __init__(self,factory):self.factory=factory

    def read(self,org,plant,project=None):
        with self.factory() as uow:
            rows=uow.readiness(org,plant)
            if project is None:return rows
            from production_besten.domain.errors import EntityNotFound
            if project not in rows:raise EntityNotFound()
            return rows[project]

    def execute(self,org,plant,actor,key,project,action,body):
        with self.factory() as uow:return uow.release_project(org,plant,actor,key,project,action,body)
