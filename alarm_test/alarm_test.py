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
from contracts import contract
from os import environ as env

@contract
def get_hosts_cpu_frequency(ceilo, hosts):
    """Get cpu frequency of hosts.

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

    host_ram_total = dict() #dict of (host, total_ram)
    for host in hosts:
        data = nova.hosts.get(host)
        host_ram_total[host] = data[0].memory_mb

    return host_ram_total

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

def get_vms_last_n_cpu_util(nova, ceilo, hosts, last_n_cpu):
    """Get CPU usage of vms.
  
    :param nova: A Nova client
     :type nova: *

    :param ceilo: A Ceilo client.
     :type ceilo: *

    :param hosts: A set of hosts
     :type hosts: list(str)

    :param last_n_cpu: Number of last cpu values to average
     :type last_n_cpu: int

    :return: A dictionary of (vm, cpu_usage)
     :rtype: dict(str: *)
    """

    vms_last_cpu_util = dict() #dict of (vm, ram_usage)
    #dict(host: [vms])
    vms_hosts = vms_by_hosts(nova, hosts) 
    for vms in vms_hosts.values():
        for vm in vms:
            cpu_util_list = (
                ceilo.samples.list(meter_name='cpu_util', 
                                   limit=last_n_cpu, 
                                   q=[{'field':'resource_id',
                                       'op':'eq',
                                       'value':vm}]))
            #we have collected least last_n_cpu samples
            if len(cpu_util_list) == last_n_cpu:
                vms_last_cpu_util[vm] = (
                    sum([sample.counter_volume for sample in cpu_util_list])/last_n_cpu)

    return vms_last_cpu_util

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
    for vm in nova.servers.list():
        result[vm_hostname(vm)].append(str(vm.id))
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
def get_hosts_ram_usage_ceilo(ceilo, hosts_ram_total):
    """Get ram usage for each host from ceilometer

    :param ceilo: A Ceilometer client.
     :type ceilo: *

    :param hosts_ram_total: A dictionary of (host, total_ram)
     :type hosts_ram_total: dict(str: *)

    :return: A dictionary of (host, ram_usage)
     :rtype: dict(str: *)
    """
    hosts_ram_usage = dict() #dict of (host, ram_usage)
    for host in hosts_ram_total:        
        #actually hostname_nodename
        host_res_id = "_".join([host, host])
        #sample of ram usage in percentage
        host_mem_usage = ceilo.samples.list(meter_name='host.memory.usage',
                                            limit=1, 
                                            q=[{'field':'resource_id',
                                                'op':'eq',
                                                'value':host_res_id}])

        if host_mem_usage:
            host_mem_usage = host_mem_usage[0].counter_volume
            host_mem_total = hosts_ram_total[host]
            hosts_ram_usage[host] = (int)((host_mem_usage/100)*host_mem_total)

    return hosts_ram_usage

def create_alarm(resource_ids, must_print=False, must_create=False):
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

    if must_print:
        print alarm_cpu_high
        print alarm_cpu_low
    if must_create:
        ceilo_client.alarms.create(**alarm_cpu_high)
        ceilo_client.alarms.create(**alarm_cpu_low)

def start():

    keystone = {}
    keystone['username'] = env['OS_USERNAME']
    keystone['password'] = env['OS_PASSWORD']
    keystone['auth_url'] = env['OS_AUTH_URL']
    keystone['tenant_name'] = env['OS_TENANT_NAME']

#key_client = (keyclient.Client(username=keystone['username'], password=keystone['password'], 
    #               tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
    #auth = (v2.Password(username=keystone['username'], password=keystone['password'],
    #               tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
    #sess = session.Session(auth=auth)
    #nova_client = novaclient.Client(2, session=sess)       
    
    nova_client = (novaclient.Client(3, keystone['username'], keystone['password'], keystone['tenant_name'], 
                   keystone['auth_url'], service_type='compute'))
	
	ceilo_client = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                    tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))
	
	last_n_cpu = 2

	hosts = nova_client.hosts.list()
	compute_hosts = [host.host_name for host in hosts if host.service == 'compute']
	print "compute_hosts: %s\n" % str(compute_hosts)

	compute_hosts = [s.encode('ascii','ignore') for s in compute_hosts]
	print "compute_hosts: %s\n" % str(compute_hosts)

	hosts_cpu_total = get_hosts_cpu_frequency(ceilo_client, compute_hosts)
	print "hosts_cpu_total: %s\n" % hosts_cpu_total

	hosts_cpu_usage = get_hosts_last_cpu_usage(ceilo_client, compute_hosts) 
	print "hosts_cpu_usage: %s\n" % hosts_cpu_usage

	hosts_ram_total = get_hosts_ram_total(nova_client, compute_hosts)
	print "hosts_ram_total: %s\n" % hosts_ram_total

	hosts_ram_usage = get_hosts_ram_usage(nova_client, compute_hosts)
	print "hosts_ram_usage: %s\n" % hosts_ram_usage

        hosts_ram_usage_ceilo = get_hosts_ram_usage_ceilo(ceilo_client, hosts_ram_total)
        print "hosts_ram_usage: %s\n" % hosts_ram_usage_ceilo

	vms_hosts = vms_by_hosts(nova_client, compute_hosts)
	print "vms_hosts: %s\n" % vms_hosts

	vms_last_cpu_util = get_vms_last_n_cpu_util(nova_client, ceilo_client, compute_hosts, last_n_cpu)
	print "vms_last_cpu_util: %s\n" % vms_last_cpu_util

	"""	
	resource_ids = ["_".join([host, host]) for host in compute_hosts]
	print "RESOURCE_IDS: %s" % str(resource_ids)

	all_vms = nova_client.servers.list()
	hostname = 'compute1'
	host_vms = [vm for vm in all_vms if getattr(vm, 'OS-EXT-SRV-ATTR:host') == hostname]

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
	
start()
