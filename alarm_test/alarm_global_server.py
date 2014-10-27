"""
Simula il server del global manager
"""

from bottle import put, route, request, run 

@put('/global')
def put():
        print request.url
        headers = request.headers
        write_packet(headers)

def write_packet(headers):
        myfile = open("log/global_log.txt", "a")

        headers_key = headers.keys()
        for key in headers_key:
                myfile.write(key + ": " + headers.get(key) + "\n")

        postdata = request.body.read()
        myfile.write(postdata + "\n")

        myfile.write("\n")

run(host='controller', port=9810)
