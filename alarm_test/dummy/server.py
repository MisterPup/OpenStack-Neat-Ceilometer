"""
Server di test
"""

from bottle import get, post, route, request, run


@post('/underload')
def post_underload():
	post()

@post('/overload')
def post_overload():
	post()

def post():
	print request.url
	headers = request.headers
	write_packet(headers)

def write_packet(headers):
	myfile = open("log.txt", "a")

	headers_key = headers.keys()
	for key in headers_key:
		myfile.write(key + ": " + headers.get(key) + "\n")

	postdata = request.body.read()
	myfile.write(postdata + "\n")

	myfile.write("\n")

run(host='controller', port=9710)

