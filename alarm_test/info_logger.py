"""
Logger di varie info per ogni host

"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient

import os
from os import environ as env
import time

def start(hosts, sleep_sec, base_dir):
    print 'You must be admin to use this script'
    # start logger
    time_dir = get_cur_formatted_time()
    root_path = os.path.join(base_dir, time_dir)

    keystone = {}
    keystone['username'] = env['OS_USERNAME']
    keystone['password'] = env['OS_PASSWORD']
    keystone['auth_url'] = env['OS_AUTH_URL']
    keystone['tenant_name'] = env['OS_TENANT_NAME']      
    
    nova = (novaclient.Client(3, keystone['username'], keystone['password'], keystone['tenant_name'], 
                  keystone['auth_url'], service_type='compute'))
    
    ceilo = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                  tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))    

    flavor_list = nova.flavors.list()
    flavor_dict = dict((flavor.id, flavor.name) for flavor in flavor_list)

    while True:
        for host in hosts:
            host_id = '_'.join([host, host]) #host_node: computeX_computeX
            log_info(nova, ceilo, host, host_id, root_path, flavor_dict)
        time.sleep(sleep_sec)

def log_info(nova, ceilo, host, host_id, root_path, flavor_dict):
    # log info every interval
    path = os.path.join(root_path, host)

    if not os.path.exists(path):
        os.makedirs(path)

    print path

    log_meter_host_cpu_util(ceilo, host_id, path)
    log_meter_host_mem_util(ceilo, host_id, path)
    log_meter_host_cpu_mem(ceilo, host_id, path)
    log_vms_host(nova, host, path, flavor_dict)
    log_alarm_host_cpu_mem(ceilo, host_id, path)

def log_meter_host_cpu_util(ceilo, host_id, path):
    # sample of cpu util in percentage
    host_cpu_util = ceilo.samples.list(meter_name='host.cpu.util',
                                        limit=1, 
                                        q=[{'field':'resource_id',
                                            'op':'eq',
                                            'value':host_id}])
    host_cpu_util = (host_cpu_util[0].counter_volume)/100
    content = get_string_to_write(str(host_cpu_util))

    path_file = get_path_to_file(path, "meter_host_cpu_util")
    write_file(path_file, content)

def log_meter_host_mem_util(ceilo, host_id, path):
    # sample of ram usage in percentage
    host_mem_usage = ceilo.samples.list(meter_name='host.memory.usage',
                                        limit=1, 
                                        q=[{'field':'resource_id',
                                            'op':'eq',
                                            'value':host_id}])
    host_mem_usage = (host_mem_usage[0].counter_volume)/100
    content = get_string_to_write(str(host_mem_usage))

    path_file = get_path_to_file(path, "meter_host_mem_util")
    write_file(path_file, content) 

def log_meter_host_cpu_mem(ceilo, host_id, path):
    # sample of cpu-ram combined meter
    host_cpu_mem_combo = ceilo.samples.list(meter_name='host.cpu.util.memory.usage',
                                            limit=1, 
                                            q=[{'field':'resource_id',
                                                'op':'eq',
                                                'value':host_id}])    
    content = get_string_to_write(str(host_cpu_mem_combo[0].counter_volume))
 
    path_file = get_path_to_file(path, "meter_host_cpu_mem")
    write_file(path_file, content) 

def log_alarm_host_cpu_mem(ceilo, host_id, path):
    # overload and underload alarms
    alarms = ceilo.alarms.list(q=[{'field':'meter',
                                   'op':'eq',
                                   'value':'host.cpu.util.memory.usage'}])
    hostname = [x.strip() for x in host_id.split('_')][0]

    for alarm in alarms:
        name = alarm.name
        state = alarm.state
        #print hostname
        #print name
        if hostname in name:
            name_state = ''
            if state == 'ok':
                name_state = name + ':  ' + '0'
            elif state == 'alarm':
                name_state = name + ':  ' + '1'
            else:
               name_state = name + ':  ' + '2'
    
            content = get_string_to_write(name_state)
            if 'overload' in name:
                path_file = get_path_to_file(path, "alarm_host_cpu_mem_overload")
                write_file(path_file, content)
            if 'underload' in name:
                path_file = get_path_to_file(path, "alarm_host_cpu_mem_underload")
                write_file(path_file, content)

            path_file = get_path_to_file(path, "alarm_host_cpu_mem")
            write_file(path_file, content)
    content = get_string_to_write("**********")
    path_file = get_path_to_file(path, "alarm_host_cpu_mem")
    write_file(path_file, content)

def log_vms_host(nova, host, path, flavor_dict):
    # vms in host
    search_opts = {'host': host, 'all_tenants': True}
    vms = nova.servers.list(search_opts=search_opts)
    path_file = get_path_to_file(path, "vms")

    id_flavor = [(vm.id, flavor_dict[vm.flavor['id']]) for vm in vms]
    num_vms = len(vms)
    content = get_string_to_write(str(num_vms) + ' , ' + str(id_flavor))
    write_file(path_file, content)

def write_file(path_file, content):
    out_file = open(path_file,"a")
    out_file.write(str(content) + os.linesep)
    out_file.close()

def get_path_to_file(path, filename):
    return os.path.join(path, filename)

def get_string_to_write(content):
    return ", ".join([get_cur_formatted_time(), content]) 

def get_cur_formatted_time():
    cur_time = time.time()
    formatted_time = time.strftime('%Y-%m-%dT%H:%M:%S', 
                                   time.localtime(cur_time))
    return formatted_time

compute_hosts = ['compute02', 'compute03', 'compute04']
sleep_sec = 150
base_dir = "log"
start(compute_hosts, sleep_sec, base_dir)
