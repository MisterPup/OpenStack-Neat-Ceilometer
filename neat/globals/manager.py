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

""" The main global manager module.

The global manager is deployed on the management host and is
responsible for making VM placement decisions and initiating VM
migrations. It exposes a REST web service, which accepts requests from
local managers. The global manager processes only one type of requests
-- reallocation of a set of VM instances. Once a request is received,
the global manager invokes a VM placement algorithm to determine
destination hosts to migrate the VMs to. Once a VM placement is
determined, the global manager submits a request to the Nova API to
migrate the VMs. The global manager is also responsible for switching
idle hosts to the sleep mode, as well as re-activating hosts when
necessary.

The global manager is agnostic of a particular implementation of the
VM placement algorithm in use. The VM placement algorithm to use can
be specified in the configuration file using the
`algorithm_vm_placement_factory` option. A VM placement algorithm can
call the Nova API to obtain the information about host characteristics
and current VM placement. If necessary, it can also query the central
database to obtain the historical information about the resource usage
by the VMs.

The global manager component provides a REST web service implemented
using the Bottle framework. The authentication is done using the admin
credentials specified in the configuration file. Upon receiving a
request from a local manager, the following steps will be performed:

1. Parse the `vm_uuids` parameter and transform it into a list of
   UUIDs of the VMs to migrate.

2. Call the Nova API to obtain the current placement of VMs on the
   hosts.

3. Call the function specified in the `algorithm_vm_placement_factory`
   configuration option and pass the UUIDs of the VMs to migrate and
   the current VM placement as arguments.

4. Call the Nova API to migrate the VMs according to the placement
   determined by the `algorithm_vm_placement_factory` algorithm.

When a host needs to be switched to the sleep mode, the global manager
will use the account credentials from the `compute_user` and
`compute_password` configuration options to open an SSH connection
with the target host and then invoke the command specified in the
`sleep_command`, which defaults to `pm-suspend`.

When a host needs to be re-activated from the sleep mode, the global
manager will leverage the Wake-on-LAN technology and send a magic
packet to the target host using the `ether-wake` program and passing
the corresponding MAC address as an argument. The mapping between the
IP addresses of the hosts and their MAC addresses is initialized in
the beginning of the global manager's execution.
"""

from contracts import contract
from neat.contracts_extra import *

import bottle
from hashlib import sha1
import novaclient
from novaclient.v1_1 import client
from ceilometerclient import client as ceiloclient
import time
import subprocess
import random

import neat.common as common
from neat.config import *
from neat.db_utils import *

import logging
log = logging.getLogger(__name__)


ERRORS = {
    400: 'Bad input parameter: incorrect or missing parameters',
    401: 'Unauthorized: user credentials are missing',
    403: 'Forbidden: user credentials do not much the ones ' +
         'specified in the configuration file',
    405: 'Method not allowed: the request is made with ' +
         'a method other than the only supported PUT',
    412: 'Precondition failed: the request has been sent more ' +
         'than 5 seconds ago, the states of the hosts/VMs may ' +
         'have changed - retry'}


@contract
def raise_error(status_code):
    """ Raise and HTTPResponse exception with the specified status code.

    :param status_code: An HTTP status code of the error.
     :type status_code: int
    """
    if status_code in ERRORS:
        if status_code == 412 and log.isEnabledFor(logging.INFO):
            log.info('REST service: %s', ERRORS[status_code])
        else:
            log.error('REST service: %s', ERRORS[status_code])
        raise bottle.HTTPResponse(ERRORS[status_code], status_code)
    log.error('REST service: Unknown error')
    raise bottle.HTTPResponse('Unknown error', 500)


@contract
def validate_params(user, password, params):
    """ Validate the input request parameters.

    :param user: A sha1-hashed user name to compare to.
     :type user: str

    :param password: A sha1-hashed password to compare to.
     :type password: str

    :param params: A dictionary of input parameters.
     :type params: dict(str: *)

    :return: Whether the parameters are valid.
     :rtype: bool
    """
    if 'username' not in params or 'password' not in params:
        raise_error(401)
        return False
    if params['username'] != user or \
       params['password'] != password:
        raise_error(403)
        return False
    if 'reason' not in params or \
       'time' not in params or \
       'host' not in params or \
       params['reason'] not in [0, 1] or \
       params['reason'] == 1 and 'vm_uuids' not in params:
        raise_error(400)
        return False
    if params['time'] + 5 < time.time():
        raise_error(412)
        return False
    log.debug('Request parameters validated')
    return True


def start():
    """ Start the global manager web service.
    """
    config = read_and_validate_config([DEFAILT_CONFIG_PATH, CONFIG_PATH],
                                      REQUIRED_FIELDS)

    common.init_logging(
        config['log_directory'],
        'global-manager.log',
        int(config['log_level']))

    state = init_state(config)
    switch_hosts_on(config['ether_wake_interface'],
                    state['host_macs'],
                    state['compute_hosts'],
                    state['db'])

    bottle.debug(True)
    bottle.app().state = {
        'config': config,
        'state': state}

    host = config['global_manager_host']
    port = config['global_manager_port']
    log.info('Starting the global manager listening to %s:%s', host, port)
    bottle.run(host=host, port=port)


@contract
def get_params(request):
    """ Return the request data as a dictionary.

    :param request: A Bottle request object.
     :type request: *

    :return: The request data dictionary.
     :rtype: dict(str: *)
    """
    params = dict(request.forms)
    if 'time' in params:
        params['time'] = float(params['time'])
    if 'reason' in params:
        params['reason'] = int(params['reason'])
    if 'vm_uuids' in params:
        params['vm_uuids'] = params['vm_uuids'].split(',')
    return params


@contract
def get_remote_addr(request):
    """ Return the IP address of the client.

    :param request: A Bottle request object.
     :type request: *

    :return: The IP address of the remote client.
     :rtype: str
    """
    return bottle.request.remote_addr


@bottle.put('/')
def service():
    params = get_params(bottle.request)
    state = bottle.app().state
    validate_params(state['state']['hashed_username'],
                    state['state']['hashed_password'],
                    params)
    log.info('Received a request from %s: %s',
             get_remote_addr(bottle.request),
             str(params))
    try:
        if params['reason'] == 0:
            log.info('Processing an underload of a host %s', params['host'])
            if 'ceilometer' not in params:
                execute_underload(
                    state['config'],
                    state['state'],
                    params['host'])
            else: #request sent from alarm manager after underload alarm
                execute_underload_ceilometer(
                    state['config'],
                    state['state'],
                    params['host'])                
        else:
            log.info('Processing an overload, VMs: %s', str(params['vm_uuids']))
            if 'ceilometer' not in params:
                execute_overload(
                    state['config'],
                    state['state'],
                    params['host'],
                    params['vm_uuids'])
            else: #request sent from alarm manager after overload alarm
                execute_overload_ceilometer(
                    state['config'],
                    state['state'],
                    params['host'],
                    params['vm_uuids'])
    except:
        log.exception('Exception during request processing:')
        raise


@bottle.route('/', method='ANY')
def error():
    message = 'Method not allowed: the request has been made' + \
              'with a method other than the only supported PUT'
    log.error('REST service: %s', message)
    raise bottle.HTTPResponse(message, 405)


@contract
def init_state(config):
    """ Initialize a dict for storing the state of the global manager.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :return: A dict containing the initial state of the global managerr.
     :rtype: dict
    """
    return {'previous_time': 0,
            'db': init_db(config['sql_connection']),
            'nova': client.Client(config['os_admin_user'],
                                  config['os_admin_password'],
                                  config['os_admin_tenant_name'],
                                  config['os_auth_url'],
                                  service_type="compute"),
            'ceilometer': ceiloclient.get_client(2, 
                                    username=config['os_admin_user'],
                                    password=config['os_admin_password'],
                                    tenant_name=config['os_admin_tenant_name'],
                                    auth_url=config['os_auth_url']),            
            'hashed_username': sha1(config['os_admin_user']).hexdigest(),
            'hashed_password': sha1(config['os_admin_password']).hexdigest(),
            'compute_hosts': common.parse_compute_hosts(
                                        config['compute_hosts']),
            'host_macs': {}}


@contract
def execute_underload(config, state, host):
    """ Process an underloaded host: migrate all VMs from the host.

1. Prepare the data about the current states of the hosts and VMs.

2. Call the function specified in the `algorithm_vm_placement_factory`
   configuration option and pass the data on the states of the hosts and VMs.

3. Call the Nova API to migrate the VMs according to the placement
   determined by the `algorithm_vm_placement_factory` algorithm.

4. Switch off the host at the end of the VM migration.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param state: A state dictionary.
     :type state: dict(str: *)

    :param host: A host name.
     :type host: str

    :return: The updated state dictionary.
     :rtype: dict(str: *)
    """
    log.info('Started processing an underload request')
    underloaded_host = host
    hosts_cpu_total, _, hosts_ram_total = state['db'].select_host_characteristics()

    hosts_to_vms = vms_by_hosts(state['nova'], state['compute_hosts'])
    vms_last_cpu = state['db'].select_last_cpu_mhz_for_vms()
    hosts_last_cpu = state['db'].select_last_cpu_mhz_for_hosts()

    # Remove VMs from hosts_to_vms that are not in vms_last_cpu
    # These VMs are new and no data have been collected from them
    for host, vms in hosts_to_vms.items():
        for i, vm in enumerate(vms):
            if not vm in vms_last_cpu:
                del hosts_to_vms[host][i]

    if log.isEnabledFor(logging.DEBUG):
        log.debug('hosts_to_vms: %s', str(hosts_to_vms))

    hosts_cpu_usage = {}
    hosts_ram_usage = {}
    hosts_to_keep_active = set()
    for host, vms in hosts_to_vms.items():
        if vms:
            host_cpu_mhz = hosts_last_cpu[host]
            for vm in vms:
                if vm not in vms_last_cpu:
                    log.info('No data yet for VM: %s - skipping host %s', vm, host)
                    hosts_to_keep_active.add(host)
                    del hosts_cpu_total[host]
                    del hosts_ram_total[host]
                    if host in hosts_cpu_usage:
                        del hosts_cpu_usage[host]
                    if host in hosts_ram_usage:
                        del hosts_ram_usage[host]
                    break
                host_cpu_mhz += vms_last_cpu[vm]
            else:
                hosts_cpu_usage[host] = host_cpu_mhz
                hosts_ram_usage[host] = host_used_ram(state['nova'], host)
        else:
            # Exclude inactive hosts
            del hosts_cpu_total[host]
            del hosts_ram_total[host]

    if log.isEnabledFor(logging.DEBUG):
        log.debug('Host CPU usage: %s', str(hosts_last_cpu))
        log.debug('Host total CPU usage: %s', str(hosts_cpu_usage))

    # Exclude the underloaded host
    del hosts_cpu_usage[underloaded_host]
    del hosts_cpu_total[underloaded_host]
    del hosts_ram_usage[underloaded_host]
    del hosts_ram_total[underloaded_host]

    if log.isEnabledFor(logging.DEBUG):
        log.debug('Excluded the underloaded host %s', underloaded_host)
        log.debug('Host CPU usage: %s', str(hosts_last_cpu))
        log.debug('Host total CPU usage: %s', str(hosts_cpu_usage))

    vms_to_migrate = vms_by_hosts(state['nova'], 
                                  [underloaded_host])[underloaded_host]
    vms_cpu = {}
    for vm in vms_to_migrate:
        if vm not in vms_last_cpu:
            log.info('No data yet for VM: %s - dropping the request', vm)
            log.info('Skipped an underload request')
            return state
        vms_cpu[vm] = state['db'].select_cpu_mhz_for_vm(
            vm,
            int(config['data_collector_data_length']))
    vms_ram = vms_ram_limit(state['nova'], vms_to_migrate)

    # Remove VMs that are not in vms_ram
    # These instances might have been deleted
    for i, vm in enumerate(vms_to_migrate):
        if not vm in vms_ram:
            del vms_to_migrate[i]

    for vm in vms_cpu.keys():
        if not vm in vms_ram:
            del vms_cpu[vm]

    time_step = int(config['data_collector_interval'])
    migration_time = common.calculate_migration_time(
        vms_ram,
        float(config['network_migration_bandwidth']))

    if 'vm_placement' not in state:
        vm_placement_params = common.parse_parameters(
            config['algorithm_vm_placement_parameters'])
        vm_placement_state = None
        vm_placement = common.call_function_by_name(
            config['algorithm_vm_placement_factory'],
            [time_step,
             migration_time,
             vm_placement_params])
        state['vm_placement'] = vm_placement
        state['vm_placement_state'] = {}
    else:
        vm_placement = state['vm_placement']
        vm_placement_state = state['vm_placement_state']

    log.info('Started underload VM placement')
    placement, vm_placement_state = vm_placement(
        hosts_cpu_usage, hosts_cpu_total,
        hosts_ram_usage, hosts_ram_total,
        {}, {},
        vms_cpu, vms_ram,
        vm_placement_state)
    log.info('Completed underload VM placement')
    state['vm_placement_state'] = vm_placement_state

    if log.isEnabledFor(logging.INFO):
        log.info('Underload: obtained a new placement %s', str(placement))

    active_hosts = hosts_cpu_total.keys()
    inactive_hosts = set(state['compute_hosts']) - set(active_hosts)
    prev_inactive_hosts = set(state['db'].select_inactive_hosts())
    hosts_to_deactivate = list(inactive_hosts
                               - prev_inactive_hosts
                               - hosts_to_keep_active)

    if not placement:
        log.info('Nothing to migrate')
        if underloaded_host in hosts_to_deactivate:
            hosts_to_deactivate.remove(underloaded_host)
    else:
        log.info('Started underload VM migrations')
        migrate_vms(state['nova'],
                    config['vm_instance_directory'],
                    placement, 
		    state['db'])
        log.info('Completed underload VM migrations')

    if hosts_to_deactivate:
        switch_hosts_off(config['sleep_command'],
                         hosts_to_deactivate,
                         state['db'])

    log.info('Completed processing an underload request')
    return state

@contract
def execute_underload_ceilometer(config, state, underloaded_host):
    """ Process an underloaded host: migrate all VMs from the host.
    Same as "execute_underload" except measures are collected by ceilometer.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param state: A state dictionary.
     :type state: dict(str: *)

    :param underloaded_host: A host name.
     :type underloaded_host: str

    :return: The updated state dictionary.
     :rtype: dict(str: *)
    """

    log.info('Started processing an underload request')    
    ceilo_client = state['ceilometer']
    nova = state['nova']
    compute_hosts = state['compute_hosts']
    vm_placement_params = common.parse_parameters(
        config['algorithm_vm_placement_parameters'])
    
    """Collect data for each hosts for vm_placement algorithm"""

    #dict of (host, cpu_max_frequency)
    hosts_cpu_total = get_hosts_cpu_frequency(ceilo_client, 
                                              compute_hosts)
    #dict of (host, cpu_frequency_usage)
    hosts_cpu_usage = get_hosts_last_cpu_usage(ceilo_client, 
                                               compute_hosts)
    #dict of (host, total_ram)
    hosts_ram_total = get_hosts_ram_total(nova, 
                                         compute_hosts)
    #dict of (host, ram_used)
    hosts_ram_usage = get_hosts_ram_usage(nova, 
                                          compute_hosts)

    """Collect cpu util data for each vms"""
    #dict(vm: last_cpu_util)
    vms_last_cpu_util = get_vms_on_host_last_cpu_util(nova, 
                                                      ceilo_client,
                                                      compute_hosts)
   
    """Keep info for host only if active and if we have data for each vm on it """
 
    active_hosts = [] #host with running vms
    keep_active_hosts = [] #hosts with running vms without enough collected data
    inactive_hosts = [] #host without running vms

    vms_hosts = vms_by_hosts(nova, compute_hosts) #dict(host: [vms])
    log.debug('vms_hosts %(vms_hosts)s', {'vms_hosts':vms_hosts})

    #classify every host as active, inactive, keep_active
    for host, vms in vms_hosts.items():
        if vms: #host with vms
            for vm in vms:
                #we haven't collected any data for this new vms
                if vm not in vms_last_cpu_util:
                    if host == underloaded_host:
                        log.info('No data yet for VM: %s - dropping the request', vm)
                        log.info('Skipped an underload request')
                        return state

                    keep_active_hosts.append(host)
                    #eliminate host without sufficient data from dicts
                    del hosts_cpu_total[host]
                    del hosts_cpu_usage[host]
                    del hosts_ram_total[host]
                    del hosts_ram_usage[host]

                    break
            else: #for cycle executed without break
                active_hosts.append(host) #we have collected data for each vms on host
        else: #host without vms
            inactive_hosts.append(host)
            #eliminate inactive host from dicts
            del hosts_cpu_total[host]
            del hosts_cpu_usage[host]
            del hosts_ram_total[host]
            del hosts_ram_usage[host]

    #exclude the underloaded host
    del hosts_cpu_total[underloaded_host]
    del hosts_cpu_usage[underloaded_host]
    del hosts_ram_total[underloaded_host]
    del hosts_ram_usage[underloaded_host]

    """For each vm to migrate, get last n cpu usage values and ram allocation"""

    #updated list of vms on underloaded host, i.e. vms to migrate  
    vms_to_migrate = vms_by_hosts(nova, [underloaded_host])[underloaded_host]
    #number of last cpu values to average
    last_n_vm_cpu = vm_placement_params['last_n_vm_cpu']
    #dict(vms: [cpu_usage])
    #We have already checked that there is at least one sample per vm
    vms_cpu = get_vms_last_n_cpu_util(ceilo_client, vms_to_migrate,
                                      last_n_vm_cpu, True) 
    #dict(vm: ram_allocated)
    vms_ram = vms_ram_limit(nova, vms_to_migrate)

    """Prepare parameters for vm_placement algorithm"""

    time_step = int(config['data_collector_interval']) #I don't use this information anymore
    migration_time = common.calculate_migration_time(
        vms_ram,
        float(config['network_migration_bandwidth']))

    if 'vm_placement' not in state:
        vm_placement_params = common.parse_parameters(
            config['algorithm_vm_placement_parameters'])
        vm_placement = common.call_function_by_name(
            config['algorithm_vm_placement_factory'],
            [time_step,
             migration_time,
             vm_placement_params])
        state['vm_placement'] = vm_placement
        state['vm_placement_state'] = None
    else:
        vm_placement = state['vm_placement']

    """Start vm placement algorithm"""

    log.info('Started underload VM placement')
    placement, state['vm_placement_state'] = vm_placement(
        hosts_cpu_usage, hosts_cpu_total,
        hosts_ram_usage, hosts_ram_total,
        {}, {},
        vms_cpu, vms_ram,
        state['vm_placement_state'])
    log.info('Completed underload VM placement')

    log.info('Underload: obtained a new placement %s', str(placement))

    """Migrate vms"""

    if not placement:
        log.info('Nothing to migrate')
    else:
        log.info('Started underload VM migrations')
        migrate_vms(nova, #migrate vms to chosen hosts
                    config['vm_instance_directory'],
                    placement)
        log.info('Completed underload VM migrations')

    """Deactivate host with no vms after migration"""

    vms_hosts = vms_by_hosts(nova, 
                             compute_hosts) #updated vms to host information, after migrations
    hosts_to_deactivate = ([h for h in compute_hosts 
                            if not vms_hosts[h]]) #list of hosts without vms after migrations

    if hosts_to_deactivate:
        switch_hosts_off(config['sleep_command'], #switch off all hosts with no vms on them
                         hosts_to_deactivate)

    log.info('Completed processing an underload request')
    return state

@contract
def execute_overload(config, state, host, vm_uuids):
    """ Process an overloaded host: migrate the selected VMs from it.

1. Prepare the data about the current states of the hosts and VMs.

2. Call the function specified in the `algorithm_vm_placement_factory`
   configuration option and pass the data on the states of the hosts and VMs.

3. Call the Nova API to migrate the VMs according to the placement
   determined by the `algorithm_vm_placement_factory` algorithm.

4. Switch on the inactive hosts required to accommodate the VMs.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param state: A state dictionary.
     :type state: dict(str: *)

    :param host: A host name.
     :type host: str

    :param vm_uuids: A list of VM UUIDs to migrate from the host.
     :type vm_uuids: list(str)

    :return: The updated state dictionary.
     :rtype: dict(str: *)
    """
    log.info('Started processing an overload request')
    overloaded_host = host
    hosts_cpu_total, _, hosts_ram_total = state['db'].select_host_characteristics()
    hosts_to_vms = vms_by_hosts(state['nova'], state['compute_hosts'])
    vms_last_cpu = state['db'].select_last_cpu_mhz_for_vms()
    hosts_last_cpu = state['db'].select_last_cpu_mhz_for_hosts()

    # Remove VMs from hosts_to_vms that are not in vms_last_cpu
    # These VMs are new and no data have been collected from them
    for host, vms in hosts_to_vms.items():
        for i, vm in enumerate(vms):
            if not vm in vms_last_cpu:
                del hosts_to_vms[host][i]

    hosts_cpu_usage = {}
    hosts_ram_usage = {}
    inactive_hosts_cpu = {}
    inactive_hosts_ram = {}
    for host, vms in hosts_to_vms.items():
        if vms:
            host_cpu_mhz = hosts_last_cpu[host]
            for vm in vms:
                if vm not in vms_last_cpu:
                    log.info('No data yet for VM: %s - skipping host %s', vm, host)
                    del hosts_cpu_total[host]
                    del hosts_ram_total[host]
                    if host in hosts_cpu_usage:
                        del hosts_cpu_usage[host]
                    if host in hosts_ram_usage:
                        del hosts_ram_usage[host]
                    break
                host_cpu_mhz += vms_last_cpu[vm]
            else:
                hosts_cpu_usage[host] = host_cpu_mhz
                hosts_ram_usage[host] = host_used_ram(state['nova'], host)
        else:
            inactive_hosts_cpu[host] = hosts_cpu_total[host]
            inactive_hosts_ram[host] = hosts_ram_total[host]
            del hosts_cpu_total[host]
            del hosts_ram_total[host]

    # Exclude the overloaded host
    del hosts_cpu_usage[overloaded_host]
    del hosts_cpu_total[overloaded_host]
    del hosts_ram_usage[overloaded_host]
    del hosts_ram_total[overloaded_host]

    if log.isEnabledFor(logging.DEBUG):
        log.debug('Host CPU usage: %s', str(hosts_last_cpu))
        log.debug('Host total CPU usage: %s', str(hosts_cpu_usage))

    vms_to_migrate = vm_uuids
    vms_cpu = {}
    for vm in vms_to_migrate:
        if vm not in vms_last_cpu:
            log.info('No data yet for VM: %s - dropping the request', vm)
            log.info('Skipped an underload request')
            return state
        vms_cpu[vm] = state['db'].select_cpu_mhz_for_vm(
            vm,
            int(config['data_collector_data_length']))
    vms_ram = vms_ram_limit(state['nova'], vms_to_migrate)

    # Remove VMs that are not in vms_ram
    # These instances might have been deleted
    for i, vm in enumerate(vms_to_migrate):
        if not vm in vms_ram:
            del vms_to_migrate[i]

    for vm in vms_cpu.keys():
        if not vm in vms_ram:
            del vms_cpu[vm]

    time_step = int(config['data_collector_interval'])
    migration_time = common.calculate_migration_time(
        vms_ram,
        float(config['network_migration_bandwidth']))

    if 'vm_placement' not in state:
        vm_placement_params = common.parse_parameters(
            config['algorithm_vm_placement_parameters'])
        vm_placement_state = None
        vm_placement = common.call_function_by_name(
            config['algorithm_vm_placement_factory'],
            [time_step,
             migration_time,
             vm_placement_params])
        state['vm_placement'] = vm_placement
        state['vm_placement_state'] = {}
    else:
        vm_placement = state['vm_placement']
        vm_placement_state = state['vm_placement_state']

    log.info('Started overload VM placement')
    placement, vm_placement_state = vm_placement(
        hosts_cpu_usage, hosts_cpu_total,
        hosts_ram_usage, hosts_ram_total,
        inactive_hosts_cpu, inactive_hosts_ram,
        vms_cpu, vms_ram,
        vm_placement_state)
    log.info('Completed overload VM placement')
    state['vm_placement_state'] = vm_placement_state

    if log.isEnabledFor(logging.INFO):
        log.info('Overload: obtained a new placement %s', str(placement))

    if not placement:
        log.info('Nothing to migrate')
    else:
        hosts_to_activate = list(
            set(inactive_hosts_cpu.keys()).intersection(
                set(placement.values())))
        if hosts_to_activate:
            switch_hosts_on(config['ether_wake_interface'],
                            state['host_macs'],
                            hosts_to_activate,
                            state['db'])
        log.info('Started overload VM migrations')
        migrate_vms(state['nova'],
                    config['vm_instance_directory'],
                    placement,
		    state['db'])
        log.info('Completed overload VM migrations')
    log.info('Completed processing an overload request')
    return state

@contract
def execute_overload_ceilometer(config, state, overloaded_host, vm_uuids):
    """Process an overloaded host: migrate the selected VMs from it.
    Same as "execute_overload" except measures are collected by ceilometer.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param state: A state dictionary.
     :type state: dict(str: *)

    :param overloaded_host: A host name.
     :type overloaded_host: str

    :param vm_uuids: A list of VM UUIDs to migrate from the host.
     :type vm_uuids: list(str)

    :return: The updated state dictionary.
     :rtype: dict(str: *)
    """

    log.info('Started processing an overload request')
    ceilo_client = state['ceilometer']
    nova = state['nova']
    compute_hosts = state['compute_hosts']
    vm_placement_params = common.parse_parameters(
        config['algorithm_vm_placement_parameters'])
    
    """Collect data for each hosts for vm_placement algorithm"""

    #dict of (host, cpu_max_frequency)
    hosts_cpu_total = get_hosts_cpu_frequency(ceilo_client, 
                                              compute_hosts)
    #dict of (host, cpu_frequency_usage)
    hosts_cpu_usage = get_hosts_last_cpu_usage(ceilo_client, 
                                               compute_hosts)
    #dict of (host, total_ram)
    hosts_ram_total = get_hosts_ram_total(nova, 
                                         compute_hosts)
    #dict of (host, ram_used)
    hosts_ram_usage = get_hosts_ram_usage(nova, 
                                          compute_hosts)

    """Collect cpu util data for each vms"""
    #dict(vm: last_cpu_util)
    vms_last_cpu_util = get_vms_on_host_last_cpu_util(nova, 
                                                      ceilo_client,
                                                      compute_hosts)

    """Keep info for host only if active and if we have data for each vm on it """
    
    active_hosts = [] #host with running vms
    keep_active_hosts = [] #hosts with running vms without enough collected data
    inactive_hosts = [] #host without running vms

    inactive_hosts_cpu = {}
    inactive_hosts_ram = {}

    vms_hosts = vms_by_hosts(nova, compute_hosts) #dict(host: [vms])
    log.debug('vms_hosts %(vms_hosts)s', {'vms_hosts':vms_hosts})

    #classify every host as active, inactive, keep_active
    for host, vms in vms_hosts.items():
        if vms: #host with vms
            for vm in vms:
                #we haven't collected any data for this new vms
                if vm not in vms_last_cpu_util:
                    #no data for vm to migrate
                    if vm in vm_uuids:
                        log.info('No data yet for VM: %s - dropping the request', vm)
                        log.info('Skipped an overload request')
                        return state

                    keep_active_hosts.append(host)
                    #eliminate host without sufficient data from dicts
                    del hosts_cpu_total[host]
                    del hosts_cpu_usage[host]
                    del hosts_ram_total[host]
                    del hosts_ram_usage[host]

                    break
            else: #for cycle executed without break
                active_hosts.append(host) #we have collected data for each vms on host
        else: #host without vms
            inactive_hosts.append(host)
            inactive_hosts_cpu = hosts_cpu_total[host]
            inactive_hosts_ram = hosts_ram_total[host]
            #eliminate inactive host from dicts
            del hosts_cpu_total[host]
            del hosts_cpu_usage[host]
            del hosts_ram_total[host]
            del hosts_ram_usage[host]

    #exclude the overloaded host
    del hosts_cpu_total[overloaded_host]
    del hosts_cpu_usage[overloaded_host]
    del hosts_ram_total[overloaded_host]
    del hosts_ram_usage[overloaded_host]

    """For each vm to migrate, get last n cpu usage values and ram allocation"""

    #updated list of vms on overloaded host
    vms_overloaded_host = vms_by_hosts(nova, [overloaded_host])[overloaded_host]
    #updated list of vms to migrate. We eliminate from the list, vm that have been deleted
    vms_to_migrate = list(set(vm_uuids).intersection(set(vms_overloaded_host)))
    #number of last cpu values to average
    last_n_vm_cpu = vm_placement_params['last_n_vm_cpu']
    #dict(vms: [cpu_usage])
    vms_cpu = get_vms_last_n_cpu_util(ceilo_client, vms_to_migrate,
                                      last_n_vm_cpu, True) 
    #dict(vm: ram_allocated)
    vms_ram = vms_ram_limit(nova, vms_to_migrate)

    """Prepare parameters for vm_placement algorithm"""

    time_step = int(config['data_collector_interval']) #I don't use this information anymore
    migration_time = common.calculate_migration_time(
        vms_ram,
        float(config['network_migration_bandwidth']))

    if 'vm_placement' not in state:
        vm_placement_params = common.parse_parameters(
            config['algorithm_vm_placement_parameters'])
        vm_placement = common.call_function_by_name(
            config['algorithm_vm_placement_factory'],
            [time_step,
             migration_time,
             vm_placement_params])
        state['vm_placement'] = vm_placement
        state['vm_placement_state'] = None
    else:
        vm_placement = state['vm_placement']

    """Start vm placement algorithm"""

    log.info('Started overload VM placement')
    placement, state['vm_placement_state'] = vm_placement(
        hosts_cpu_usage, hosts_cpu_total,
        hosts_ram_usage, hosts_ram_total,
        inactive_hosts_cpu, inactive_hosts_ram,
        vms_cpu, vms_ram,
        state['vm_placement_state'])
    log.info('Completed overload VM placement')

    log.info('overload: obtained a new placement %s', str(placement))

    """Migrate vms"""

    if not placement:
        log.info('Nothing to migrate')
    else:
        #activate inactive host to which vms will be migrated
        hosts_to_activate = list(
            set(inactive_hosts_cpu.keys()).intersection(
                set(placement.values())))
        if hosts_to_activate:
            switch_hosts_on(config['ether_wake_interface'],
                            state['host_macs'],
                            hosts_to_activate)
        log.info('Started overload VM migrations')
        migrate_vms(nova, #migrate vms to chosen hosts
                    config['vm_instance_directory'],
                    placement)
        log.info('Completed overload VM migrations')
    log.info('Completed processing an overload request')
    return state

@contract
def get_hosts_cpu_frequency(ceilo, hosts):
    """Get cpu frequency for each host in hosts.

    :param ceilo: A Ceilo client.
     :type ceilo: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :return: A dictionary of (host, cpu_frequency)
     :rtype: dict(str: *)
    """
    hosts_cpu_total = dict() #dict of (host, cpu_max_frequency)
    for host in hosts:
        host_id = "_".join([host, host])
        cpu_frequency_list = ceilo.samples.list(meter_name='compute.node.cpu.frequency', 
            limit=1, q=[{'field':'resource_id','op':'eq','value':host_id}])
        if cpu_frequency_list:
            hosts_cpu_total[host] = cpu_frequency_list[0].counter_volume

    return hosts_cpu_total

@contract
def get_hosts_last_cpu_usage(ceilo, hosts):
    """Get last cpu usage of hosts.

    :param ceilo: A Ceilo client.
     :type ceilo: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :return: A dictionary of (host, cpu_usage)
     :rtype: dict(str: *)
    """

    hosts_cpu_usage = dict() #dict of (host, cpu_frequency_usage)
    for host in hosts:
        host_id = "_".join([host, host])
        cpu_usage_list = (
            ceilo.samples.list(meter_name='compute.node.cpu.percent',
                               limit=1, 
                               q=[{'field':'resource_id',
                                   'op':'eq',
                                   'value':host_id}]))
        if cpu_usage_list:
            hosts_cpu_usage[host] = cpu_usage_list[0].counter_volume

    return hosts_cpu_usage

@contract
def get_hosts_ram_total(nova, hosts):
    """Get total RAM (free+used) of hosts.

    :param nova: A Nova client
     :type nova: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :return: A dictionary of (host, total_ram)
     :rtype: dict(str: *)
    """

    hosts_ram_total = dict() #dict of (host, total_ram)
    for host in hosts:
        data = nova.hosts.get(host)
        hosts_ram_total[host] = data[0].memory_mb

    return hosts_ram_total

@contract
def get_hosts_ram_usage(nova, hosts):
    """Get RAM usage of hosts.

    :param nova: A Nova client
     :type nova: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :return: A dictionary of (host, ram_usage)
     :rtype: dict(str: *)
    """

    hosts_ram_usage = dict() #dict of (host, ram_usage)
    for host in hosts:
        hosts_ram_usage[host] = host_used_ram(nova, host)

    return hosts_ram_usage

def get_vms_on_host_last_cpu_util(nova, ceilo, hosts):
    """Get last cpu usage for each vm on each host.
  
    :param nova: A Nova client
     :type nova: *

    :param ceilo: A Ceilo client.
     :type ceilo: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :return: A dictionary of (vm, cpu_usage)
     :rtype: dict(str: *)
    """

    vms_last_cpu_util = dict() #dict of (vm, cpu_usage)
    vms_hosts = vms_by_hosts(nova, hosts) #dict(host: [vms])
    for vms in vms_hosts.values():
        cur_host_vms_last_cpu_util = get_vms_last_n_cpu_util(ceilo, vms)
        for vm in cur_host_vms_last_cpu_util.keys():
            vms_last_cpu_util[vm] = cur_host_vms_last_cpu_util[vm]

    return vms_last_cpu_util


@contract
def host_used_ram(nova, host):
    """ Get the used RAM of the host using the Nova API.

    :param nova: A Nova client.
     :type nova: *

    :param host: A host name.
     :type host: str

    :return: The used RAM of the host.
     :rtype: int
    """
    data = nova.hosts.get(host)
    if len(data) > 2 and data[2].memory_mb != 0:
        return data[2].memory_mb
    return data[1].memory_mb


@contract
def host_mac(host):
    """ Get mac address of a host.

    :param host: A host name.
     :type host: str

    :return: The mac address of the host.
     :rtype: str
    """
    mac = subprocess.Popen(
        ("ping -c 1 {0} > /dev/null;" +
         "arp -a {0} | awk '{{print $4}}'").format(host),
        stdout=subprocess.PIPE,
        shell=True).communicate()[0].strip()
    if len(mac) != 17:
        log.warning('Received a wrong mac address for %s: %s',
                    host, mac)
        return ''
    return mac


@contract
def migrate_vms(nova, vm_instance_directory, placement, db=None):
    """ Synchronously live migrate a set of VMs.

    :param db: The database object.
     :type db: *
  
    :param nova: A Nova client.
     :type nova: *

    :param vm_instance_directory: The VM instance directory.
     :type vm_instance_directory: str

    :param placement: A dict of VM UUIDs to host names.
     :type placement: dict(str: str)
    """
    retry_placement = {}
    vms = placement.keys()
    # Migrate only 2 VMs at a time, as otherwise migrations may fail
    #vm_pairs = [vms[x:x + 2] for x in xrange(0, len(vms), 2)]
    # Temporary migrates VMs one by one
    vm_pairs = [vms[x:x + 1] for x in xrange(0, len(vms), 1)]
    for vm_pair in vm_pairs:
        start_time = time.time()
        for vm_uuid in vm_pair:
            migrate_vm(nova, vm_instance_directory, vm_uuid, placement[vm_uuid])

        time.sleep(10)

        while True:
            for vm_uuid in list(vm_pair):
                vm = nova.servers.get(vm_uuid)
                if log.isEnabledFor(logging.DEBUG):
                    log.debug('VM %s: %s, %s',
                              vm_uuid,
                              vm_hostname(vm),
                              vm.status)
                if vm_hostname(vm) == placement[vm_uuid] and \
                    vm.status == u'ACTIVE':
                    vm_pair.remove(vm_uuid)
                    if db is not None: #None if using ceilometer
                        db.insert_vm_migration(vm_uuid, placement[vm_uuid])
                    if log.isEnabledFor(logging.INFO):
                        log.info('Completed migration of VM %s to %s',
                                 vm_uuid, placement[vm_uuid])
                elif time.time() - start_time > 300 and \
                    vm_hostname(vm) != placement[vm_uuid] and \
                    vm.status == u'ACTIVE':
                    vm_pair.remove(vm_uuid)
                    retry_placement[vm_uuid] = placement[vm_uuid]
                    if log.isEnabledFor(logging.WARNING):
                        log.warning('Time-out for migration of VM %s to %s, ' +
                                    'will retry', vm_uuid, placement[vm_uuid])
                else:
                    break
            else:
                break
            time.sleep(3)

    if retry_placement:
        if log.isEnabledFor(logging.INFO):
            log.info('Retrying the following migrations: %s',
                     str(retry_placement))
        migrate_vms(nova, vm_instance_directory, retry_placement, db)


@contract
def migrate_vm(nova, vm_instance_directory, vm, host):
    """ Live migrate a VM.

    :param nova: A Nova client.
     :type nova: *

    :param vm_instance_directory: The VM instance directory.
     :type vm_instance_directory: str

    :param vm: The UUID of a VM to migrate.
     :type vm: str

    :param host: The name of the destination host.
     :type host: str
    """
    # To avoid problems with migration, need the following:
    subprocess.call('chown -R nova:nova ' + vm_instance_directory,
                    shell=True)
    nova.servers.live_migrate(vm, host, False, False)
    if log.isEnabledFor(logging.INFO):
        log.info('Started migration of VM %s to %s', vm, host)


@contract
def switch_hosts_off(sleep_command, hosts, db=None):
    """ Switch hosts to a low-power mode.

    :param db: The database object.
     :type db: *

    :param sleep_command: A Shell command to switch off a host.
     :type sleep_command: str

    :param hosts: A list of hosts to switch off.
     :type hosts: list(str)
    """
    if sleep_command:
        for host in hosts:
            command = 'ssh {0} "{1}"'. \
                format(host, sleep_command)
            if log.isEnabledFor(logging.DEBUG):
                log.debug('Calling: %s', command)
            subprocess.call(command, shell=True)
    if log.isEnabledFor(logging.INFO):
        log.info('Switched off hosts: %s', str(hosts))
    if db is not None:
        db.insert_host_states(dict((x, 0) for x in hosts))


@contract
def switch_hosts_on(ether_wake_interface, host_macs, hosts, db=None):
    """ Switch hosts to the active mode.

    :param db: The database object.
     :type db: *

    :param ether_wake_interface: An interface to send a magic packet.
     :type ether_wake_interface: str

    :param host_macs: A dict of host names to mac addresses.
     :type host_macs: dict(str: str)

    :param hosts: A list of hosts to switch on.
     :type hosts: list(str)
    """
    for host in hosts:
        if host not in host_macs:
            host_macs[host] = host_mac(host)
        command = 'ether-wake -i {0} {1}'.format(
            ether_wake_interface,
            host_macs[host])
        if log.isEnabledFor(logging.DEBUG):
            log.debug('Calling: %s', command)
        subprocess.call(command, shell=True)
    if log.isEnabledFor(logging.INFO):
        log.info('Switched on hosts: %s', str(hosts))
    if db is not None:
        db.insert_host_states(dict((x, 1) for x in hosts))
