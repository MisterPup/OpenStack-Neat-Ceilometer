==========================================
OpenStack-Neat-Ceilometer
==========================================

| This work is an extension to OpenStack Neat. It has been realized in the context of the Master's Thesis:
| *"A unified framework for resources monitoring and virtual machines migration in OpenStack"*.
| We have **integrated** Ceilometer into Neat. Hosts are monitored by checking on samples of a new meter, defined from
| a combination of host cpu utilization and host memory utilization.
| When a threshold is crossed, an alarm triggers and a request is sent to an endpoint. Behind this endpoint there are two
| services which handle the request to bring the alarmed host into a normal state.

| The thesis consists in an extension to OpenStack Neat (this repository), and an extension to Ceilometer
| (https://github.com/MisterPup/Ceilometer-Juno-Extension.git)

The following changes have been added to OpenStack Neat:

* The *Data Collector* have been substited by the *Compute Agent* of Ceilometer in the task of polling samples

* The *Local Manager* have been substituted by the *Alarm Manager*, a new component that receive requests when
  a Ceilometer Alarm goes into alarm state because an host have been found overloaded or underloaded. It selects
  the subset of VMs to migrate from the alarmed host
  
* The *Global Manager* have been integrated with Ceilometer

* A new version of the heuristic *Best Fit Decreasing* for solving the **Bin Packing Problem** have been created by
  taking into account the combined meter to avoid migrations to overloaded hosts
  
* System V scripts have been realized to control Alarm and Global Manager under Debian-based distros
