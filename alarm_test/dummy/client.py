"""
Client di test
"""

import requests
import simplejson as json

url = "http://controller:9710/overload?blabla"

data = {"current": "alarm", "alarm_id": "b7b68121-81dc-4b25-becd-27db93387e21", "reason": "Transition to alarm due to 1 samples outside threshold, most recent: 19.5589116865", "reason_data": {"count": 1, "most_recent": 19.558911686528027, "type": "threshold", "disposition": "outside"}, "previous": "insufficient data"}

headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
r = requests.post(url, data=json.dumps(data), headers=headers)
