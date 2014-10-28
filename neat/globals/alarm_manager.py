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

#add import here
from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient
from neat.config import *

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
	request = bottle.request
	json = request.json

	if not json is None:
		ceilo_client = state['ceilometer']

		"""
		Recover alarm info
		"""
		alarm_id = json.get('alarm_id')		
		alarm = ceilo_client.alarms.get(alarm_id)
		resource_id = alarm.__getattr__('threshold_rule')['query'][0]['value'] #compute1_compute1 (host_node)
		hostname = resource_id.split('_')[0] #compute1
		alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
		alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
		alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch

		#log
		"""
		Send information to global manager
		"""
		r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
		'password': state['hashed_password'], 'time': time.time(), 'host': hostname, 'reason': 0})) #send request to global manager
    
@bottle.post('/overload')
def service_overload():
	request = bottle.request
	json = request.json

	if not json is None:
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
		alarm_timestamp = alarm.__getattr__('state_timestamp') #get timestamp of last state changing
		alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
		alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch

		#log
		"""
		Recover list of vms in "alarmed" host
		"""
		all_vms = nova_client.servers.list()
		host_vms = [vm for vm in all_vms if getattr(vm, 'OS-EXT-SRV-ATTR:host') == hostname] #list of vms in "alarmed" host

		"""
		Recover allocated ram of vms
		"""
		vms_ram = list() #list of {vm_id, vm_ram} tuples
		for vm in host_vms:
			vm_id = vm.id #resource_id
			#why does it return two samples? We take only the first one
			vm_ram_sample = ceilo_client.samples.list(meter_name='memory', q=[{'field':'resource_id','op':'eq','value':vm_id}])[0]
			vm_ram = getattr(vm_ram_sample, 'resource_metadata')['memory_mb']
			vms_ram.append({'id': vm_id, 'ram': vm_ram})
			
		min_ram = min([vms_ram[x]['ram'] for x in range(0, len(vms_ram))]) #min allocated ram


		"""
		Select vm with minum allocated memory, and maximum cpu utilization
		"""
		interval_cfg = 600 #ten minutes (read value from configuration file)
		start_sec = time.time() - interval_cfg
		start_time = datetime.fromtimestamp(start_sec).strftime('%Y-%m-%dT%H:%M:%S')

		selected_vm_id = '' #selected vm
		max_avg_cpu_util = 0
		for vm_ram in vms_ram:
			if vm_ram['ram'] > min_ram:
				continue
			#get average cpu utilization of vm in the last ten minutes
			vm_cpu_util_sample = ceilo_client.statistics.list(meter_name='cpu_util', q=[{'field':'timestamp','op':'lt','value':start_time}])[0]
			vm_avg_cpu_util = getattr(vm_cpu_util_sample, 'avg')
			if vm_avg_cpu_util > max_avg_cpu_util:
				max_avg_cpu_util = vm_avg_cpu_util
				selected_vm_id = vm_ram['id']

		vm_uuids = list()
        vm_uuids.append(selected_vm_id)
		
		"""
		Send information to global manager
		"""
		r = (requests.put('http://' + config['global_manager_host'] + ':' + config['global_manager_port'], {'username': state['hashed_username'],
				'password': state['hashed_password'], 'time': alarm_time_sec, 'host': hostname, 'reason': 1, 'vm_uuids': ','.join(vm_uuids)}))

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
			'compute_hosts': common.parse_compute_hosts(config['compute_hosts']),
			'host_macs': {}}
