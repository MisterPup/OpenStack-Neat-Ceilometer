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
		log.info("Received underload request")
		ceilo_client = state['ceilometer']

		"""
		Recover alarm info
		"""
		alarm_id = json.get('alarm_id')		
		alarm = ceilo_client.alarms.get(alarm_id)
		resource_id = alarm.__getattr__('threshold_rule')['query'][0]['value'] #compute1_compute1 (host_node)
		hostname = resource_id.split('_')[0] #compute1
		#alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
		#alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
		#alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch
		alarm_time_sec = time.time() #if repeat_action, than every minute a request is sent

		#log
		"""
		Send information to global manager
		"""
		r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
		'password': state['hashed_password'], 'ceilometer' : 1, 'time': time.time(), 'host': hostname, 'reason': 0})) #send request to global manager
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
		#alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
		#alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
		#alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch
		alarm_time_sec = time.time() #if repeat_action, than every minute a request is sent

		#log
		"""
		Recover list of vms in "alarmed" host
		"""
		all_vms = nova_client.servers.list() #list of vms (Server objects)
		host_vms = [vm for vm in all_vms if getattr(vm, 'OS-EXT-SRV-ATTR:host') == hostname] #list of vms in "alarmed" host

		"""
		Recover allocated ram of vms (put in function)
		"""
		vms_ram = dict() #dict(vm_id: vm_ram)
		for vm in host_vms:
			vm_id = str(vm.id) #resource_id
			#why does it return two samples? We take only the first one
			vm_ram_sample = ceilo_client.samples.list(meter_name='memory', q=[{'field':'resource_id','op':'eq','value':vm_id}])[0]
			vm_ram = getattr(vm_ram_sample, 'resource_metadata')['memory_mb']
			vms_ram[vm_id] = int(vm_ram)

		"""
		Recover average cpu utilization of vms (put in function)
		"""
		interval_cfg = 600 #ten minutes (read it from configuration file!)
		start_sec = time.time() - interval_cfg
		start_time = datetime.fromtimestamp(start_sec).strftime('%Y-%m-%dT%H:%M:%S')

		vms_avg_cpu_util = dict() #dict(vm_id: vm_avg_cpu_util)
		for vm in host_vms:
			vm_id = str(vm.id) #resource_id
			#get average cpu utilization of vm in the last ten minutes
			#why does it return two statistics? 
			vm_cpu_util_stats = ceilo_client.statistics.list(meter_name='cpu_util', q=[{'field':'resource_id','op':'eq','value':vm_id}, {'field':'timestamp','op':'gt','value':start_time}])[0]
			vm_avg_cpu_util = getattr(vm_cpu_util_stats, 'avg')
			vms_avg_cpu_util[vm_id] = vm_avg_cpu_util

		"""
		Recover state information
		"""
		time_step = int(config['data_collector_interval']) #I don't use this information anymore
		migration_time = common.calculate_migration_time(
			vms_ram,
			float(config['network_migration_bandwidth']))

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
			vms_avg_cpu_util, vms_ram, state['vm_selection_state'])
		log.info('Completed VM selection')
		
		"""
		Send information to global manager
		"""
		r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
				'password': state['hashed_password'], 'ceilometer' : 1, 'time': alarm_time_sec, 'host': hostname, 'reason': 1, 'vm_uuids': ','.join(vm_uuids)}))
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
