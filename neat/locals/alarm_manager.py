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

""" The alarm manager module.
Add description here
"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient

from neat.config import *
import neat.common as common

from contracts import contract
import time
from datetime import datetime
from hashlib import sha1

import bottle
import requests

import logging
log = logging.getLogger(__name__)
log_selection = logging.getLogger('.vm_selection')

def start():
    """ Start the alarm manager web service.
    """
    config = read_and_validate_config([DEFAILT_CONFIG_PATH, CONFIG_PATH],
                                        REQUIRED_FIELDS)

    common.init_logging(config['log_directory'],
                'alarm-manager.log',
                int(config['log_level']))

    state = init_state(config)
    bottle.debug(True)
    bottle.app().state = {
        'config': config,
        'state': state}

    host = config['alarm_manager_host']
    port = config['alarm_manager_port']
    log.info('Starting the alarm manager listening to %s:%s', host, port)
    bottle.run(host=host, port=port)

@bottle.post('/underload')
def service_underload():
    """
    Process an underloaded host request. 
    Prepare data for global manager:
        - name of underloaded host
        - alarm received timestamp
    """
    json = bottle.request.json
    config = bottle.app().state['config']
    state = bottle.app().state['state']

    if not json is None:
        log.info('Received underload request')
        nova_client = state['nova']
        ceilo_client = state['ceilometer']

        """
        Recover alarm info
        """
        alarm_id = json.get('alarm_id')
        log.info('Underload alarm id: %(id)s', {'id':alarm_id})    

        alarm = ceilo_client.alarms.get(alarm_id)
        resource_id = alarm.__getattr__('threshold_rule')['query'][0]['value'] #compute1_compute1 (host_node)
        hostname = resource_id.split('_')[0] #compute1
        hostname = hostname.encode('ascii','ignore') 
        #alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
        #alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
        #alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch
        #if repeat_action, and state is still "alarmed", than every minute a request is sent
        alarm_time_sec = time.time()

        """
        Check if this is the first time sending the same underload request
        """
        #list of vms in "alarmed" host
        host_vms = common.vms_by_hosts(nova_client, 
                                       [hostname])[hostname]

        """
        If 'repeat_action' attribute of alarm is set to True
        and the underloaded host has already been set to inactive
        but it cannot be put into sleep state,
        than a request is sent every minute because the host is still underloaded.
        We check that the underloaded host has vms on it;
        if positive, this is the first time it is sending an underload request, and
        the algorithm proceeds;
        else we skip this request
        """
        #if the host has already been set to inactive, so no vms on it
        if not host_vms:
            log.info('Host %(name)s without vms, skip underload request', {'name': hostname})
            return state

        log.info("Sending request to global manager")
        """
        Send information to global manager
        """
        r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
        'password': state['hashed_password'], 'ceilometer_alarm' : 1, 'time': time.time(), 'host': hostname, 'reason': 0})) #send request to global manager
        log.info("Underload request sent to global manager")

@bottle.post('/overload')
def service_overload():
    """
    Process an overloaded host request. 
    Prepare data for global manager:
        - name of overloaded host
        - alarm received timestamp
        - selected vms to migrate
    """
    json = bottle.request.json
    config = bottle.app().state['config']
    state = bottle.app().state['state']

    if not json is None:
        log.info("Received overload request")
        nova_client = state['nova']
        ceilo_client = state['ceilometer']

        #try except
        """
        Recover alarm info
        """
        alarm_id = json.get('alarm_id')
        alarm = ceilo_client.alarms.get(alarm_id) #recover alarm info
        resource_id = alarm.__getattr__('threshold_rule')['query'][0]['value'] #compute1_compute1
        hostname = resource_id.split('_')[0] #get host from resource_id: compute1_compute1 -> compute1
        hostname = hostname.encode('ascii','ignore')
        #alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
        #alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
        #alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch
        #if repeat_action, and state is still "alarmed", than every minute a request is sent
        alarm_time_sec = time.time()

        """
        Check if this is the first time sending the same overload request.
        Only happens when the threshold is too low.
        """
        #list of vms in "alarmed" host
        host_vms = common.vms_by_hosts(nova_client,
                                       [hostname])[hostname]

        """
        If 'repeat_action' attribute of alarm is set to True
        and the overload threshold is too low
        than a request is sent every minute because the host is still overloaded.
        We proceed only if the overloaded host has vms on it
        """

        if not host_vms:
            log.info('Host %(name)s without vms, skip overload request', {'name': hostname})
            return state

        """
        Recover list of vms in "alarmed" host
        """
        #list of vms in "alarmed" host
        host_vms = common.vms_by_hosts(nova_client, 
                                       [hostname])[hostname]
        log.info("VMs on alarmed host '%(name)s': %(vms)s", {'name':hostname, 'vms':host_vms})

        """
        Recover allocated ram of vms (put in function)
        """
        #dict(vm_id: vm_ram)
        vms_ram = common.vms_ram_limit(nova_client, host_vms)
        log.debug('vms_ram: %(vms_ram)s', {'vms_ram':vms_ram})

        """
        Recover last n cpu utilization values (put in function)
        """
        vm_selection_params = common.parse_parameters(
            config['algorithm_vm_selection_parameters'])
        #number of last cpu values to recover
        last_n = vm_selection_params['last_n']
        log.debug('last_n_cpu: %(last)s', {'last':last_n})     

        #dict(vm: [cpu_usage])
        vms_last_n_cpu_util = common.get_vms_last_n_cpu_util(ceilo_client, 
                                                             host_vms,
                                                             last_n,
                                                             True)

        #check that there are enough data for each vms
        for vm in vms_last_n_cpu_util:
            #we haven't collected enough data for this vm
            if len(vms_last_n_cpu_util[vm]) != last_n:
                log.info('No data yet for VM: %s - dropping the request', vm)
                log.info('Skipped an overload request')
                return state
        log.debug('vms_last_n_cpu_util: %(last_cpu)s', {'last_cpu':vms_last_n_cpu_util})

        """
        Recover state information
        """
        time_step = int(config['data_collector_interval']) #I don't use this information anymore
        migration_time = common.calculate_migration_time(
            vms_ram,
            float(config['network_migration_bandwidth']))

        log.info('Loading VM selection parameters')

        if 'vm_selection' not in state:
            vm_selection_params = common.parse_parameters(
                config['algorithm_vm_selection_parameters'])
            vm_selection = common.call_function_by_name(
            config['algorithm_vm_selection_factory'],
            [time_step,
             migration_time,
             vm_selection_params])
            state['vm_selection'] = vm_selection
            state['vm_selection_state'] = None
        else:
            vm_selection = state['vm_selection']

        """
        Select vms to migrate
        """
        log.info('Started VM selection')
        vm_uuids, state['vm_selection_state'] = vm_selection(
            vms_last_n_cpu_util, vms_ram, state['vm_selection_state'])
        log.info('Completed VM selection')
        
        log_selection.info("SELECTION")
        log_selection.info(vms_last_n_cpu_util)
        log_selection.info(vms_ram)
        log_selection.info(vm_uuids)
 
        """
        Send information to global manager
        """
        r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
                'password': state['hashed_password'], 'ceilometer_alarm' : 1, 'time': alarm_time_sec, 'host': hostname, 'reason': 1, 'vm_uuids': ','.join(vm_uuids)}))
        log.info("Overload request sent to global manager")

@bottle.route('/', method='ANY')
def error():
    message = ('Method not allowed: the request has been made' +
              'with a method other than the only supported POST')
    log.error('REST service: %s', message)
    raise bottle.HTTPResponse(message, 405)

@contract
def init_state(config):
    """ Initialize a dict for storing the state of the alarm manager.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :return: A dict containing the initial state of the alarm managerr.
     :rtype: dict
    """
    #do we need to add other parameters to state?
    return {'previous_time': 0,
            'nova': novaclient.Client(3, config['os_admin_user'],
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
            'compute_hosts': common.parse_compute_hosts(config['compute_hosts']),
            'host_macs': {}}
