# Telegraf + Kapacitor + Kubernetes Autoscaling
This repository provides an example of how you can use [Kapacitor](https://www.influxdata.com/time-series-platform/kapacitor/) and 
[Telegraf](https://github.com/influxdata/telegraf) to autoscale resources in Kubernetes, using custom metrics, while still implementing Prometheus-style metric endpoints. 
This is due to the limitation with the existing [Horizontal Pod Autscaler](https://kubernetes.io/docs/user-guide/horizontal-pod-autoscaling/) that only supports scaling on CPU and memory metrics.

Telegraf is used to scrape the Prometheus-style metrics endpoints and relays them to Kapacitor, which implements the autoscaling functionality.

This repository is based heavily on [influxdata/k8s-kapacitor-autoscale](https://github.com/influxdata/k8s-kapacitor-autoscale).

## Setup
This example assumes you have a running Kubernetes cluster. Check out these instructions outlining how to setup a multi-machine [Kubernetes cluster on Vagrant](https://coreos.com/kubernetes/docs/latest/kubernetes-on-vagrant.html).

### Get the repo

Download this repo and use it as a working directory:

    $ git clone https://github.com/JanekLehr/k8s-telegraf-kapacitor-autoscale.git
    $ cd k8s-telegraf-kapacitor-autoscale
    
## The Example Application

Our example application can be found in the `app` directory of this repo.

It does two things:

1. Serves up an HTTP Prometheus style metrics endpoint on port 8000 that returns the current total number of requests the app instance has received
2. Serves up an HTTP endpoint on port 8080 that just returns "ok"

## Configure the Telegraf metrics agent

We deploy Telegraf to collect the application metrics from the Prometheus endpoint and send them along to Kapacitor.

Create a ConfigMap to store the Telegraf configuration 

	$ kubectl create -f configmaps/telegraf-configmap.yaml
	
Later we will deploy the Telegraf container in the same Pod as our application so that we automatically start sending metrics to Kapacitor when a new application 
Pod is created. This is why we've configured the Prometheus input plugin to scrape metrics from localhost.

### Make the application image available

The app image in the [app deployment](deployments/app.yaml#L14) configuration is set to `janeklehr/alert-app:latest`. 
You will want to build the application image and host it in a repository accessible by your Kubernetes cluster. 
Another option is to ssh into each host and build the image locally. I chose to use my [DockerHub](https://hub.docker.com/) account to host the image publicly. Example:

	$ cd app
	$ docker build -t janeklehr/alert-app .
	$ docker login
	$ docker push janeklehr/alert-app

### Start the Application with Telegraf

This repo provides a deployment definition for the app that deploys an app container and Telegraf container per Pod, and exposes the application as a Service.
From the repository root run.

    $ kubectl create -f deployments/app.yaml

### Test the Application

Wait until the status for your app Pod is 'Running'

	$ kubectl get pods
	NAME                   READY     STATUS    RESTARTS   AGE
	app-3850222329-gmxln   2/2       Running   0          6m
	
Get the node IP address of a pod

	$ kubectl describe pods/app-3850222329-gmxln
	Name:		app-3850222329-gmxln
	Namespace:	default
	Node:		172.17.4.201/172.17.4.201   ##  <----- this is your node IP
	Start Time:	Tue, 17 Jan 2017 15:12:59 -0600
	Labels:		app=app
				pod-template-hash=3850222329
	.
	.
	.
				
In the deployment configuration we've set the node ports to use (30100 and 30200). You can see the port by listing the services

	$ kubectl get services
	NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)                         AGE
	app          10.3.0.213   <nodes>       8080:30100/TCP,8000:30200/TCP   1m
	kubernetes   10.3.0.1     <none>        443/TCP                         15m
	
Save the app routes to environment variables
	
	$ export APP_URL=http://172.17.4.201:30100
	$ export APP_METRICS_URL=http://172.17.4.201:30200

Test that the app is working:

    $ curl $APP_URL
	ok
	$ curl $APP_METRICS_URL
	# HELP requests Total number of requests served
	# TYPE requests counter
	# HELP process_virtual_memory_bytes Virtual memory size in bytes.
	# TYPE process_virtual_memory_bytes gauge
	process_virtual_memory_bytes 181784576.0
	# HELP process_resident_memory_bytes Resident memory size in bytes.
	# TYPE process_resident_memory_bytes gauge
	process_resident_memory_bytes 19427328.0
	# HELP process_start_time_seconds Start time of the process since unix epoch in seconds.
	# TYPE process_start_time_seconds gauge
	process_start_time_seconds 1484687749.21
	# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.
	# TYPE process_cpu_seconds_total counter
	process_cpu_seconds_total 0.3
	# HELP process_open_fds Number of open file descriptors.
	# TYPE process_open_fds gauge
	process_open_fds 8.0
    
    
## Start Kapacitor

Now that the app is up and Telegraf is scraping metrics, let's start up Kapacitor.

    $ kubectl create -f deployments/kapacitor.yaml

### Test that Kapacitor is working

Get the Kapacitor URL and port like we did for the application. Kapacitor exposes port 9092 mapped to node port 30300.

	$ kubectl get services
	NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)                         AGE
	app          10.3.0.86    <nodes>       8080:30100/TCP,8000:30200/TCP   21m
	kapacitor    10.3.0.88    <nodes>       9092:30300/TCP                  10s
	kubernetes   10.3.0.1     <none>        443/TCP                         27m

>NOTE: This time we export the URL so that the kapacitor client can also know how to connect.

    $ export KAPACITOR_URL=http://172.17.4.201:30300

At this point you either need to have the `kapacitor` client installed locally or via docker to run the client.
The client can be downloaded from [here](https://www.influxdata.com/downloads/#kapacitor).

First check that we can talk to Kapacitor:

    $ kapacitor stats general

You should see output like the following:

    ClusterID:                    7b4d5ca3-8074-403f-99b9-e1743c3dbbff
    ServerID:                     94d0f5ea-5a57-4573-a279-e69a81fc5b5c
    Host:                         kapacitor-3uuir
    Tasks:                        0
    Enabled Tasks:                0
    Subscriptions:                0
    Version:                      1.1.0


### Using Kapacitor to autoscale our application

Kapacitor uses `tasks` to do work, the next steps involve defining and enabling a new task that will autoscale our app.
A task is defined via a [TICKscript](https://docs.influxdata.com/kapacitor/v1.1/tick/). This repository has the TICKscript we need: [`autoscale.tick`](autoscale.tick).

Define and enable the autoscale task in Kapacitor:

    $ kapacitor define autoscale -tick autoscale.tick -type stream -dbrp autoscale.autogen
    $ kapacitor enable autoscale

To make sure the task is running correctly use the `kapacitor show` command:

    $ kapacitor show autoscale

There will be lots of output about the content and status of the task but the second to last line should look something like this:

    k8s_autoscale6 [avg_exec_time_ns="0s" cooldown_drops="0" decrease_events="0" errors="0" increase_events="0" ];

Since the task has just started the k8s_autoscale6 node has not processed any points yet but it will after a minute.

At this point take a minute to [read the task](autoscale.tick) and get a feel for what it is doing.
The high level steps are:

* Select the `requests` data that each application host is sending.
* Compute the requests per second per host
* For each replicaset (in our case it's just the one `app` replicaset), compute the total requests per second across all hosts.
* Compute a moving average of the total requests per second over the last 60 points (`1m`).
* Compute the desired number of hosts for the deployment based on the target value. At this step Kapacitor will call out to the Kubernetes API and change the desired replicas to match the computed result.

There are some more details about cooldowns and other things, feel free to ignore those for now.

## Generate some load and watch the application autoscale

At this point our k8s cluster should have only two pods running, the one app pod and the one kapacitor pod.
Check this by list the pods:

    $ kubectl get pods

Once the request count increases on the app pod Kapacitor will instruct k8s to create more pods for that replicaset.
At that point you should see multiple app pods while still only seeing one Kapacitor pod.

There are several ways to generate HTTP requests, use a tool you are comfortable with.
If you do not already have a favorite HTTP load generation tool we recommend [hey](https://github.com/rakyll/hey).
We also provide a simple script [`ramp.sh`](https://github.com/influxdata/k8s-kapacitor-autoscale/blob/master/ramp.sh) that uses `hey` to slowly ramp traffic up and then back down.

Install `hey` before running `ramp.sh`:

    $ go get -u github.com/rakyll/hey
    $ ./ramp.sh $APP_URL

### Watch autoscaling in progress

While the traffic is ramping up watch the current list of pods to see that more pods are added as traffic increases.
The default target is 100 requests per second per host.
The `ramp.sh` script will print out the current QPS it is generating. Divide that number by 100 and round up.
That should be the number of app pods running.

    $ kubectl get pods -w
    
### Prometheus

Deploy Prometheus on the cluster using these [instructions](https://coreos.com/blog/prometheus-and-kubernetes-up-and-running.html). The yaml files in those instructions have been included in this repo:

- [prometheus-configmap-1.yaml](configmaps/prometheus-configmap-1.yaml)
- [prometheus-configmap-2.yaml](configmaps/prometheus-configmap-2.yaml)
- [prometheus-deployment.yaml](deployments/prometheus-deployment.yaml)
- [node-exporter.yaml](daemonsets/node-exporter.yaml)

After you've applied the prometheus-config-map-2.yaml you should see that the app in the [Prometheus targets](http://172.17.4.201:30900/targets) 

The node exporters are also sending metrics to Kapacitor using the same mechanism as the app service. You can now choose to define autoscaling rules based on the metrics the node exporters make available.
    
    
### Notes and TODOs

- The reason we deploy Telegraf within each Pod is because, unlike Prometheus, the Prometheus input plugin doesn't interface 
with Kubernetes service discovery to dynamically discover each instance of the service to scrape. However, there is an 
[issue](https://github.com/influxdata/telegraf/issues/272) requesting this as a new feature.

- The agent "interval" in the Telegraf config is very important when defining the "moving_avg_count", and derivative unit in the 
TICK script. In this example we want our moving window to be one minute long, which is why we set "moving_avg_count=60" since Telegraf 
is sending us a metric every second. It's very important that the derivative unit matches up with the Telegraf interval so that we can an 
accurate computation of requests/s. An alternate TICK script that accomplishes the same thing can be found in the 
[k8s_autoscale_node doc](https://docs.influxdata.com/kapacitor/v1.1/nodes/k8s_autoscale_node/)

- **TODO:** I found that when the node exporter is deployed with `hostNetwork: true` then Telgraf is unable to discover the Kapacitor endpoint using 
Kubernetes' service discovery. Commenting this piece out fixed this problem only for the pods deployed on the non-k8-master node. I'm not 
sure yet if this is due to this particular Kubernetes cluster configuration or if it's a general limitation.

- **TODO:** I found that the total requests per second calculation isn't what you would expect after another Pod is added. My theory is that it has 
something to do with the way the Telegraf config and Kapacitor TICK stack work together. It needs more investigation. Something to try when debugging 
this issue is having the app send directly to Kapacitor, like the [original Influx version](https://github.com/influxdata/k8s-kapacitor-autoscale) of this repo does, and see if this weird behavior continues.