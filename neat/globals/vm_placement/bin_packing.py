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

""" Bin Packing based VM placement algorithms.
"""

from contracts import contract
from neat.contracts_extra import *

import logging
log = logging.getLogger(__name__)


@contract
def best_fit_decreasing_factory(time_step, migration_time, params):
    """ Creates the Best Fit Decreasing (BFD) heuristic for VM placement.

    :param time_step: The length of the simulation time step in seconds.
     :type time_step: int,>=0

    :param migration_time: The VM migration time in time seconds.
     :type migration_time: float,>=0

    :param params: A dictionary containing the algorithm's parameters.
     :type params: dict(str: *)

    :return: A function implementing the BFD algorithm.
     :rtype: function
    """
    return lambda hosts_cpu_usage, hosts_cpu_total, \
                  hosts_ram_usage, hosts_ram_total, \
                  inactive_hosts_cpu, inactive_hosts_ram, \
                  vms_cpu, vms_ram, state=None: \
        (best_fit_decreasing(
            params['last_n_vm_cpu'],
            get_available_resources(
                    params['cpu_threshold'],
                    hosts_cpu_usage,
                    hosts_cpu_total),
            get_available_resources(
                    params['ram_threshold'],
                    hosts_ram_usage,
                    hosts_ram_total),
            inactive_hosts_cpu,
            inactive_hosts_ram,
            vms_cpu,
            vms_ram),
         {})

@contract
def best_fit_decreasing_no_overload_factory(time_step, migration_time, params):
    """ Creates the Best Fit Decreasing No Overload (BFDNO) heuristic for VM placement.
    
    :param time_step: The length of the simulation time step in seconds.
     :type time_step: int,>=0

    :param migration_time: The VM migration time in time seconds.
     :type migration_time: float,>=0

    :param params: A dictionary containing the algorithm's parameters.
     :type params: dict(str: *)

    :return: A function implementing the BFD algorithm.
     :rtype: function
    """
    return lambda hosts_cpu_usage, hosts_cpu_total, \
                  hosts_ram_usage, hosts_ram_total, \
                  inactive_hosts_cpu, inactive_hosts_ram, \
                  vms_cpu, vms_ram, state=None: \
        (best_fit_decreasing_no_overload(
            params['last_n_vm_cpu'],
            get_available_resources(
                    params['cpu_threshold'],
                    hosts_cpu_usage,
                    hosts_cpu_total),
            get_total_with_threshold(
                    params['cpu_threshold'],
                    hosts_cpu_total),
            get_available_resources(
                    params['ram_threshold'],
                    hosts_ram_usage,
                    hosts_ram_total),
            get_total_with_threshold(
                    params['ram_threshold'],
                    hosts_ram_total),       
            inactive_hosts_cpu,
            inactive_hosts_ram,
            vms_cpu,
            vms_ram,
            params['cpu_weight'],
            params['ram_weight'],
            params['overload_threshold']),
         {})

@contract
def get_total_with_threshold(threshold, total):
    """Return the total resource capacity, limited by threshold

    :param threshold: A threshold on the maximum allowed resource usage.
     :type threshold: float,>=0

    :param total: A map of hosts to the total resource capacity.
     :type total: dict(str: number)

    :return: A map of hosts to the total resource capacity, limited by threshold.
     :rtype: dict(str: int)
    """
    return dict((host, int(threshold * total[host]))
                for host in total.keys())

@contract
def get_available_resources(threshold, usage, total):
    """ Get a map of the available resource capacity.

    :param threshold: A threshold on the maximum allowed resource usage.
     :type threshold: float,>=0

    :param usage: A map of hosts to the resource usage.
     :type usage: dict(str: number)

    :param total: A map of hosts to the total resource capacity.
     :type total: dict(str: number)

    :return: A map of hosts to the available resource capacity.
     :rtype: dict(str: int)
    """
    return dict((host, int(threshold * total[host] - resource))
                for host, resource in usage.items())

@contract
def best_fit_decreasing(last_n_vm_cpu, hosts_cpu, hosts_ram,
                        inactive_hosts_cpu, inactive_hosts_ram,
                        vms_cpu, vms_ram):
    """ The Best Fit Decreasing (BFD) heuristic for placing VMs on hosts.

    :param last_n_vm_cpu: The last n VM CPU usage values to average.
     :type last_n_vm_cpu: int

    :param hosts_cpu: A map of host names and their available CPU in MHz.
     :type hosts_cpu: dict(str: int)

    :param hosts_ram: A map of host names and their available RAM in MB.
     :type hosts_ram: dict(str: int)

    :param inactive_hosts_cpu: A map of inactive hosts and available CPU MHz.
     :type inactive_hosts_cpu: dict(str: int)

    :param inactive_hosts_ram: A map of inactive hosts and available RAM MB.
     :type inactive_hosts_ram: dict(str: int)

    :param vms_cpu: A map of VM UUID and their CPU utilization in MHz.
     :type vms_cpu: dict(str: list(int))

    :param vms_ram: A map of VM UUID and their RAM usage in MB.
     :type vms_ram: dict(str: int)

    :return: A map of VM UUIDs to host names, or {} if cannot be solved.
     :rtype: dict(str: str)
    """
    vms_tmp = []
    for vm, cpu in vms_cpu.items():
        last_n_cpu = cpu[-last_n_vm_cpu:]
        vms_tmp.append((sum(last_n_cpu) / len(last_n_cpu),
                        vms_ram[vm],
                        vm))
    vms = sorted(vms_tmp, reverse=True)
    hosts = sorted(((v, hosts_ram[k], k)
                    for k, v in hosts_cpu.items()))
    inactive_hosts = sorted(((v, inactive_hosts_ram[k], k)
                             for k, v in inactive_hosts_cpu.items()))
    mapping = {}
    for vm_cpu, vm_ram, vm_uuid in vms:
        mapped = False
        while not mapped:
            for _, _, host in hosts:
                if hosts_cpu[host] >= vm_cpu and \
                    hosts_ram[host] >= vm_ram:
                        mapping[vm_uuid] = host
                        hosts_cpu[host] -= vm_cpu
                        hosts_ram[host] -= vm_ram
                        mapped = True
                        break
            else:
                if inactive_hosts:
                    activated_host = inactive_hosts.pop(0)
                    hosts.append(activated_host)
                    hosts = sorted(hosts)
                    hosts_cpu[activated_host[2]] = activated_host[0]
                    hosts_ram[activated_host[2]] = activated_host[1]
                else:
                    break

    if len(vms) == len(mapping):
        return mapping
    return {}

@contract
def check_no_overload_if_placement(cpu_weight, ram_weight, overload_threshold,
                        vm_cpu, hosts_cpu, total_threshold_cpu,
                        vm_ram, hosts_ram, total_threshold_ram):
    """ Check if placing the vm on the selected host, will make it overloaded.

    :param cpu_weight: Weight of the CPU in the combined meter.
     :type cpu_weight: float,>= 0

    :param ram_weight: Weight of the RAM in the combined meter.
     :type ram_weight: float,>=0

    :param overload_threshold: Overload threshold of the combined meter.
     :type overload_threshold: float,>=0

    :param vm_cpu: CPU utilization of the vm in MHz.
     :type vm_cpu: int,>0

    :param hosts_cpu: A map of host names and their available CPU in MHz.
     :type hosts_cpu: dict(str: int)

    :param total_threshold_cpu: total CPU capacity of the host, limited by threshold.
     :type total_threshold_cpu: int

    :param vm_ram: RAM usage of the VM in MB.
     :type vm_ram: int,>0

    :param hosts_ram: A map of host names and their available RAM in MB.
     :type hosts_ram: dict(str: int)

    :param total_threshold_ram: total RAM capacity of the host, limited by threshold.
     :type total_threshold_ram: int, >0

    :return: A boolean telling if the vm can be placed on the host, without making it overloaded.
     :rtype bool

    """
    cpu_term = cpu_weight * (host_cpu + vm_cpu) / (total_threshold_cpu)
    ram_term = ram_weight * (host_ram + vm_ram) / (total_threshold_ram)
    return cpu_term + ram_term < overload_threshold

@contract
def best_fit_decreasing_no_overload(last_n_vm_cpu, hosts_cpu, total_threshold_cpu, 
                        hosts_ram, total_threshold_ram,
                        inactive_hosts_cpu, inactive_hosts_ram,
                        vms_cpu, vms_ram,
                        cpu_weight, ram_weight, overload_threshold):
    """ The Best Fit Decreasing (BFD) heuristic for placing VMs on hosts.
    It avoids putting a vm on an overloaded host

    :param last_n_vm_cpu: The last n VM CPU usage values to average.
     :type last_n_vm_cpu: int

    :param hosts_cpu: A map of host names and their available CPU in MHz.
     :type hosts_cpu: dict(str: int)

    :param total_threshold_cpu: total CPU capacity of the host, limited by threshold.
     :type total_threshold_cpu: int

    :param hosts_ram: A map of host names and their available RAM in MB.
     :type hosts_ram: dict(str: int)

    :param total_threshold_ram: total RAM capacity of the host, limited by threshold.
     :type total_threshold_ram: int, >0

    :param inactive_hosts_cpu: A map of inactive hosts and available CPU MHz.
     :type inactive_hosts_cpu: dict(str: int)

    :param inactive_hosts_ram: A map of inactive hosts and available RAM MB.
     :type inactive_hosts_ram: dict(str: int)

    :param vms_cpu: A map of VM UUID and their CPU utilization in MHz.
     :type vms_cpu: dict(str: list(int))

    :param vms_ram: A map of VM UUID and their RAM usage in MB.
     :type vms_ram: dict(str: int)

    :param cpu_weight: Weight of the CPU in the combined meter.
     :type cpu_weight: float,>= 0

    :param ram_weight: Weight of the RAM in the combined meter.
     :type ram_weight: float,>=0

    :param overload_threshold: Overload threshold of the combined meter.
     :type overload_threshold: float,>=0

    :return: A map of VM UUIDs to host names, or {} if cannot be solved.
     :rtype: dict(str: str)
    """
    vms_tmp = []
    for vm, cpu in vms_cpu.items():
        last_n_cpu = cpu[-last_n_vm_cpu:]
        vms_tmp.append((sum(last_n_cpu) / len(last_n_cpu),
                        vms_ram[vm],
                        vm))
    vms = sorted(vms_tmp, reverse=True)
    hosts = sorted(((v, hosts_ram[k], k)
                    for k, v in hosts_cpu.items()))
    inactive_hosts = sorted(((v, inactive_hosts_ram[k], k)
                             for k, v in inactive_hosts_cpu.items()))

    mapping = {}
    for vm_cpu, vm_ram, vm_uuid in vms:
        mapped = False
        while not mapped:
            for _, _, host in hosts:
                if (hosts_cpu[host] >= vm_cpu and
                    hosts_ram[host] >= vm_ram and
                    check_no_overload_if_placement(cpu_weight, ram_weight, overload_threshold,
                                                   vm_cpu, hosts_cpu[host], total_threshold_cpu[host],
                                                   vm_ram, hosts_ram[host], total_threshold_ram[host])):
                        mapping[vm_uuid] = host
                        hosts_cpu[host] -= vm_cpu
                        hosts_ram[host] -= vm_ram
                        mapped = True
                        break
            else:
                if inactive_hosts:
                    activated_host = inactive_hosts.pop(0)
                    hosts.append(activated_host)
                    hosts = sorted(hosts)
                    hosts_cpu[activated_host[2]] = activated_host[0]
                    hosts_ram[activated_host[2]] = activated_host[1]
                else:
                    break

    if len(vms) == len(mapping):
        return mapping
    return {}
