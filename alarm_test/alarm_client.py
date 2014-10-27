"""
Client per simulare allarmi
"""

import requests
import simplejson as json

"""
Host: controller:9710
Accept: */* 
User-Agent: python-requests/2.4.1 CPython/2.7.3 Linux/3.2.0-4-amd64
Connection: keep-alive
Content-Length: 312 
Content-Type: application/json
Accept-Encoding: gzip, deflate
{"current": "alarm", "alarm_id": "b7b68121-81dc-4b25-becd-27db93387e21", "reason": "Transition to alarm due to 1 samples outside threshold, most recent: 19.5
589116865", "reason_data": {"count": 1, "most_recent": 19.558911686528027, "type": "threshold", "disposition": "outside"}, "previous": "insufficient data"}
"""

url = "http://controller:9710/overload?blabla"

data = {"current": "alarm", "alarm_id": "ab612787-ac16-48bb-a5c0-2a5fed073cef", "reason": "Transition to alarm due to 1 samples outside threshold, most recent: 89.5589116865", "reason_data": {"count": 1, "most_recent": 89.558911686528027, "type": "threshold", "disposition": "outside"}, "previous": "insufficient data"}

headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
r = requests.post(url, data=json.dumps(data), headers=headers)
