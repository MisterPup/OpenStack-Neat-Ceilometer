"""
Logger di varie info per ogni host

"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient

import os
from os import environ as env
import time

def start(hosts, sleep_sec, base_dir):
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

    while True:
        for host in hosts:
            host_id = '_'.join([host, host]) #host_node: computeX_computeX
            log_info(nova, ceilo, host, host_id, root_path)
        time.sleep(sleep_sec)

def log_info(nova, ceilo, host, host_id, root_path):
    # log info every interval
    path = os.path.join(root_path, host)

    if not os.path.exists(path):
        os.makedirs(path)

    print path

    log_meter_host_cpu_util(ceilo, host_id, path)
    log_meter_host_mem_util(ceilo, host_id, path)
    log_meter_host_cpu_mem(ceilo, host_id, path)
    #log_alarm_host_cpu_mem(ceilo, host_id, path)
    #log_vms_host(nova, host, path)

def log_meter_host_cpu_util(ceilo, host_id, path):
    # sample of cpu util in percentage
    host_cpu_util = ceilo.samples.list(meter_name='host.cpu.util',
                                        limit=1, 
                                        q=[{'field':'resource_id',
                                            'op':'eq',
                                            'value':host_id}])
    host_cpu_util = (host_cpu_util[0].counter_volume)/100
    content = ", ".join([get_cur_formatted_time(), str(host_cpu_util)])

    path_file = os.path.join(path, "meter_host_cpu_util")
    write_file(path_file, content)

def log_meter_host_mem_util(ceilo, host_id, path):
    # sample of ram usage in percentage
    host_mem_usage = ceilo.samples.list(meter_name='host.memory.usage',
                                        limit=1, 
                                        q=[{'field':'resource_id',
                                            'op':'eq',
                                            'value':host_id}])
    host_mem_usage = (host_mem_usage[0].counter_volume)/100
    content = ", ".join([get_cur_formatted_time(), str(host_mem_usage)])

    path_file = os.path.join(path, "meter_host_mem_util")
    write_file(path_file, content) 

def log_meter_host_cpu_mem(ceilo, host_id, path):
    # sample of cpu-ram combined meter
    host_cpu_mem_combo = ceilo.samples.list(meter_name='host.cpu.util.memory.usage',
                                            limit=1, 
                                            q=[{'field':'resource_id',
                                                'op':'eq',
                                                'value':host_id}])    
    content = ", ".join([get_cur_formatted_time(), str(host_cpu_mem_combo[0].counter_volume)])
 
    path_file = os.path.join(path, "meter_host_cpu_mem")
    write_file(path_file, content) 

def log_alarm_host_cpu_mem(ceilo, host_id, path):
    # overload and underload alarms
    alarms = ceilo.alarms.list(q=[{'field':'meter',
                                   'op':'eq',
                                   'value':"meter_host_cpu_mem"}])

    for alarm in alarms:
        name = alarm.__getattr__(name)
        if "overload" in name:
            content = ", ".join([get_cur_formatted_time(), str(alarm)])
            path_file = os.path.join(path, "alarm_overload_host_cpu_mem")
            write_file(path_file, content)
        elif "underload" in name:
            content = ", ".join([get_cur_formatted_time(), str(alarm)])
            path_file = os.path.join(path, "alarm_underload_host_cpu_mem")
            write_file(path_file, content)

def log_vms_host(nova, host, path):
    # vms in host
    search_opts = {'host': host, 'all_tenants': True}
    vms = nova.servers.list(search_opts=search_opts)

    ids = [vm.id for vm in vms]
    content = ", ".join([get_cur_formatted_time(), str(ids)])
    path_file = os.path.join(path, "vms")
    write_file(path_file, ids)

def write_file(path_file, content):
    out_file = open(path_file,"a")
    out_file.write(str(content) + os.linesep)
    out_file.close()   

def get_cur_formatted_time():
    cur_time = time.time()
    formatted_time = time.strftime('%Y-%m-%dT%H:%M:%S', 
                                   time.localtime(cur_time))
    return formatted_time

#compute_hosts = ['compute02', 'compute03', 'compute04']
compute_hosts = ['compute02']
sleep_sec = 60
base_dir = "log"
start(compute_hosts, sleep_sec, base_dir)
