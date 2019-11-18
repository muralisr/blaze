from blaze.action import ActionSpace
from blaze.config.config import get_config
from blaze.config.client import get_random_client_environment
from blaze.environment.environment import Environment
from blaze.environment.observation import get_observation_space
from blaze.model.model import ModelInstance, SavedModel

from tests.mocks.agent import MockAgent
from tests.mocks.config import get_env_config


class TestModelInstance:
    def setup(self):
        self.client_environment = get_random_client_environment()
        self.env_config = get_env_config()
        self.config = get_config(self.env_config, self.client_environment)
        self.trainable_push_groups = self.env_config.trainable_push_groups

    def test_init(self):
        action_space = ActionSpace(self.env_config.push_groups)
        mock_agent = MockAgent(action_space)
        m = ModelInstance(mock_agent, self.config)
        assert isinstance(m, ModelInstance)
        assert m.agent is mock_agent
        assert not m._policy

    def test_policy(self):
        observation_space = get_observation_space()
        action_space = ActionSpace(self.trainable_push_groups)
        mock_agent = MockAgent(action_space)
        m = ModelInstance(mock_agent, self.config)
        policy = m.policy
        assert policy
        assert all(observation_space.contains(obs) for obs in mock_agent.observations)

    def test_push_policy_returns_cached_policy(self):
        action_space = ActionSpace(self.trainable_push_groups)
        mock_agent = MockAgent(action_space)
        m = ModelInstance(mock_agent, self.config)
        first_policy = m.policy
        second_policy = m.policy
        assert first_policy is second_policy


class TestSavedModel:
    def test_create(self):
        saved_model = SavedModel(MockAgent, Environment, "/tmp/model_location", {})
        assert saved_model
        assert isinstance(saved_model, SavedModel)

    def test_instantiate_creates_model_with_given_environment(self):
        env_config = get_env_config()
        client_env = get_random_client_environment()
        config = get_config(env_config, client_env)

        saved_model = SavedModel(MockAgent, Environment, "/tmp/model_location", {})
        model_instance = saved_model.instantiate(config)
        assert isinstance(model_instance, ModelInstance)
        assert isinstance(model_instance.agent, MockAgent)
        assert model_instance.agent.kwargs["env"] == Environment
        assert model_instance.agent.kwargs["config"] == {"env_config": config}
        assert model_instance.agent.file_path == saved_model.location
        assert model_instance.config == config
