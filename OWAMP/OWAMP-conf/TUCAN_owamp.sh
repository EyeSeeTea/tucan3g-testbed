#!/bin/sh
### BEGIN INIT INFO
# Provides:          TUCAN_owamp
# Required-Start:    $local_fs $remote_fs $network $syslog $nocatsplash $TUCAN_ntp
# Required-Stop:
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# X-Interactive:     false
# Short-Description: TUCAN3G testbed owamp automatic launch 
# Description: TUCAN3G testbed owamp automatic launch
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

#################################
# OWAMP automatic launch script #
#################################

now=$(date +"%F %k:%M:%S")
log_tag="[TUCAN3G]"
log_level="-p local0.notice"
if [ -r /etc/default/owamp ]; then
  . /etc/default/owamp
fi

case "$1" in
start)
  logger $log_level -t $log_tag -s "Starting owampd ..."
  owampd $OWAMPD_OPTS
  iptables -A INPUT -p tcp --dport 861 -j ACCEPT
  logger $log_level -t $log_tag -s "Done\n"
  ;;
stop)
  logger $log_level -t $log_tag -s "Stopping owampd ..."
  kill -9 $(cat /var/owampd.pid)
  iptables -D INPUT -p tcp --dport 861 -j ACCEPT
  logger $log_level -t $log_tag -s "Done\n"
  ;;
*)
  logger $log_level -t $log_tag -s "[$now] - [FATAL] - Unknow command, only available are start|stop"
  ;;
esac

exit 0

