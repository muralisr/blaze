import pytest
import tempfile
from unittest import mock

from blaze.command.train import train
from blaze.config.train import TrainConfig
from tests.mocks.config import get_env_config

class TestTrain():
  def test_train_exits_with_invalid_arguments(self):
    with pytest.raises(SystemExit):
      train([])

  def test_train_invalid_website_file(self):
    with pytest.raises(IOError):
      train(['experiment_name', '--dir', '/tmp/tmp_dir', '--website', '/non/existent/file'])

  @mock.patch('blaze.model.apex.train')
  def test_train(self, mock_train):
    env_config = get_env_config()
    train_config = TrainConfig(
      experiment_name='experiment_name',
      model_dir='/tmp/tmp_dir',
      num_cpus=4,
      max_timesteps=100,
    )
    with tempfile.NamedTemporaryFile() as env_file:
      env_config.save_file(env_file.name)
      train([
        train_config.experiment_name,
        '--dir', train_config.model_dir,
        '--cpus', str(train_config.num_cpus),
        '--timesteps', str(train_config.max_timesteps),
        '--model', 'APEX',
        '--website', env_file.name,
      ])

    mock_train.assert_called_once()
    mock_train.assert_called_with(train_config, env_config)
