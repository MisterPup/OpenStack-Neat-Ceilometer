"""
Client per simulare l'arrivo di allarmi.
Impostare l'id dell'allarme di overload
"""

import requests
import simplejson as json

host = 'controller'
port = '60180'
request_type = 'overload'

url = "http://" + host + ":" + port + "/" + request_type + "?blabla"

alarm_id = "55501bd2-406c-492c-9e78-2212e78db89b"

data = {"current": "alarm", "alarm_id": alarm_id, "reason": "Transition to alarm due to 1 samples outside threshold, most recent: 89.5589116865", "reason_data": {"count": 1, "most_recent": 89.558911686528027, "type": "threshold", "disposition": "outside"}, "previous": "insufficient data"}

headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
r = requests.post(url, data=json.dumps(data), headers=headers)
