"""
Test vari sugli allarmi
"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient
import requests
import time
from datetime import datetime
#from keystoneclient.auth.identity import v2
#from keystoneclient import session
import bottle

def start():

        keystone = {}
        keystone['username']="admin" #env['OS_USERNAME']
        keystone['password']="torvergata" #env['OS_PASSWORD']
        keystone['auth_url']="http://controller:35357/v2.0" #env['OS_AUTH_URL']
        keystone['tenant_name']="admin" #env['OS_TENANT_NAME']

        #key_client = (keyclient.Client(username=keystone['username'], password=keystone['password'], 
        #               tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
        #auth = (v2.Password(username=keystone['username'], password=keystone['password'],
        #               tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
        #sess = session.Session(auth=auth)
        #nova_client = novaclient.Client(2, session=sess)       
    
        nova_client = (novaclient.Client(3, keystone['username'], keystone['password'], keystone['tenant_name'], 
                        keystone['auth_url'], service_type='compute'))

	hosts = nova_client.hosts.list()
	compute_hosts = [host.host_name for host in hosts if host.service == 'compute']
	print compute_hosts

	resource_ids = ["_".join([host, host]) for host in compute_hosts]
	print resource_ids

	all_vms = nova_client.servers.list()
	hostname = 'compute1'
	host_vms = [vm for vm in all_vms if getattr(vm, 'OS-EXT-SRV-ATTR:host') == hostname]
	print host_vms

        ceilo_client = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                         tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
	
	"""
	vms_ram = list()
	for vm in host_vms:
		vm_id = vm.id #resource_id
		print vm_id
		#why does it return two samples? We take only the first one
		vm_ram_sample = ceilo_client.samples.list(meter_name='memory', q=[{'field':'resource_id','op':'eq','value':vm_id}])[0]
		vm_ram = getattr(vm_ram_sample, 'resource_metadata')['memory_mb']
		vms_ram.append({'id': vm_id, 'ram': vm_ram})
	
	min_ram = min([vms_ram[x]['ram'] for x in range(0, len(vms_ram))])

	interval_cfg = 600 #ten minutes (read value from configuration file)
	now = time.time()
	start_sec = now - interval_cfg
	start_time = datetime.fromtimestamp(start_sec).strftime('%Y-%m-%dT%H:%M:%S')

	#print datetime.datetime.fromtimestamp(now).strftime('%Y-%m-%dT%H:%M:%S')
	#print start_time

	str_time = '2014-10-20T15:11:29.759000'
	obj_time = datetime.strptime(str_time, '%Y-%m-%dT%H:%M:%S.%f')
	print str_time
	print obj_time
	print obj_time.strftime('%s')

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
	print selected_vm_id
	"""
	
        web_hook = 'http://controller:9710/'
    
        for count in range(0, len(resource_ids)):
                cur_res_id = resource_ids[count]
                cur_host = compute_hosts[count]

                alarm_cpu_high = ({'name':'cpu_' + cur_host + '_high', 'description':cur_host + ' running hot', 'meter_name':'compute.node.cpu.percent', 
                                'threshold':70.0, 'comparison-operator':'gt', 'statistic':'avg', 'period':600, 'evaluation-periods':1,
                                'alarm_action':web_hook, 'query':{'resource_id': cur_res_id}})

                alarm_cpu_low = ({'name':'cpu_' + cur_host + '_down', 'description':cur_host + ' running cold', 'meter_name':'compute.node.cpu.percent', 
                                'threshold':20.0, 'comparison-operator':'lt', 'statistic':'avg', 'period':600, 'evaluation-periods':1,
                                'alarm_action':web_hook, 'query':{'resource_id': cur_res_id}})


                print  alarm_cpu_high
                print alarm_cpu_low    
                ceilo_client.alarms.create(**alarm_cpu_high)
                ceilo_client.alarms.create(**alarm_cpu_low)
start()
