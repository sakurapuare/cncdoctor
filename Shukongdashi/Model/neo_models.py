from __future__ import annotations

from Shukongdashi.core.container import get_container


class Neo4j:
    def __init__(self):
        self.graph = None

    def connectDB(self):
        self.graph = get_container().graph_repository
        return self.graph

    def insertNode(self, entity, lable):
        return None

    def insertRelation(self, entity1, relation, entity2, lable1, lable2):
        repository = self.connectDB()
        if hasattr(repository, "_upsert_relation"):
            repository._upsert_relation(entity1, relation, entity2, lable1, lable2)  # noqa: SLF001
        return None

    def findNode(self, title):
        repository = self.connectDB()
        for label in ["Describe", "Xianxiang", "Yuanyin", "Errorid", "Caozuo", "GuzhangBuwei"]:
            if title in repository.list_entities(label):
                return [{"n": {"title": title}}]
        return []

    def matchItembyTitle(self, value):
        return self.findNode(value)

    def findBuquanItems(self, question_start):
        repository = self.connectDB()
        return [{"n": {"title": item}} for item in repository.search_descriptions(question_start)]

    def matchHudongItembyTitle(self, value):
        return self.findNode(value)

    def getEntityRelationbyEntity(self, value):
        return []

    def findRelationByEntity(self, entity1):
        return []

    def findRelationByEntity2(self, entity1):
        return []

    def findOtherEntities(self, entity, relation):
        repository = self.connectDB()
        return [{"n2": {"title": item}} for item in repository.find_related_from(entity, relation)]

    def findAllDescribes(self):
        repository = self.connectDB()
        return [{"m": {"title": item}} for item in repository.search_descriptions("", limit=50)]

    def findEntitiesByType(self, type):
        repository = self.connectDB()
        return [{"m": {"title": item}} for item in repository.list_entities(type)]

    def findOtherEntities2(self, entity, relation):
        repository = self.connectDB()
        return [{"n1": {"title": item}} for item in repository.find_related_to(entity, relation)]

    def findNumberOfEntities1(self, entity, relation):
        repository = self.connectDB()
        return [{"relathionCount": repository.count_related_to(entity, relation)}]
