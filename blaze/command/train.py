""" Implements the commands for training """
import multiprocessing
import sys

from blaze.evaluator.analyzer import get_num_rewards
from blaze.config.config import get_config
from blaze.config.environment import EnvironmentConfig
from blaze.config.train import TrainConfig
from blaze.logger import logger as log

from . import command


@command.argument("name", help="The name of the experiment")
@command.argument(
    "--model", help="The RL technique to use while training", default="PPO", choices=["A3C", "APEX", "PPO"]
)
@command.argument(
    "--workers", help="Number of workers to use for training", default=multiprocessing.cpu_count() - 1, type=int
)
@command.argument("--timesteps", help="Maximum number of timesteps to train for", default=500000000, type=int)
@command.argument(
    "--manifest_file",
    help="A description of the website that should be trained. This should be the " "generated by `blaze preprocess`",
    required=True,
)
@command.argument("--reward_func", help="Reward function to use", default=1, choices=list(range(get_num_rewards())))
@command.argument("--resume", help="Resume training from last checkpoint", default=False, action="store_true")
@command.argument(
    "--no-resume",
    help="Start a new training session even if a previous checkpoint is available",
    default=False,
    action="store_true",
)
@command.command
def train(args):
    """
    Trains a model to generate push policies for the given website. This command takes as input the
    manifest file generated by `blaze preprocess` and outputs a model that can be served.
    """
    # check for ambiguous options
    if args.resume and args.no_resume:
        log.error("invalid options: cannot specify both --resume and --no-resume")
        sys.exit(1)

    log.info("starting train", name=args.name, model=args.model)

    # import specified model
    if args.model == "A3C":
        from blaze.model import a3c as model
    if args.model == "APEX":
        from blaze.model import apex as model
    if args.model == "PPO":
        from blaze.model import ppo as model

    # compute resume flag and initialize training
    resume = False if args.no_resume else True if args.resume else "prompt"
    train_config = TrainConfig(experiment_name=args.name, num_workers=args.workers, resume=resume)
    env_config = EnvironmentConfig.load_file(args.manifest_file)
    config = get_config(env_config, reward_func=args.reward_func)
    model.train(train_config, config)
