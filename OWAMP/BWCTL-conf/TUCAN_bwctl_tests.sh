#!/bin/bash
set -x
### BEGIN INIT INFO
# Provides:          TUCAN_bwctl_tests
# Required-Start:    $local_fs $remote_fs $network $syslog $nocatsplash $TUCAN_ntp $TUCAN_owamp $TUCAN_bwctl
# Required-Stop:
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# X-Interactive:     false
# Short-Description: TUCAN3G testbed bwctl measurements automatic launch
# Description: TUCAN3G testbed bwctl measurements automatic launch
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

##############################################
# BWCTL measurements automatic launch script #
##############################################

now=$(date +"%F %k:%M:%S")
log_tag="[TUCAN3G]"
log_level="-p local0.notice"
RETURN_BAD_COMMAND=2
RETURN_BAD_FORMAT=1
RETURN_SUCCESS=0
RETURN=
KEYS=
IPS_SRC=
IPS_DST=
DSS=


case "$1" in
start)
  logger $log_level -t $log_tag -s "Starting bwctld tests configured in ips.conf..."
  # script is only executed when ips.conf file is present
  if [ -r /etc/bwctld/ips.conf ]; then
    # Data parsing
    KEYS=( $( awk 'NR >= 1  {print $1}' /etc/bwctld/ips.conf ) )
    IPS_SRC=( $( awk 'NR >= 1  {print $2}' /etc/bwctld/ips.conf ) )
    IPS_DST=( $( awk 'NR >= 1  {print $3}' /etc/bwctld/ips.conf) )
    DSS=( $( awk 'NR >= 1  {print $4}' /etc/bwctld/ips.conf ) )

    # Validations
    if [ ${#KEYS[@]} -gt ${#IPS_SRC[@]} ] || [ ${#KEYS[@]} -gt ${#IPS_DST[@]} ] || [ ${#KEYS[@]} -gt ${#DSS[@]} ]; then
      echo "Error, bad ips.conf format" >&2
      exit $RETURN_BAD_FORMAT
    fi

    i=0
    for key in ${KEYS[@]}; do
      bwctl -T iperf3 -f m -D ${DSS[$i]} --sender ${IPS_SRC[$i]} --receiver ${IPS_DST[$i]} --streaming -p -d /var/tmp --format c --parsable -d /var/tmp
      RETURN=$?
      if [ $RETURN -ne 0 ]; then
        echo "Error, bad bwctl command" >&2
        exit $RETURN_BAD_COMMAND
      fi 
      i=$(echo "$i + 1"|bc)
    done 
    logger $log_level -t $log_tag -s "Done\n"
    #$(awk 'NR >= 1 {if($1=="tacsa-nurco") print $2}' /etc/bwctld/ips.conf)
  else
    logger $log_level -t $log_tag -s "[$now] - [FATAL] - No ips.conf file detected, no measurements launched"
  fi
  ;;
stop)
  logger $log_level -t $log_tag -s "Stopping bwctld ..."
  kill -9 $(cat /var/tmp/bwctld.pid)
  logger $log_level -t $log_tag -s "Done\n"
  ;;
*)
  logger $log_level -t $log_tag -s "[$now] - [FATAL] - Unknow command, only available are start|stop"
  ;;
esac

exit $RETURN_SUCCESS
