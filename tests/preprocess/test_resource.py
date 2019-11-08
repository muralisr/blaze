from blaze.preprocess.resource import resource_list_to_push_groups
from blaze.proto import policy_service_pb2
from tests.mocks.config import get_push_groups


class TestResourceListToPushGroups:
    def setup(self):
        self.push_groups = get_push_groups()
        self.resources = [res for group in self.push_groups for res in group.resources]
        self.resources.sort(key=lambda r: r.order)

    def test_resource_list_to_push_groups(self):
        push_groups = resource_list_to_push_groups(self.resources)
        for g, group in enumerate(push_groups):
            assert group.id == g
            assert group.name == self.push_groups[g].name
            assert group.trainable
            for res, actual in zip(group.resources, self.push_groups[g].resources):
                assert res.url == actual.url
                assert res.order == actual.order
                assert res.type == actual.type
                assert res.source_id == actual.source_id
                assert res.group_id == group.id

    def test_resource_list_to_push_groups_with_domain_suffix(self):
        push_groups = resource_list_to_push_groups(self.resources, train_domain_globs=["*example.com"])
        for g, group in enumerate(push_groups):
            assert group.id == g
            assert group.name == self.push_groups[g].name
            assert group.trainable == self.push_groups[g].trainable
            for res, actual in zip(group.resources, self.push_groups[g].resources):
                assert res.url == actual.url
                assert res.order == actual.order
                assert res.type == actual.type
                assert res.source_id == actual.source_id
                assert res.group_id == group.id
