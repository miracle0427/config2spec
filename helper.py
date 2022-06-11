#!/usr/bin/env python
# Author: Ruediger Birkner (Networked Systems Group at ETH Zurich)

import logging
import numpy as np
import os
import random
import time
import subprocess
import signal
import socket

import pandas as pd

statistics = {'type':[], 'query': [], 'result': [], 'source_num' :[],
              'count-example': [], 'down_links':[], 'count-example-num' : [],
              'time':[], 'holds_policies': [], 'holds_not_policies': [], 'unknown_policies': [], }


from config2spec.backend.minesweeper import MinesweeperBackend
from config2spec.dataplane.batfish_engine import BatfishEngine
from config2spec.netenv.network_environment import NetworkEnvironment
from config2spec.netenv.enumerate_sampler import EnumerateSampler
from config2spec.netenv.link_set_sampler import BlockLinksPolicySetSampler
from config2spec.netenv.merge_set_sampler import MergePolicySetSampler
from config2spec.netenv.random_set_sampler import RandomPolicySetSampler
from config2spec.netenv.random_sampler import RandomSampler
from config2spec.netenv.set_sampler import PolicySetSampler
from config2spec.netenv.sum_sampler import PolicySumSampler
from config2spec.policies.policy_db import PolicyDB
from config2spec.policies.policy_db import PolicyStatus
from config2spec.topology.builder.minesweeper_builder import BackendTopologyBuilder
from config2spec.topology.links import Link
from config2spec.topology.links import LinkState


def get_logger(name, loglevel):
    # LOGGING
    if loglevel == "INFO":
        log_level = logging.INFO
    elif loglevel == "DEBUG":
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    # add handler
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    if len(logger.handlers) == 0:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def init_manager(backend_path, port):
    ms_cmd = ['java', '-cp', '%s' % backend_path, 'org.batfish.backend.Backend', '%d' % port]
    print(ms_cmd)

    # creating minesweeper manager
    ms_manager = MinesweeperManager(ms_cmd, port)
    ms_manager.start()

    return ms_manager


def init_backend(ms_manager, scenario, base_path, config_path, port):
    # init the backend (Batfish/Minesweeper)
    ms_backend = MinesweeperBackend(base_path, scenario, config_path, url="http://localhost", port=port, debug=False)
    ms_backend.init_minesweeper()

    ms_manager.backend = ms_backend

    ms_manager.restart(backend_calls=0, force=True)


def build_network(backend, scenario_path, max_failures, waypoints_min, waypoints_fraction):
    topology_files = backend.get_topology()
    network = BackendTopologyBuilder.build_topology(topology_files, scenario_path)

    # get waypoints
    all_routers = network.nodes()
    num_waypoints = max(waypoints_min, int(len(all_routers) / waypoints_fraction))
    waypoints = random.sample(all_routers, num_waypoints)

    links = list()
    all_edges = network.get_undirected_edges()
    for i, edge in enumerate(all_edges):
        links.append(Link("l{id}".format(id=i), edge, LinkState.SYMBOLIC))

    # create the network environment
    netenv = NetworkEnvironment(links, k_failures=max_failures)

    return network, netenv, waypoints


def init_dp_engine(network, fib_path, debug=False):
    nodes = list(network.nodes())
    next_hops = network.next_hops
    simple_acls = network.simple_acls
    dp_engine = BatfishEngine(nodes, next_hops, simple_acls, fib_path, debug=debug)

    return dp_engine


def get_sampler(sampling_mode, netenv, policy_db, seed):
    if sampling_mode == "random":
        sampler = RandomSampler(netenv, seed=seed,
                                use_provided_samples=False, debug=False)
    elif sampling_mode == "sum":
        sampler = PolicySumSampler(netenv, policy_db, seed=seed,
                                   use_provided_samples=False, debug=False)
    elif sampling_mode == "enumerate":
        sampler = EnumerateSampler(netenv, seed=seed,
                                   use_provided_samples=False, debug=False)
    elif sampling_mode == "merge":
        sampler = MergePolicySetSampler(netenv, policy_db, seed=seed,
                                        use_provided_samples=False, debug=False)
    elif sampling_mode == "block":
        sampler = BlockLinksPolicySetSampler(netenv, policy_db, seed=seed,
                                             use_provided_samples=False, debug=False)
    elif sampling_mode == "randomset":
        sampler = RandomPolicySetSampler(netenv, policy_db, seed=seed,
                                         use_provided_samples=False, debug=False)
    else:
        sampler = PolicySetSampler(netenv, policy_db, seed=seed,
                                   use_provided_samples=False, debug=False)
    return sampler


def get_policy_db(network, waypoints=None, debug=False):
    return PolicyDB(network, waypoints=waypoints, debug=debug)


class SlidingTimer(object):
    def __init__(self, window_size):
        self.window_size = window_size

        self.times = list()
        self.eliminated_policies = list()

        self.infinity = 10000000

    def mean_time_per_item(self):
        if self.times:
            # if the list of times is shorter than the window size this still works
            mean_time = np.mean(self.times[-self.window_size:])
            return mean_time
        else:
            return 0

    def mean_time_per_policy(self):
        if self.times:
            total_time = sum(self.times[-self.window_size:])
            num_policies = sum(self.eliminated_policies[-self.window_size:])

            if num_policies > 0:
                return total_time/num_policies
            return self.infinity
        else:
            return 0

    def estimate_remaining_time(self, num_samples):
        mean_time = self.mean_time_per_item()

        if mean_time:
            return num_samples * mean_time
        else:
            return 0

    def update(self, runtime, num_eliminated_policies):
        self.times.append(runtime)
        self.eliminated_policies.append(num_eliminated_policies)

    def full_window(self):
        return len(self.times) == self.window_size


class Pipeline(object):
    def __init__(self, policy_db, sampler, dp_engine, netenv, ms_manager, window_size, network, debug=False):
        self.logger = get_logger("Dense-Sparse-Pipeline", 'DEBUG' if debug else 'INFO')

        self.policy_db = policy_db
        self.sampler = sampler
        self.dp_engine = dp_engine
        self.netenv = netenv
        self.ms_manager = ms_manager
        self.network = network

        # set up time analysis
        self.sampling_times = SlidingTimer(window_size)
        self.verification_times = SlidingTimer(window_size)

        # temporary variables
        self.prev_forwarding_graphs = None
        self.prev_guess_size = -1

    def sample(self, first=False):
        start_time = time.time()

        # pick the concrete env to use
        if first:
            concrete_env = self.sampler.get_all_up()
        elif self.sampler.fwd_state_based:
            concrete_env = self.sampler.get_next_env(self.prev_forwarding_graphs)
        else:
            concrete_env = self.sampler.get_next_env()

        # compute the dataplane and check the policies that hold
        num_eliminated_policies = -1

        if concrete_env:
            failed_edges = concrete_env.get_links(state=LinkState.DOWN)
            fib_file_name = self.ms_manager.get_dataplane(failed_edges)
            if fib_file_name:
                forwarding_graphs = self.dp_engine.get_forwarding_graphs(fib_file_name)
                dominator_graphs = self.dp_engine.get_dominator_graphs()

                _, guess_size = self.policy_db.update_policies(9, forwarding_graphs, dominator_graphs)

                self.prev_forwarding_graphs = forwarding_graphs
                if self.prev_guess_size >= 0:
                    num_eliminated_policies = self.prev_guess_size - guess_size
                self.prev_guess_size = guess_size

            sampling_time = time.time() - start_time
            if num_eliminated_policies >= 0:
                self.sampling_times.update(sampling_time, num_eliminated_policies)

            return True
        else:
            self.logger.error("Couldn't find another unused sample!")
            return False

    def verify(self):
        start_time = time.time()

        # pick next policy/policies to check
        query = self.policy_db.get_query(environment=self.netenv, group=True)
        num_policies = len(query.sources)

        # check policies with Minesweeper
        response = self.ms_manager.check_query(query)

        query_str = query.to_string_representation()

        if 'Type:reachability' in query_str:
            statistics['type'].append('reachability')
        elif 'Type:loadbalancing' in query_str:
            statistics['type'].append('loadbalancing')
        elif 'Type:waypoint' in query_str:
            statistics['type'].append('waypoint')

        statistics['query'].append(query_str)
        statistics['source_num'].append(len(query.sources))


        # update policy db
        if response.all_hold():
            verified_sources = response.holds()
            for source in verified_sources:
                self.policy_db.update_policy(response.type, response.subnet, response.specifics,
                                             PolicyStatus.HOLDS, source=source)
            self.logger.debug("Verify: Satisfied - All policies hold: {}".format(num_policies))

            statistics['result'].append('correct')
            statistics['count-example'].append(None)
            statistics['down_links'].append(None)
            statistics['count-example-num'].append(0)

        else:
            failed_sources = response.holds_not()
            for source in failed_sources:
                self.policy_db.update_policy(response.type, response.subnet, response.specifics,
                                             PolicyStatus.HOLDSNOT, source=source)
            self.logger.debug("Verify: Counterexample - {} policies out of {} are violated".format(len(failed_sources),
                                                                                                   num_policies))
            statistics['result'].append('wrong')
            statistics['count-example'].append([str(entry) for entry in failed_sources])

            downlinks = []
            for link in response.counter_example.links.values():
                if link.state == LinkState.DOWN:
                    downlinks.append(link.edge)

            statistics['down_links'].append([str(entry) for entry in downlinks])
            statistics['count-example-num'].append(len(failed_sources))


        # update timing stats
        verification_time = time.time() - start_time
        verified = len(response.holds())
        violated = len(response.holds_not())
        self.verification_times.update(verification_time, verified + violated)

        holds_policies = self.policy_db.num_policies(status=PolicyStatus.HOLDS)
        holds_not_policies = self.policy_db.num_policies(status=PolicyStatus.HOLDSNOT)
        unknown_policies = self.policy_db.num_policies(status=PolicyStatus.UNKNOWN)

        statistics['time'].append(verification_time)
        statistics['holds_policies'].append(holds_policies)
        statistics['holds_not_policies'].append(holds_not_policies)
        statistics['unknown_policies'].append(unknown_policies)

        path = os.path.dirname(self.dp_engine.fib_path)
        pd.DataFrame(statistics).to_csv(os.path.join(path, 'statistics.csv'), index=False)

        return True

    def trim(self):
        start = time.time()
        connected_pairs = self.network.get_k_connected_routers(self.netenv.k_failures + 1)
        num_trimmed_policies = self.policy_db.trim_policies(connected_pairs)
        self.logger.debug("Trim: trimmed {} policies".format(num_trimmed_policies))
        total = time.time() - start

        holds_policies = self.policy_db.num_policies(status=PolicyStatus.HOLDS)
        holds_not_policies = self.policy_db.num_policies(status=PolicyStatus.HOLDSNOT)
        unknown_policies = self.policy_db.num_policies(status=PolicyStatus.UNKNOWN)

        statistics['type'].append('trim')
        statistics['query'].append(None)
        statistics['source_num'].append(None)
        statistics['result'].append(None)
        statistics['count-example'].append(None)
        statistics['down_links'].append(None)
        statistics['count-example-num'].append(None)
        statistics['time'].append(total)
        statistics['holds_policies'].append(holds_policies)
        statistics['holds_not_policies'].append(holds_not_policies)
        statistics['unknown_policies'].append(unknown_policies)

    def run(self, trim_policies=False):
        self.logger.info("Start running the pipeline by computing the first sample.")

        # start actual policy learning with a first sample - all links up
        success = self.sample(first=True)
        if not success:
            self.logger.error("Dataplane sampling failed...")
            return

        num_steps = 0
        self.trim()
        while True:
            remaining_samples = self.sampler.remaining_samples()
            remaining_policies = self.policy_db.num_policies(status=PolicyStatus.UNKNOWN)

            # logging
            if num_steps % 100 == 0:
                self.logger.info("Step {}: There are {} samples and {} policies remaining.".format(num_steps,
                                                                                                   remaining_samples,
                                                                                                   remaining_policies))
            num_steps += 1

            # check if we are done
            if remaining_samples == 0 or remaining_policies == 0:
                break

            self.verify()

            # check if something failed
            if not success:
                self.logger.error("Something failed (most likely the dataplane sampling)")
                break

        # as we are done, we need to change all the unknown policies to ones that hold
        self.policy_db.change_status(PolicyStatus.UNKNOWN, PolicyStatus.HOLDS)
        path = os.path.dirname(self.dp_engine.fib_path)
        pd.DataFrame(statistics).to_csv(os.path.join(path, 'statistics.csv'), index=False)
        return


class MinesweeperManager(object):
    def __init__(self, command, port):
        self.process = None
        self.command = command
        self.running = False
        self.logger = get_logger('MinesweeperManager', 'INFO')
        self.queries = 0
        self.port = port

        self.backend = None

    def start(self):
        if not self.running:
            self.logger.info("Starting Minesweeper.")

            # make sure the port is available before starting Minesweeper
            while MinesweeperManager.port_blocked(self.port):
                self.logger.info("Port %d still blocked." % (self.port, ))
                time.sleep(0.5)

            # start Minesweeper
            self.logger.info("Port %d finally free, everything ready to start Minesweeper." % (self.port, ))
            self.process = subprocess.Popen(self.command, preexec_fn=os.setsid)
            self.running = True

            # wait a bit for Minesweeper to fully start up
            time.sleep(2.0)
        else:
            self.logger.info("Minesweeper is already running.")

    def stop(self, backend_calls, force_stop=False):
        self.queries += backend_calls
        if self.queries > 3500 or force_stop:
            self.logger.debug("Killing Minesweeper as it answered %d queries - (force stop %s)" % (self.queries,
                                                                                                  force_stop))
            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            self.running = False
            self.queries = 0
            return True
        else:
            self.logger.debug("Keeping Minesweeper running as it answered just %d queries so far." % (self.queries, ))
            return False

    @staticmethod
    def port_blocked(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            sock.bind(("0.0.0.0", port))
            result = False
        except:
            result = True

        sock.close()
        return result

    def restart(self, backend_calls=0, force=False):
        assert self.backend, "Cannot restart the backend without self.ms_backend being set."

        # restart the backend/process
        stopped = self.stop(backend_calls=backend_calls, force_stop=force)
        if stopped:
            self.start()

            # init the restarted backend
            self.backend.init_minesweeper(force_init=True)

            # request topology such that the backend has already parsed the config
            self.backend.get_topology()

    def get_dataplane(self, failed_edges):
        return self.backend.get_dataplane(failed_edges)

    def check_query(self, query):
        # check if we should restart the backend
        self.queries += 1

        if self.queries > 3000:
            self.restart(force=True)

        return self.backend.check_query(query)