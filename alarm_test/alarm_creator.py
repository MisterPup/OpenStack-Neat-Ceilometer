"""
Creatore di allarmi per l'alarm manager
"""

from novaclient import client as novaclient
from ceilometerclient import client as ceiloclient
import requests
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
        compute_hosts = [host.host_name for host in hosts if host.service == 'compute'] #list of compute hosts

        resource_ids = ["_".join([host, host]) for host in compute_hosts] #resource_id of compute hosts

        ceilo_client = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                         tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))

        web_hook_overload = 'http://controller:60180/overload'
	web_hook_underload = 'http://controller:60180/underload' 
    
        for count in range(0, len(resource_ids)): #create alarm for compute_hosts
                cur_res_id = resource_ids[count]
                cur_host = compute_hosts[count]

                alarm_cpu_overload = ({'name':'cpu_' + cur_host + '_overload', 'description':cur_host + ' overloaded', 'meter_name':'compute.node.cpu.percent', 
                                'threshold':70.0, 'comparison_operator':'gt', 'statistic':'avg', 'period':600, 'evaluation_periods':1,
                                'alarm_actions':[web_hook_overload], 'repeat_actions': True, 'matching_metadata':{'resource_id': cur_res_id}})

                alarm_cpu_underload = ({'name':'cpu_' + cur_host + '_underload', 'description':cur_host + ' underloaded', 'meter_name':'compute.node.cpu.percent', 
                                'threshold':20.0, 'comparison_operator':'lt', 'statistic':'avg', 'period':600, 'evaluation_periods':1,
                                'alarm_actions':[web_hook_underload], 'repeat_actions': True, 'matching_metadata':{'resource_id': cur_res_id}})


                print alarm_cpu_overload
                print alarm_cpu_underload
                ceilo_client.alarms.create(**alarm_cpu_overload)
                ceilo_client.alarms.create(**alarm_cpu_underload)

start()
#bottle.run(host='controller', port=9710)
