""" This module implements utilities to record and pre-process live web page loads """
import collections
import functools
import subprocess
import tempfile
from typing import List, Optional, Set
from xml.etree import ElementTree

import requests

from blaze.action import Policy
from blaze.chrome.har import Har
from blaze.config import Config
from blaze.config.client import ClientEnvironment, get_default_client_environment
from blaze.config.environment import Resource
from blaze.chrome.config import get_chrome_command, get_chrome_flags
from blaze.chrome.devtools import capture_har_in_mahimahi
from blaze.logger import logger
from blaze.mahimahi import MahiMahiConfig
from blaze.util.seq import ordered_uniq

from .har import har_entries_to_resources, compute_parent_child_relationships
from .resource import resource_list_to_push_groups
from .url import Url

EXECUTION_CAPTURE_RUNS = 5
STABLE_SET_NUM_RUNS = 10


def record_webpage(url: str, save_dir: str, config: Config):
    """
    Given a URL and runtime configuration, record_webpage creates a Mahimahi record
    shell and records the web page load in Chrome. It saves the result to the given
    save directory, which is expected to be empty. A subprocess.CalledProcessError
    is raised if an error occurs
    """
    with tempfile.TemporaryDirectory(prefix="blaze_record", dir="/tmp") as tmp_dir:
        chrome_flags = get_chrome_flags(tmp_dir)
        chrome_cmd = get_chrome_command(url, chrome_flags, config)

        mm_config = MahiMahiConfig(config)
        cmd = mm_config.record_shell_with_cmd(save_dir, chrome_cmd)

        logger.with_namespace("record_webpage").debug("spawning web recorder", url=url, cmd=cmd)

        proc = subprocess.run(cmd)
        proc.check_returncode()


def find_url_stable_set(url: str, config: Config) -> List[Resource]:
    """
    Loads the given URL `STABLE_SET_NUM_RUNS` times back-to-back and records the HAR file
    generated by chrome. It then finds the common URLs across the page loads, computes their
    relative ordering, and returns a list of PushGroups for the webpage
    """
    log = logger.with_namespace("find_url_stable_set")
    hars: List[Har] = []
    resource_sets: List[Set[Resource]] = []
    pos_dict = collections.defaultdict(lambda: collections.defaultdict(int))
    for n in range(STABLE_SET_NUM_RUNS):
        log.debug("capturing HAR...", run=n + 1, url=url)
        har = capture_har_in_mahimahi(url, config, get_default_client_environment())
        resource_list = har_entries_to_resources(har)
        if not resource_list:
            log.warn("no response received", run=n + 1)
            continue
        log.debug("received resources", total=len(resource_list))

        for i in range(len(resource_list)):  # pylint: disable=consider-using-enumerate
            for j in range(i + 1, len(resource_list)):
                pos_dict[resource_list[i].url][resource_list[j].url] += 1

        resource_sets.append(set(resource_list))
        hars.append(har)

    log.debug("resource set lengths", resource_lens=list(map(len, resource_sets)))
    if not resource_sets:
        return []

    common_res = list(set.intersection(*resource_sets))
    common_res.sort(key=functools.cmp_to_key(lambda a, b: -pos_dict[a.url][b.url] + (len(resource_sets) // 2)))

    # Hackily reorder the combined resource sets so that compute_parent_child_relationships works
    common_res = [Resource(**{**r._asdict(), "order": i}) for (i, r) in enumerate(common_res)]
    return compute_parent_child_relationships(common_res, hars[0].timings)


def get_page_links(url: str, max_depth: int = 1) -> List[str]:
    """
    Performs DFS with the given max_depth on the given URL to discover all
    <a href="..."> links in the page
    """
    if max_depth == 0:
        return []

    log = logger.with_namespace("get_page_links").with_context(depth_left=max_depth)
    try:
        log.info("fetching page", url=url)
        page = requests.get(url)
        page.raise_for_status()
        page_text = page.text
    except requests.exceptions.RequestException as err:
        log.warn("failed to fetch page", error=repr(err))
        return []

    try:
        log.debug("parsing http response", length=len(page_text))
        root = ElementTree.fromstring(page_text)
    except ElementTree.ParseError as err:
        log.warn("failed to parse response", error=repr(err))
        return []

    parsed_links = root.findall(".//a")
    log.info("found links", url=url, n_links=len(parsed_links))

    links = []
    domain = Url.parse(url).domain
    for link in parsed_links:
        link_url = link.get("href")
        if not any(link_url.startswith(prefix) for prefix in {"http", "/"}):
            log.debug("ignoring found link (bad prefix)", link=link_url)
            continue

        link_domain = Url.parse(link_url).domain
        if link_domain != domain:
            log.debug("ignoring found link (bad domain)", link=link_url)
            continue

        links.append(link_url)
        links.extend(get_page_links(link_url, max_depth - 1))
    return ordered_uniq(links)


def get_page_load_time_in_mahimahi(
    request_url: str, client_env: ClientEnvironment, config: Config, push_policy: Optional[Policy] = None
):
    """
    Return the page load time, the HAR resources captured, and the push groups detected
    by loading the page in the given mahimahi record directory
    """
    log = logger.with_namespace("get_page_load_time_in_mahimahi")
    log.debug("using client environment", **client_env._asdict())
    hars = []
    for i in range(EXECUTION_CAPTURE_RUNS):
        log.debug("recording page execution in Mahimahi", run=(i + 1), total_runs=EXECUTION_CAPTURE_RUNS)
        har = capture_har_in_mahimahi(request_url, config, client_env, push_policy)
        hars.append(har)
        log.debug("captured page execution", page_load_time=har.page_load_time_ms)

    hars.sort(key=lambda h: h.page_load_time_ms)
    log.debug("recorded execution times", plt_ms=[h.page_load_time_ms for h in hars])
    median_har = hars[len(hars) // 2]
    har_res_list = har_entries_to_resources(median_har)
    har_push_groups = resource_list_to_push_groups(har_res_list)
    return median_har.page_load_time_ms, har_res_list, har_push_groups
