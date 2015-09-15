#!/bin/sh
### BEGIN INIT INFO
# Provides:          tucand
# Required-Start:    $local_fs $remote_fs $network $syslog $nocatsplash $time TUCAN_ntp TUCAN_owamp TUCAN_bwctl TUCAN_bwctl_tests
# Required-Stop:
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# X-Interactive:     false
# Short-Description: TUCAN3G daemon launcher
# Description: TUCAN3G main daemon
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

#######################
# TUCAN3G main daemon #
#######################

now=$(date +"%F %k:%M:%S")
log_tag="[TUCAN3G]"
log_level="-p local0.notice"

case "$1" in
start)
  # Check ips.conf and tucand.conf existance
  
  logger $log_level -t $log_tag -s "Launching daemon..."
  python /etc/TUCAN3G/tucand.py start
  logger $log_level -t $log_tag -s "Done"
  ;;
stop)
  logger $log_level -t $log_tag -s "Stopping daemon..."
  python /etc/TUCAN3G/tucand.py stop
  logger $log_level -t $log_tag -s "Done"
  ;;
restart)
  logger $log_level -t $log_tag -s "Restarting daemon..."
  python /etc/TUCAN3G/tucand.py restart
  logger $log_level -t $log_tag -s "Done"
  ;;
*)
  log_level="-p local0.err"
  logger $log_level -t $log_tag -s "[$now] - [FATAL] - Unknow command. Usage: /etc/init.d/tucand.sh [start|stop|restart]"
  ;;
esac

exit 0

