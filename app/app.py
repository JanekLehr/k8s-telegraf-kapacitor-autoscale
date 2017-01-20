from socket import gethostname
from os import environ
from flask import Flask
from prometheus_client import start_http_server, Counter

app = Flask(__name__)

request_counter = Counter('requests',
                          'Total number of requests served',
                          ['host', 'deployment'])
hostname = gethostname()
deployment = environ.get('APP_DEPLOYMENT', 'app')


@app.route('/')
def index():
    request_counter.labels(host=hostname, deployment=deployment).inc()
    return 'ok'

if __name__ == '__main__':
    start_http_server(port=8000, addr='0.0.0.0')
    app.run(port=8080, host='0.0.0.0')
