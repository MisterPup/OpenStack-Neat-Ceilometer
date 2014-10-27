"""
Il vero alarm manager
"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient

from contracts import contract
import time
from datetime import datetime
from hashlib import sha1

import bottle
import requests

@bottle.post('/overload')
def service_overload():
	request = bottle.request
	json = request.json

        keystone = {}
        keystone['username']="admin" #env['OS_USERNAME']
        keystone['password']="torvergata" #env['OS_PASSWORD']
        keystone['auth_url']="http://controller:35357/v2.0" #env['OS_AUTH_URL']
        keystone['tenant_name']="admin" #env['OS_TENANT_NAME']

	if not json is None:

		nova_client = (novaclient.Client(3, keystone['username'], keystone['password'], keystone['tenant_name'], 
                        keystone['auth_url'], service_type='compute'))
		ceilo_client = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                         tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))

		#try except
		"""
		Recover alarm info
		"""
		alarm_id = json.get('alarm_id')
		alarm = ceilo_client.alarms.get(alarm_id) #recover alarm info
		print alarm.__getattr__('threshold_rule')
		resource_id = alarm.__getattr__('threshold_rule')['query'][0]['value'] #compute1_compute1
		hostname = resource_id.split('_')[0] #get host from resource_id: compute1_compute1 -> compute1
		alarm_timestamp = alarm.__getattr__('timestamp') #get timestamp
		alarm_time_obj = datetime.strptime(alarm_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
		alarm_time_sec = alarm_time_obj.strftime('%s') #convert timestamp to seconds from epoch

		print "hostname %s" % hostname
		print "alarm_timestamp %s" % alarm_timestamp

		#log
		"""
		Recover list of vms in "alarmed" host
		"""
		all_vms = nova_client.servers.list()
		host_vms = [vm for vm in all_vms if getattr(vm, 'OS-EXT-SRV-ATTR:host') == hostname] #list of vms in "alarmed" host

		print host_vms

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
			print vm_ram
			
		min_ram = min([vms_ram[x]['ram'] for x in range(0, len(vms_ram))]) #min allocated ram

		print  min_ram

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
			print vm_avg_cpu_util
			if vm_avg_cpu_util > max_avg_cpu_util:
				max_avg_cpu_util = vm_avg_cpu_util
				selected_vm_id = vm_ram['id']

		vm_uuids = list()
        	vm_uuids.append(selected_vm_id)
		print selected_vm_id
		
		"""
		Send information to global manager
		"""
	
		hash_username = sha1('admin').hexdigest()
		hash_password = sha1('torvergata').hexdigest()
		#r = (requests.put('http://controller:9810/global', {'username': hash_username,
		#		'password': hash_password, 'time': alarm_time_sec, 'host': hostname, 'reason': 1, 'vm_uuids': ','.join(vm_uuids)}))

		print "put completed"

bottle.run(host='controller', port=9710)
