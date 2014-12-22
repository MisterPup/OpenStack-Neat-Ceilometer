# Copyright 2012 Anton Beloglazov
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

""" The functions from this module are shared by other components.
"""

from contracts import contract
from neat.contracts_extra import *

import os
import time
import json
import re
import numpy
import subprocess

import novaclient
from novaclient.v1_1 import client
from ceilometerclient import client as ceiloclient

from neat.config import *
from neat.db_utils import *

import logging
log = logging.getLogger(__name__)


@contract
def start(init_state, execute, config, time_interval, iterations=-1):
    """ Start the processing loop.

    :param init_state: A function accepting a config and
                       returning a state dictionary.
     :type init_state: function

    :param execute: A function performing the processing at each iteration.
     :type execute: function

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param time_interval: The time interval to wait between iterations.
     :type time_interval: int

    :param iterations: The number of iterations to perform, -1 for infinite.
     :type iterations: int

    :return: The final state.
     :rtype: dict(str: *)
    """
    state = init_state(config)

    if iterations == -1:
        while True:
            state = execute(config, state)
            time.sleep(time_interval)
    else:
        for _ in xrange(iterations):
            state = execute(config, state)
            time.sleep(time_interval)

    return state


@contract
def build_local_vm_path(local_data_directory):
    """ Build the path to the local VM data directory.

    :param local_data_directory: The base local data path.
     :type local_data_directory: str

    :return: The path to the local VM data directory.
     :rtype: str
    """
    return os.path.join(local_data_directory, 'vms')


@contract
def build_local_host_path(local_data_directory):
    """ Build the path to the local host data file.

    :param local_data_directory: The base local data path.
     :type local_data_directory: str

    :return: The path to the local host data file.
     :rtype: str
    """
    return os.path.join(local_data_directory, 'host')


@contract
def physical_cpu_count(vir_connection):
    """ Get the number of physical CPUs using libvirt.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :return: The number of physical CPUs.
     :rtype: int
    """
    return vir_connection.getInfo()[2]


@contract
def physical_cpu_mhz(vir_connection):
    """ Get the CPU frequency in MHz using libvirt.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :return: The CPU frequency in MHz.
     :rtype: int
    """
    return vir_connection.getInfo()[3]


@contract
def physical_cpu_mhz_total(vir_connection):
    """ Get the sum of the core CPU frequencies in MHz using libvirt.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :return: The total CPU frequency in MHz.
     :rtype: int
    """
    return physical_cpu_count(vir_connection) * \
        physical_cpu_mhz(vir_connection)


@contract
def frange(start, end, step):
    """ A range generator for floats.

    :param start: The starting value.
     :type start: number

    :param end: The end value.
     :type end: number

    :param step: The step.
     :type step: number
    """
    while start <= end:
        yield start
        start += step


@contract
def init_logging(log_directory, log_file, log_level):
    """ Initialize the logging system.

    :param log_directory: The directory to store log files.
     :type log_directory: str

    :param log_file: The file name to store log messages.
     :type log_file: str

    :param log_level: The level of emitted log messages.
     :type log_level: int

    :return: Whether the logging system has been initialized.
     :rtype: bool
    """
    if log_level == 0:
        logging.disable(logging.CRITICAL)
        return True

    if not os.access(log_file, os.F_OK):
        if not os.access(log_directory, os.F_OK):
            os.makedirs(log_directory)
        elif not os.access(log_directory, os.W_OK):
            raise IOError(
                'Cannot write to the log directory: ' + log_directory)
    elif not os.access(log_file, os.W_OK):
        raise IOError('Cannot write to the log file: ' + log_file)

    if log_level == 3:
        level = logging.DEBUG
    elif log_level == 2:
        level = logging.INFO
    else:
        level = logging.WARNING

    logger = logging.root
    logger.handlers = []
    logger.filters = []

    logger.setLevel(level)
    handler = logging.FileHandler(
        os.path.join(log_directory, log_file))
    handler.setFormatter(
        logging.Formatter(
            '%(asctime)s %(levelname)-8s %(name)s %(message)s'))
    logger.addHandler(handler)

    return True


@contract
def call_function_by_name(name, args):
    """ Call a function specified by a fully qualified name.

    :param name: A fully qualified name of a function.
     :type name: str

    :param args: A list of positional arguments of the function.
     :type args: list

    :return: The return value of the function call.
     :rtype: *
    """
    fragments = name.split('.')
    module = '.'.join(fragments[:-1])
    fromlist = fragments[-2]
    function = fragments[-1]
    m = __import__(module, fromlist=fromlist)
    return getattr(m, function)(*args)


@contract
def parse_parameters(params):
    """ Parse algorithm parameters from the config file.

    :param params: JSON encoded parameters.
     :type params: str

    :return: A dict of parameters.
     :rtype: dict(str: *)
    """
    return dict((str(k), v)
                for k, v in json.loads(params).items())


@contract
def parse_compute_hosts(compute_hosts):
    """ Transform a coma-separated list of host names into a list.

    :param compute_hosts: A coma-separated list of host names.
     :type compute_hosts: str

    :return: A list of host names.
     :rtype: list(str)
    """
    return filter(None, re.split('\W+', compute_hosts))


@contract
def calculate_migration_time(vms, bandwidth):
    """ Calculate the mean migration time from VM RAM usage data.

    :param vms: A map of VM UUIDs to the corresponding maximum RAM in MB.
     :type vms: dict(str: int)

    :param bandwidth: The network bandwidth in MB/s.
     :type bandwidth: float,>0

    :return: The mean VM migration time in seconds.
     :rtype: float
    """
    return float(numpy.mean(vms.values()) / bandwidth)


@contract
def execute_on_hosts(hosts, commands):
    """ Execute Shell command on hosts over SSH.

    :param hosts: A list of host names.
     :type hosts: list(str)

    :param commands: A list of Shell commands.
     :type commands: list(str)
    """
    commands_merged = ''
    for command in commands:
        commands_merged += 'echo $ ' + command + ';'
        commands_merged += command + ';'

    for host in hosts:
        print 'Host: ' + host
        print subprocess.Popen(
            'ssh ' + host + ' "' + commands_merged + '"',
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True).communicate()[0]


@contract
def vms_by_hosts(nova, hosts):
    """ Get a map of host names to VMs using the Nova API.

    :param nova: A Nova client.
     :type nova: *

    :param hosts: A list of host names.
     :type hosts: list(str)

    :return: A dict of host names to lists of VM UUIDs.
     :rtype: dict(str: list(str))
    """
    result = dict((host, []) for host in hosts)
    vms_by_hosts = servers_by_hosts(nova, hosts)
    for host, vms in hosts.items():
        for vm in vms:
            result[host].append(str(vm.id))

@contract
def servers_by_hosts(nova, hosts):
    """ Get a map of host names to VMs using the Nova API.

    :param nova: A Nova client.
     :type nova: *

    :param hosts: A list of host names.
     :type hosts: list(str)

    :return: A dict of host names to lists of VM UUIDs.
     :rtype: dict(str: list(str))
    """
    result = dict((host, []) for host in hosts)
    for vm in nova.servers.list():
        hostname = vm_hostname(vm)
        if hostname in result.keys():
            result[hostname].append(vm)
    return result

@contract
def vm_hostname(vm):
    """ Get the name of the host where VM is running.

    :param vm: A Nova VM object.
     :type vm: *

    :return: The hostname.
     :rtype: str
    """
    return str(getattr(vm, 'OS-EXT-SRV-ATTR:host'))

@contract
def vms_ram_limit(nova, vms):
    """ Get the RAM limit from the flavors of the VMs.

    :param nova: A Nova client.
     :type nova: *

    :param vms: A list of VM UUIDs.
     :type vms: list(str)

    :return: A dict of VM UUIDs to the RAM limits.
     :rtype: dict(str: int)
    """
    flavors_to_ram = flavors_ram(nova)
    vms_ram = {}
    for uuid in vms:
        try:
            vm = nova.servers.get(uuid)
            vms_ram[uuid] = flavors_to_ram[vm.flavor['id']]
        except novaclient.exceptions.NotFound:
            pass
    return vms_ram


@contract
def flavors_ram(nova):
    """ Get a dict of flavor IDs to the RAM limits.

    :param nova: A Nova client.
     :type nova: *

    :return: A dict of flavor IDs to the RAM limits.
     :rtype: dict(str: int)
    """
    return dict((str(fl.id), fl.ram) for fl in nova.flavors.list())


def get_vms_last_n_cpu_util(ceilo, vms, last_n_vm_cpu=1, integer=False):
    """Get last n cpu usage values for each vm in vms.

    :param ceilo: A Ceilo client.
     :type ceilo: *

    :param vms: A set of vms
     :type vms: list(str)

    :param last_n_vm_cpu: Number of last cpu values to recover
     :type last_n_vm_cpu: int

    :param integer: Boolean telling if we want data as integer or float
     :type integer: bool

    :return: A dictionary of (vm, [cpu_usage])
     :rtype: dict(str: *)
    """

    vms_last_cpu_util = dict() #dict of (vm, [cpu_util])
    for vm in vms:
        cpu_util_list = (
            ceilo.samples.list(meter_name='cpu_util', 
                               limit=last_n_vm_cpu, 
                               q=[{'field':'resource_id',
                                   'op':'eq',
                                   'value':vm}]))
    
        #we have collected at least last_n_vm_cpu samples for current vm
        if len(cpu_util_list) == last_n_vm_cpu:
            if integer:
                vms_last_cpu_util[vm] = [int(sample.counter_volume) for sample in cpu_util_list]
            else:
                vms_last_cpu_util[vm] = [sample.counter_volume for sample in cpu_util_list]

    return vms_last_cpu_util