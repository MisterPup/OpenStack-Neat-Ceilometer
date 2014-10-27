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

        """
        resource_ids = list()
        for host in compute_hosts: #we can get them from the configurations file
                res_id = "_".join([host, host]) #actually host_node
                print res_id
                resource_ids.append(res_id) #how to find host id?
        """

        ceilo_client = (ceiloclient.get_client(2, username=keystone['username'], password=keystone['password'],
                         tenant_name=keystone['tenant_name'], auth_url=keystone['auth_url']))

        web_hook = 'http://controller:9710/'
    
        for count in range(0, len(resource_ids)): #create alarm for compute_hosts
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
                #ceilo_client.alarms.create(**alarm_cpu_high)
                #ceilo_client.alarms.create(**alarm_cpu_low)

start()
#bottle.run(host='controller', port=9710)
