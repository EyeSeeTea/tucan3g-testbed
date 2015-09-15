#!/bin/sh
### BEGIN INIT INFO
# Provides:          TUCAN_ntp
# Required-Start:    $local_fs $remote_fs $network $syslog $nocatsplash $time
# Required-Stop:     TUCAN_owamp TUCAN_bwctl TUCAN_bwctl_tests tucand
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# X-Interactive:     false
# Short-Description: TUCAN3G testbed ntp iptables rules
# Description: TUCAN3G testbed ntp iptables rules
### END INIT INFO

#
# Copyright (c) 2015.
#
# This file is part of WP5 TUCAN3G Testbed
#
#  WP5 TUCAN3G Testbed software is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  WP5 TUCAN3G Testbed software is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Foobar.  If not, see <http://www.gnu.org/licenses/>.
#
#  Script developed by EyeSeeTea Ltd
#

#########################################
# NTP launching & NAT acceptance script #
#########################################

now=$(date +"%F %k:%M:%S")
log_tag="[TUCAN3G]"
log_level="-p local0.notice"

case "$1" in
start)
  logger $log_level -t $log_tag -s "Defining ntp iptables rules and launching ntp daemon..."
  iptables -A INPUT -j ACCEPT -p tcp --dport 123
  # To keep it started, we use until to respawn each time it dies
  until $(/usr/sbin/ntpd -p /var/run/ntpd.pid -g -u 106:110); do
    logger $log_level -t $log_tag -s "[$now] - [FATAL] - ntp crashed with exit code $?. Respawning..."
    sleep 1
  done
  logger $log_level -t $log_tag -s "Done\n"
  ;;
stop)
  logger $log_level -t $log_tag -s "Removing ntp iptables rules and stopping ntp daemon..."
  iptables -D INPUT -j ACCEPT -p tcp --dport 123
  kill -9 $(cat /var/run/ntpd.pid)
  logger $log_level -t $log_tag -s "Done\n"
  ;;
*)
  logger $log_level -t $log_tag -s "[$now] - [FATAL] - Unknow command, only available are start|stop"
  ;;
esac

exit 0

