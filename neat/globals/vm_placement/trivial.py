# Copyright 2014 Claudio Pupparo
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Random VM placement algorithms.
"""

from contracts import contract
from neat.contracts_extra import *
import random

import logging
log = logging.getLogger(__name__)

@contract
def random_factory(time_step, migration_time, params):
    """ Creates the random VM placement algorithm.

    :param time_step: The length of the simulation time step in seconds.
     :type time_step: int,>=0

    :param migration_time: The VM migration time in time seconds.
     :type migration_time: float,>=0

    :param params: A dictionary containing the algorithm's parameters.
     :type params: dict(str: *)

    :return: A function implementing the random VM placement algorithm.
     :rtype: function
    """	

    return lambda vms_migrate, hosts_dst, state=None: ([random(vms_migrate, hosts_dst)], {})

@contract
def random(vms_migrate, hosts_dst):
    """ Rlgorithm for randomplacing VMs on hosts.

    :param vms_migrate: A list of VMs to migrate.
     :type vms_migrate: list()

    :param hosts_dst: A list of possibile host destination for migration.
     :type hosts_dst: list()

    :return: A map of VM UUIDs to host names.
     :rtype: dict(str: str)
    """
    placement = {}
    for vm in vms_migrate:
        rand_index = random.randint(0, len(hosts_dst) - 1) #uniform random in [0, n-1], n=number of host
        rand_host = hosts_dst[rand_index]
        placement[vm] = rand_host

    return placement;
