class ProjectIntakeService:
    def __init__(self, factory):
        self.factory = factory

    def execute(self, command):
        with self.factory() as uow:
            return uow.execute_intake(command)

    def list(self, organization_id, plant_id, **filters):
        with self.factory() as uow:
            return uow.list_projects(organization_id, plant_id, **filters)

    def detail(self, organization_id, plant_id, project_id):
        with self.factory() as uow:
            return uow.project_detail(organization_id, plant_id, project_id)

    def options(self, organization_id, plant_id):
        with self.factory() as uow:
            return uow.intake_options(organization_id, plant_id)
