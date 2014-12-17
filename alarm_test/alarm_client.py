"""
Client per simulare l'arrivo di allarmi.
Impostare l'id dell'allarme di overload
"""

import requests
import simplejson as json

host = 'controller'
port = '60180'
request_type = 'underload'

url = "http://" + host + ":" + port + "/" + request_type + "?blabla"

alarm_id = "b41fa40f-1ac2-4cb6-9c9e-1acce7ae85aa"

data = {"current": "alarm", "alarm_id": alarm_id, "reason": "Transition to alarm due to 1 samples outside threshold, most recent: 89.5589116865", "reason_data": {"count": 1, "most_recent": 89.558911686528027, "type": "threshold", "disposition": "outside"}, "previous": "insufficient data"}

headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
r = requests.post(url, data=json.dumps(data), headers=headers)
