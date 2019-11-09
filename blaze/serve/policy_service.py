""" Defines classes and methods to instantiate, evaluate, and serve push policies """
import json
from typing import Dict

import grpc

from blaze.config import client
from blaze.config import environment
from blaze.model.model import ModelInstance, SavedModel
from blaze.proto import policy_service_pb2
from blaze.proto import policy_service_pb2_grpc


class PolicyService(policy_service_pb2_grpc.PolicyServiceServicer):
    """
    Implements the PolicyServerServicer interface to satsify the proto-defined RPC interface for
    serving push policies
    """

    def __init__(self, saved_model: SavedModel):
        self.saved_model = saved_model
        self.policies: Dict[str, policy_service_pb2.Policy] = {}

    def GetPolicy(self, request: policy_service_pb2.Page, context: grpc.ServicerContext) -> policy_service_pb2.Policy:
        if request.url not in self.policies:
            self.policies[request.url] = self.create_policy(request)
        return self.policies[request.url]

    def create_policy(self, page: policy_service_pb2.Page) -> policy_service_pb2.Policy:
        """ Creates and formats a push policy for the given page """
        model = self.create_model_instance(page)
        response = policy_service_pb2.Policy()
        response.policy = json.dumps(model.policy.as_dict)
        return response

    def create_model_instance(self, page: policy_service_pb2.Page) -> ModelInstance:
        """ Instantiates a model for the given page """
        # convert page network_type and device_speed to client environment
        client_environment = client.ClientEnvironment(
            device_speed=client.DeviceSpeed(page.device_speed),
            network_type=client.NetworkType(page.network_type),
            network_speed=client.NetworkSpeed(page.network_speed),
            bandwidth=page.bandwidth_kbps,
            latency=page.latency_ms,
        )
        # create environment config
        env_config = environment.EnvironmentConfig.deserialize(page.manifest)
        # instantiate a model for this config
        return self.saved_model.instantiate(env_config, client_environment)
