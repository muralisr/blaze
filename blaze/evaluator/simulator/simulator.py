"""
This module defines the classes and methods to implement a way to simulate
loading a webpage and simulating its page load time from a dependency graph
"""

import json
from queue import PriorityQueue
from typing import Optional

from blaze.action.policy import Policy
from blaze.config.environment import EnvironmentConfig, ResourceType
from blaze.config.client import ClientEnvironment
from blaze.logger import logger

from .request_queue import Node, RequestQueue


class Simulator:
    """
    The main class that simulates a web page load. It is initialized using an EnvironmentConfig,
    which specifies the har_resources (a flat, ordered list of resources recorded from
    blaze.chrome.devtools.capture_har or blaze.chrome.devtools.capture_har_in_mahimahi that
    includes timing information about each request).
    """

    def __init__(self, env_config: EnvironmentConfig):
        self.env_config = env_config
        self.log = logger.with_namespace("simulator")

        self.root = None
        self.node_map = {}
        self.url_to_node_map = {}
        self.create_execution_graph(env_config)

        self.pq: Optional[PriorityQueue] = None
        self.request_queue: Optional[RequestQueue] = None
        self.completed_nodes = {}
        self.pushed_nodes = {}
        self.total_time_ms = 0

        self.no_push: Optional[Simulator] = None
        self.client_env: Optional[ClientEnvironment] = None
        self.policy: Optional[Policy] = None

    def reset_simulation(self, client_env: ClientEnvironment, policy: Optional[Policy] = None):
        """
        Resets the state of the simulator with the given client environment

        :param client_env: the client environment to reset with
        :param policy: the push/prelaod policy to reset with
        """

        self.pq = PriorityQueue()
        self.request_queue = RequestQueue(client_env.bandwidth, client_env.latency)
        self.completed_nodes = {}
        self.pushed_nodes = {}
        self.total_time_ms = 0

        self.no_push = None
        self.client_env = client_env
        self.policy = policy

    def schedule_pushed_and_preloaded_resources(self, node: Node, delay: float):
        """
        Schedule all push and preload resources for a given node with the given delay.

        :param node: The node to push resources for
        :param delay: The delay to schedule each pushed resource with
        """

        push_resources = self.policy.push_set_for_resource(node.resource) if self.policy else []
        preload_resources = self.policy.preload_set_for_resource(node.resource) if self.policy else []

        if push_resources:
            self.log.debug(
                "push resources for resource",
                resource=node.resource.url,
                push_resources=[res.url for res in push_resources],
            )
        for res in push_resources:
            push_node = self.url_to_node_map.get(res.url)
            if push_node and push_node not in self.completed_nodes and push_node not in self.request_queue:
                self.pq.put((push_node.priority, push_node))
                self.request_queue.add_with_delay(push_node, delay + push_node.resource.time_to_first_byte_ms)
                self.pushed_nodes[push_node] = True
                self.log.debug(
                    "push resource",
                    time=self.total_time_ms,
                    delay=delay + push_node.resource.time_to_first_byte_ms,
                    source=node.resource.url,
                    push=res.url,
                )

        if preload_resources:
            self.log.debug(
                "preload resources for resource",
                resource=node.resource.url,
                preload_resources=[res.url for res in preload_resources],
            )
        for res in preload_resources:
            preload_node = self.url_to_node_map.get(res.url)
            if preload_node and preload_node not in self.completed_nodes and preload_node not in self.request_queue:
                self.pq.put((preload_node.priority, preload_node))
                # Same delay as parent, but adds an extra RTT because
                # the browser needs to explicitly make a request for it
                self.request_queue.add_with_delay(
                    preload_node,
                    delay + preload_node.resource.time_to_first_byte_ms + self.request_queue.rtt_latency_ms,
                )
                self.pushed_nodes[preload_node] = True
                self.log.debug(
                    "push resource",
                    time=self.total_time_ms,
                    delay=delay + preload_node.resource.time_to_first_byte_ms,
                    source=node.resource.url,
                    push=res.url,
                )

    def step_request_queue(self):
        """
        Steps through the request queue once and updates the simulator state based on the results
        """

        completed_this_step, time_ms_this_step = self.request_queue.step()

        for node in completed_this_step:
            self.completed_nodes[node] = self.total_time_ms + time_ms_this_step + node.resource.execution_ms
            self.log.debug("resource completed", resource=node.resource.url, time=self.completed_nodes[node])
            self.schedule_child_requests(node)

        # Pushed/preloaded resources don't affect the total page load time so far if they were the only objects
        # received in this iteration
        if not completed_this_step or not all(node in self.pushed_nodes for node in completed_this_step):
            self.total_time_ms += time_ms_this_step

    def schedule_child_requests(self, parent: Node):
        """
        Schedules all children for the given node

        :param parent: The node to schedule children for
        """

        fetch_delay_correction = 0
        execution_delay = 0
        last_execution_delay = 0

        for child in parent.children:
            # Server processing delay
            child_delay = child.resource.time_to_first_byte_ms
            # Amount of time the fetch was delayed since the parent finished, minus the amount of time saved
            # from pushing
            child_delay += child.resource.fetch_delay_ms - fetch_delay_correction
            # Adjust the delay to account for slowed-down execution delay (and speculative fetching)
            child_delay += (execution_delay - last_execution_delay) * (self.client_env.cpu_slowdown - 1)
            # if some of the fetch_delay overlaps with the parent script execution, delay that part of the time
            child_delay += min(parent.resource.execution_ms, child.resource.fetch_delay_ms) * (
                self.client_env.cpu_slowdown - 1
            )

            # If it was pushed, calculate its delay as the difference between
            # when it was scheduled and how much time has passed since then
            if self.pushed_nodes.get(child):
                # get the time that the pushed resource would be complete
                time_already_downloaded = self.request_queue.time_spent_downloading(child)
                time_remaining_to_download = self.request_queue.estimated_completion_time(child)
                remaining_delay_before_download = self.request_queue.remaining_delay(child)
                normal_time_spent_downloading = self.no_push.request_queue.time_spent_downloading(child)

                child_fetch_delay_correction = 0
                # case 1: pushed resource was partially downloaded at the point when this resource would have downloaded
                #         --> subtract the time saved by downloading it
                if time_already_downloaded > 0 and time_remaining_to_download > child_delay:
                    child_fetch_delay_correction = time_already_downloaded + child_delay
                # case 2: pushed resource completed downloading before this resource would have started downloading
                #         --> subtract the entire download time
                if time_already_downloaded > 0 and time_remaining_to_download < child_delay:
                    child_fetch_delay_correction = time_already_downloaded + time_remaining_to_download
                # case 3: pushed resource will finish after this resource would have finished
                #         --> add the extra time spent downloading, unless it would download faster
                if time_already_downloaded == 0 and remaining_delay_before_download >= child_delay:
                    child_fetch_delay_correction = -(remaining_delay_before_download - child_delay) + (
                        normal_time_spent_downloading - (time_remaining_to_download - remaining_delay_before_download)
                    )

                # only consider scripts and css as those are blocking and receiving them
                # earlier will affect the delay of the next objects (other objects' times
                # are still taken into account
                if child.resource.type in {ResourceType.SCRIPT, ResourceType.CSS}:
                    fetch_delay_correction += child_fetch_delay_correction
                    self.log.debug(
                        "correcting fetch delay",
                        parent=parent.resource.url,
                        resource=child.resource.url,
                        child_fetch_delay_correction=child_fetch_delay_correction,
                        total_fetch_delay_correction=fetch_delay_correction,
                    )
                self.pushed_nodes[child] = False

            if child.resource.type == ResourceType.SCRIPT:
                execution_delay += child.resource.execution_ms
                last_execution_delay = child.resource.execution_ms

            if child not in self.completed_nodes and child not in self.request_queue:
                self.log.debug(
                    "scheduled resource",
                    resource=child.resource.url,
                    delay=child_delay,
                    ttfb=child.resource.time_to_first_byte_ms,
                    fetch_delay=child.resource.fetch_delay_ms,
                    execution=child.resource.execution_ms,
                    total_time=self.total_time_ms,
                )
                self.pq.put((child.priority, child))
                self.request_queue.add_with_delay(child, child_delay)
                self.schedule_pushed_and_preloaded_resources(child, child_delay - child.resource.time_to_first_byte_ms)

    def simulate_load_time(self, client_env: ClientEnvironment, policy: Optional[Policy] = None) -> float:
        """
        Simulates the page load time of a webpage in the given client environment
        with an optional push policy to also simulate.

        :param client_env: The client environment to simulate
        :param policy: The push/preload policy to simulate
        :return: The predicted page load time in milliseconds
        """
        self.log.debug("simulating page load with client environment", **client_env._asdict())
        self.reset_simulation(client_env, policy)

        if policy:
            # First simulate it without the policy to comparing timing information
            self.no_push = Simulator(self.env_config)
            self.no_push.log.set_silence(True)
            self.no_push.simulate_load_time(client_env)

            self.log.debug("simulating page load with policy:")
            self.log.debug(json.dumps(policy.as_dict, indent=4))

        # start the initial item
        self.pq.put((self.root.priority, self.root))
        self.request_queue.add_with_delay(self.root, self.root.resource.time_to_first_byte_ms)

        # schedule push resources for the root
        self.schedule_pushed_and_preloaded_resources(self.root, self.root.resource.time_to_first_byte_ms)

        # process all subsequent requests
        while not self.pq.empty():
            _, curr_node = self.pq.get()
            while curr_node not in self.completed_nodes:
                self.step_request_queue()
            self.schedule_child_requests(curr_node)

        return self.completion_time()

    def completion_time(self, url: Optional[str] = None) -> float:
        """
        Computes the completion time up until the given URL, or until the last
        object in the page if URL is not specified

        :param url: The URL to check the completion time of (optional)
        :return: The completion time in milliseconds
        """
        if not url:
            return max(self.completed_nodes.values())
        return self.completed_nodes[self.url_to_node_map[url]]

    def create_execution_graph(self, env_config: EnvironmentConfig):
        """
        Creates the execution graph from the environment config

        :param env_config: The environment resources to consider
        :return: The root node of the execution graph
        """

        # create a map of Nodes, mapping their order (basically their ID) to a Node for that resource
        res_list = env_config.har_resources
        self.node_map = {res.order: Node(resource=res, priority=res.order, children=[]) for res in res_list}
        self.url_to_node_map = {node.resource.url: node for node in self.node_map.values()}

        # The root is the node corresponding to the 0th order
        self.root = self.node_map.get(0)

        # for each resource, unless it's the start resource, add it as a child of its initiator
        for res in res_list:
            if res != self.root.resource:
                self.node_map[res.initiator].children.append(self.node_map[res.order])

        # sort each child list by its order
        for node in self.node_map.values():
            node.children.sort(key=lambda n: n.resource.order)

    def print_execution_map(self):
        """
        Prints the execution graph
        """

        def recursive_print(root: Node, depth=0):
            """
            Recursive helper method for printing the execution map
            """
            if not root:
                return
            print(
                ("  " * depth)
                + f"({root.resource.order}, exec={root.resource.execution_ms:.3f}, "
                + f"ttfb={root.resource.time_to_first_byte_ms}, delay={root.resource.fetch_delay_ms:.3f}, "
                + f"size={root.resource.size} B, {ResourceType(root.resource.type).name}, {root.resource.url})"
            )
            for next_node in root.children:
                recursive_print(next_node, depth + 1)

        recursive_print(self.root)
