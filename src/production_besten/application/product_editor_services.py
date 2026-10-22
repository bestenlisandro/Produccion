class ProductEditorService:
    def __init__(self, factory):
        self.factory = factory

    def read(self, org, plant, project):
        with self.factory() as uow:
            return uow.editor_detail(org, plant, project)

    def options(self, org, plant):
        with self.factory() as uow:
            return uow.editor_options(org, plant)

    def execute(self, org, plant, actor, key, project, action, body):
        with self.factory() as uow:
            return uow.editor_execute(org, plant, actor, key, project, action, body)
