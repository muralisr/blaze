"""
This module defines the classes and methods to implement a way to simulate
loading a webpage and simulating its page load time from a dependency graph
"""

import copy
import json
from queue import PriorityQueue
from typing import List, Optional, Set, Tuple

from blaze.action.policy import Policy
from blaze.config.environment import EnvironmentConfig, ResourceType
from blaze.config.client import ClientEnvironment
from blaze.logger import logger

from .request_queue import Node, RequestQueue


class Simulator:
    """
    The main class that simulates a web page load. It is initialized using an EnvironmentConfig,
    which specifies the har_resources (a flat, ordered list of resources recorded from
    blaze.chrome.devtools.capture_har or blaze.chrome.devtools.capture_har_in_replay_server that
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
        self.cached_urls = set()

        self.no_push: Optional[Simulator] = None
        self.client_env: Optional[ClientEnvironment] = None
        self.policy: Optional[Policy] = None

        # Speed Index variables
        # time and added_viewport go in lock-step.
        # when a new image is drawn on screen, it's contribution to
        # the viewport is pushed into added_viewport and the time
        # this happened is stored in index_time.
        self.speed_index_time = []
        self.speed_index_added_viewport = []

    def reset_simulation(
        self, client_env: ClientEnvironment, policy: Optional[Policy] = None, cached_urls: Optional[Set[str]] = None
    ):
        """
        Resets the state of the simulator with the given client environment

        :param client_env: the client environment to reset with
        :param policy: the push/prelaod policy to reset with
        :param cached_urls: the cached URLs to not download
        """

        self.pq = PriorityQueue()
        self.request_queue = RequestQueue(client_env.bandwidth, client_env.latency)
        self.completed_nodes = {}
        self.pushed_nodes = {}
        self.total_time_ms = 0
        self.speed_index_time = []
        self.speed_index_added_viewport = []
        self.cached_urls = cached_urls if cached_urls else set()

        self.no_push = None
        self.client_env = client_env
        self.policy = copy.deepcopy(policy) if policy else None

    def schedule_pushed_and_preloaded_resources(
        self, node: Node, delay: float, dry_run=False
    ) -> Optional[List[Tuple[Node, float]]]:
        """
        Schedule all push and preload resources for a given node with the given delay.

        :param node: The node to push resources for
        :param delay: The delay to schedule each pushed resource with
        :param dry_run: Only return the list of resources to push with their delay
        """

        push_resources = self.policy.push_set_for_resource(node.resource) if self.policy else []
        preload_resources = self.policy.preload_set_for_resource(node.resource) if self.policy else []
        dry_run_list = []

        if push_resources and not dry_run:
            self.log.verbose(
                "push resources for resource",
                resource=node.resource.url,
                push_resources=[res.url for res in push_resources],
            )
        for res in push_resources:
            push_node = self.url_to_node_map.get(res.url)
            if push_node and push_node not in self.completed_nodes and push_node not in self.request_queue:
                cached = push_node.resource.url in self.cached_urls
                if cached:
                    continue
                push_delay = delay + push_node.resource.time_to_first_byte_ms
                if dry_run:
                    dry_run_list.append((push_node, push_delay))
                else:
                    self.pq.put((push_node.priority, push_node))
                    self.request_queue.add_with_delay(push_node, push_delay)
                    self.pushed_nodes[push_node] = True
                    self.log.verbose(
                        "push resource",
                        time=self.total_time_ms,
                        delay=push_delay,
                        source=node.resource.url,
                        push=res.url,
                    )

        if preload_resources and not dry_run:
            self.log.verbose(
                "preload resources for resource",
                resource=node.resource.url,
                preload_resources=[res.url for res in preload_resources],
            )
        for res in preload_resources:
            preload_node = self.url_to_node_map.get(res.url)
            if preload_node and preload_node not in self.completed_nodes and preload_node not in self.request_queue:
                # Same delay as parent, but adds an extra RTT because the browser needs
                # to explicitly make a request for it
                cached = preload_node.resource.url in self.cached_urls
                if cached:
                    continue
                preload_delay = delay + preload_node.resource.time_to_first_byte_ms + self.request_queue.rtt_latency_ms
                if dry_run:
                    dry_run_list.append((preload_node, preload_delay))
                else:
                    self.pq.put((preload_node.priority, preload_node))
                    self.request_queue.add_with_delay(preload_node, preload_delay)
                    self.pushed_nodes[preload_node] = True
                    self.log.verbose(
                        "push resource",
                        time=self.total_time_ms,
                        delay=delay + preload_node.resource.time_to_first_byte_ms,
                        source=node.resource.url,
                        push=res.url,
                    )

        return dry_run_list if dry_run else None

    def step_request_queue(self, get_speed_index: Optional[bool] = False):
        """
        Steps through the request queue once and updates the simulator state based on the results
        """

        completed_this_step, time_ms_this_step = self.request_queue.step()
        self.total_time_ms += time_ms_this_step

        for node in completed_this_step:
            self.completed_nodes[node] = self.total_time_ms + node.resource.execution_ms
            # use the following if html should be counted
            if False and node.resource.url == 'https://www.homedepot.com/' or node.resource.url == 'https://www.nytimes.com/' or node.resource.url == 'https://www.walgreens.com/':
                self.log.debug("appending main page to speed_index_time ", viewport=node.resource.viewport_occupied, speed_index_time=self.speed_index_time, appended_time=self.total_time_ms)
                self.log.debug("landing page time is x and appending with viewport", time=self.total_time_ms,viewport=node.resource.viewport_occupied)
                self.speed_index_time.append(self.total_time_ms)
                self.speed_index_added_viewport.append(node.resource.viewport_occupied)
            elif get_speed_index and node.resource.viewport_occupied > 0.0: # we are tracking speed index and the currently completed node contributes a non-zero amount to the viewport which means it affects ths speed index
                self.log.debug("appending something to speed_index_time ", viewport=node.resource.viewport_occupied, speed_index_time=self.speed_index_time, appended_time=self.total_time_ms)
                self.speed_index_time.append(self.total_time_ms)
                self.speed_index_added_viewport.append(node.resource.viewport_occupied)
            # elif get_speed_index:
            #     self.log.debug("SI is true, but element viewport occupied is 0")
            # if node.resource.url == 'https://www.walgreens.com/common/react/assets/images/walgreens_logo.png?o=acs':
            #     self.log.debug("XXXXXXXXXX ", resource=node.resource)
            #self.log.debug("resource completed with viewport occupied as ", resource=node.resource.url, viewport_occupied=node.resource.viewport_occupied)
            self.log.verbose("resource completed", resource=node.resource.url, time=self.completed_nodes[node])

    def schedule_child_requests(self, parent: Node, dry_run=False) -> Optional[List[Tuple[Node, float]]]:
        """
        Schedules all children for the given node

        :param parent: The node to schedule children for
        :param dry_run: Only return the list of nodes and delays instead of actually scheduling them
        """

        fetch_delay_correction = 0
        execution_delay = 0
        last_execution_delay = 0
        dry_run_list = []

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
                # get the time that the pushed resource has already spent downloading
                time_already_downloaded = self.request_queue.time_spent_downloading(child)

                # collect the requests for the whole level, schedule them, and estimate remaining download time
                if not dry_run:
                    nodes_to_schedule = self.schedule_child_requests(parent, dry_run=True)
                    rq = self.request_queue.copy()
                    for (node, delay) in nodes_to_schedule:
                        if node not in rq and node not in self.completed_nodes:
                            rq.add_with_delay(node, delay)
                    time_til_complete, time_remaining_to_download = rq.estimated_completion_time(child)
                    remaining_delay_before_download = time_til_complete - time_remaining_to_download
                else:
                    time_til_complete, time_remaining_to_download = self.request_queue.estimated_completion_time(child)
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
                if time_already_downloaded == 0:
                    child_fetch_delay_correction = -(remaining_delay_before_download - child_delay) + (
                        normal_time_spent_downloading - time_remaining_to_download
                    )

                # only consider scripts and css as those are blocking and receiving them
                # earlier will affect the delay of the next objects (other objects' times
                # are still taken into account
                if child.resource.type in {ResourceType.SCRIPT, ResourceType.CSS}:
                    fetch_delay_correction += child_fetch_delay_correction
                    if not dry_run:
                        self.log.verbose(
                            "correcting fetch delay",
                            parent=parent.resource.url,
                            resource=child.resource.url,
                            time_already_downloaded=time_already_downloaded,
                            time_remaining_to_download=time_remaining_to_download,
                            remaining_delay_before_download=remaining_delay_before_download,
                            normal_time_spent_downloading=normal_time_spent_downloading,
                            child_delay=child_delay,
                            child_fetch_delay_correction=child_fetch_delay_correction,
                            total_fetch_delay_correction=fetch_delay_correction,
                        )
                if not dry_run:
                    self.pushed_nodes[child] = False

            if child.resource.type in {ResourceType.SCRIPT}:
                execution_delay += child.resource.execution_ms
                last_execution_delay = child.resource.execution_ms

            if child not in self.completed_nodes and child not in self.request_queue:
                cached = child.resource.url in self.cached_urls
                if dry_run:
                    if not cached:
                        dry_run_list.append((child, child_delay))
                    dry_run_list.extend(
                        self.schedule_pushed_and_preloaded_resources(
                            child, child_delay - child.resource.time_to_first_byte_ms, dry_run=True
                        )
                    )
                else:
                    self.log.verbose(
                        "scheduled resource",
                        resource=child.resource.url,
                        parent=parent.resource.url,
                        delay=child_delay,
                        ttfb=child.resource.time_to_first_byte_ms,
                        fetch_delay=child.resource.fetch_delay_ms,
                        execution=child.resource.execution_ms,
                        execution_delay=execution_delay,
                        last_execution_delay=last_execution_delay,
                        total_time=self.total_time_ms,
                    )
                    self.pq.put((child.priority, child))
                    self.request_queue.add_with_delay(child, child_delay, cached=cached)
                    self.schedule_pushed_and_preloaded_resources(
                        child, child_delay - child.resource.time_to_first_byte_ms
                    )

        return dry_run_list if dry_run else None

    def simulate_speed_index(self,
        client_env: ClientEnvironment,
        policy: Optional[Policy] = None,
        cached_urls: Optional[Set[str]] = None,
    ) -> float:
        """
        Simulates the speed index of a webpage in the given client environment
        with an optional push policy to also simulate.

        :param client_env: The client environment to simulate
        :param policy: The push/preload policy to simulate
        :param cached_urls: Optional set of URLs to be considered in cache. 
        :return: The predicted speed index as a floating point value
        """
        self.log.verbose("simulating speed index with client environment", **client_env._asdict())
        self.reset_simulation(client_env, policy=policy, cached_urls=cached_urls)

        if policy:
            # First simulate it without the policy to comparing timing information
            self.no_push = Simulator(self.env_config)
            self.no_push.log.set_silence(True)
            self.no_push.simulate_speed_index(client_env)

            self.log.verbose("simulating speed index with policy:")
            self.log.verbose(json.dumps(policy.as_dict, indent=4))

        # start the initial item
        self.pq.put((self.root.priority, self.root))
        self.request_queue.add_with_delay(self.root, self.root.resource.time_to_first_byte_ms)

        # schedule push resources for the root
        self.schedule_pushed_and_preloaded_resources(self.root, self.root.resource.time_to_first_byte_ms)

        # process all subsequent requests
        while not self.pq.empty():
            _, curr_node = self.pq.get()
            while curr_node not in self.completed_nodes:
                self.step_request_queue(get_speed_index=True)
            self.schedule_child_requests(curr_node)
        return self.compute_speed_index()

    def simulate_load_time(
        self,
        client_env: ClientEnvironment,
        policy: Optional[Policy] = None,
        cached_urls: Optional[Set[str]] = None,
        use_aft: Optional[bool] = False,
    ) -> float:
        """
        Simulates the page load time of a webpage in the given client environment
        with an optional push policy to also simulate.

        :param client_env: The client environment to simulate
        :param policy: The push/preload policy to simulate
        :return: The predicted page load time in milliseconds
        """
        self.log.verbose("simulating page load with client environment", **client_env._asdict())
        self.reset_simulation(client_env, policy=policy, cached_urls=cached_urls)


        if policy:
            # First simulate it without the policy to comparing timing information
            self.no_push = Simulator(self.env_config)
            self.no_push.log.set_silence(True)
            self.no_push.simulate_load_time(client_env)

            self.log.verbose("simulating page load with policy:")
            self.log.verbose(json.dumps(policy.as_dict, indent=4))

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

        if use_aft:
            critical_nodes = [node for node in self.node_map.values() if node.resource.critical]
            if critical_nodes:
                return max(self.completed_nodes[node] for node in critical_nodes)
            self.log.warn("requested above the fold time, but no nodes marked `critical` found")
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
        res_list = sorted(env_config.har_resources, key=lambda r: r.order)
        self.node_map = {
            res.order: Node(resource=res, priority=res.order, children=[]) for res in res_list if res.order == 0
        }

        # The root is the node corresponding to the 0th order
        self.root = self.node_map.get(0)

        # for each resource, unless it's the start resource, add it as a child of its initiator
        for res in res_list:
            if res != self.root.resource:
                self.node_map[res.order] = Node(
                    resource=res, priority=res.order, children=[], parent=self.node_map.get(res.initiator, None)
                )
                self.node_map[res.initiator].children.append(self.node_map[res.order])

        # sort each child list by its order
        self.url_to_node_map = {node.resource.url: node for node in self.node_map.values()}
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

    def compute_speed_index(self):
        """
        Computes the speed index by calculating the area under the curve of viewport added versus time.
        """
        self.log.warn("in compute speed_index")
        # X-axis values are given by self.speed_index_time. For each X value.
        # the corresponding Y value is NOT given by the element at the same index
        # of speed_index_added_viewport.
        # speed_index_added_viewport gives the incremental contribution
        # of each element to the viewport. we need to create a new list
        # that contains the currently shown viewport at each instance of time
        # and this list represents the Y value.

        total_viewport_drawn = []
        self.log.warn("total_viewport_drawn is ", total_viewport_drawn=total_viewport_drawn)
        current_viewport_drawn = 0
        for element in self.speed_index_added_viewport:
            self.log.warn("appending to viewport drawn ", current_viewport_drawn=current_viewport_drawn)
            current_viewport_drawn += element
            total_viewport_drawn.append(current_viewport_drawn)


        self.log.info("total_viewport drawn before normalizing is ", total_viewport_drawn=total_viewport_drawn)
        # the total viewport at the end should reach 100. 
        # if not, we need to normalize the array to make it happen
        if total_viewport_drawn[-1] != 100:
            last_element = total_viewport_drawn[-1]
            normalizer = last_element / 100.0 
            # irrespective of whether the last_element is > or < than 100
            # we use the normalizer to bring it to 100
            for i, ele in enumerate(total_viewport_drawn):
                total_viewport_drawn[i] = ele / normalizer

        self.log.info("total_viewport drawn after normalizing is ", total_viewport_drawn=total_viewport_drawn)
        
        # 1 or 2 based on if u want reimann or wpt
        choice = 2

        if choice == 1:
            # we apply reimann trapezoidal sum
            # but note that our trapezoid has parallel heights
            # so our formula is time_delta * (y_0+y_1)/2
            total_area_under_curve = 0
            for index in range(len(total_viewport_drawn) - 1) :
                y_0 = total_viewport_drawn[index]
                y_1 = total_viewport_drawn[index + 1]
                x_0 = self.speed_index_time[index]
                x_1 = self.speed_index_time[index + 1]
                total_area_under_curve += 0.5 * (x_1 - x_0) * (y_0 + y_1)
            self.log.warn("computed area under the curve ", total_area_under_curve=total_area_under_curve)
            self.log.warn("speed_index_time is ", speed_index_time=self.speed_index_time)
            self.log.warn("total_viewport_drawn is ", total_viewport_drawn=total_viewport_drawn)
            # we have area under the curve
            # but we actually need the area above the curve.
            # so let us compute the area of the graph and subtract
            # the area under the curve from it. 

            total_area_above_curve = (max(self.speed_index_time) * max (total_viewport_drawn)) - total_area_under_curve
            return total_area_above_curve
        else:
            # The Speed Index is the "area above the curve" calculated in ms and using 0.0-1.0 for the range of visually complete.  The calculation looks at each 0.1s interval and calculates IntervalScore = Interval * (1.0 - (Completeness/100)) where Completeness is the % Visually complete for that frame and Interval is the elapsed time for that video frame in ms (100 in this case).  The overall score is just a sum of the individual intervals: SUM(IntervalScore)
            # https://sites.google.com/a/webpagetest.org/docs/using-webpagetest/metrics/speed-index#TOC-Measuring-Visual-Progress
            
            list_of_interval_scores = []
            current_time = 100 # start at 100 ms
            increment_interval = 1 # increment by 1 ms temporarily
            index_at_speed_index = 0
            self.log.info("speed index time is ", speed_index_time=self.speed_index_time)
            self.log.info("total viewport drawn is ", total_viewport_drawn=total_viewport_drawn)
            while index_at_speed_index < len(self.speed_index_time): # go until end of plt
                self.log.info("condition A")
                interval_score = 0
                if index_at_speed_index < len(self.speed_index_time) and current_time >= self.speed_index_time[index_at_speed_index]:
                    while index_at_speed_index < len(self.speed_index_time) and current_time >= self.speed_index_time[index_at_speed_index]:
                        self.log.info("condition B ", total_viewport_drawn=total_viewport_drawn[index_at_speed_index])
                        interval_score += (increment_interval * (1.0 - (total_viewport_drawn[index_at_speed_index] / 100.0)))
                        self.log.info("adding to interval score in A ", interval_score=interval_score)
                        index_at_speed_index += 1
                else:
                    self.log.info("condition C")
                    interval_score = increment_interval * (1.0 - (0 / 100.0))
                    self.log.info("adding to interval score in B ", interval_score=interval_score)
                self.log.info("condition D")
                current_time += increment_interval
                list_of_interval_scores.append(interval_score)

            total_area_above_curve = sum(list_of_interval_scores)
            self.log.warn("computed area above the curve ", total_area_above_curve=total_area_above_curve)
            return total_area_above_curve