"""
Verifica ogni intervallo che tutte le istanze abbiano il giusto metadato
relativo all'host in cui si trovano
"""

import time

from novaclient.v1_1 import client

from neat.config import *
import neat.common as common

def start():

    config = read_and_validate_config([DEFAILT_CONFIG_PATH, CONFIG_PATH],
                                      REQUIRED_FIELDS)

    common.init_logging(
        config['log_directory'],
        'metadata-manager.log',
        int(config['log_level']))

    nova = client.Client(config['os_admin_user'],
                         config['os_admin_password'],
                         config['os_admin_tenant_name'],
                         config['os_auth_url'],
                         service_type="compute")

    compute_hosts = common.parse_compute_hosts(config['compute_hosts'])

    interval = config['metadata_check_interval'] or 100 

    while True:        
        refresh_metadata(compute_hosts)
        time.sleep(interval)

def refresh_metadata(nova, compute_hosts):
	  #dict (host, [vm_id])
    server_hosts = common.servers_by_hosts(nova, compute_hosts)

    for host, vms in server_hosts:
    	metadata = {'metering.compute':host}
        for vm in vms:           
        	nova.servers.set_meta(vm, metadata) 
