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

# Store the time present in now variable
get_time(){
  now=$(date +"%F %k:%M:%S")
}

# Log messages giving a log level
# $1: log_level [ emerg | alert | crit | err | warning | notice | info ]
# $2: message
log(){
  log_level="local0.${1}"
  message="$2"
  logger -p "$log_level" -t "$log_tag" -s "$message"
}

# Launch a bwctl test using screen
# $1: DSCP
# $2: Sender IP
# $3: Receiver IP
launch_test(){
  log notice "key: $1"
  log notice "DS: $2"
  log notice "Sender: $3"
  log notice "Receiver: $4"
  tmux new -d -s "TUCAN-$1" "bash /etc/bwctld/TUCAN_bwctl_launcher.sh $2 $3 $4" \; detach \; 
}


case "$1" in
start)
  log notice "Starting bwctld tests configured in ips.conf..."
  # script is only executed when ips.conf file is present
  if [ -r /etc/bwctld/ips.conf ]; then
    # Data parsing from ips.conf file
    KEYS=( $( awk 'NR >= 1  {print $1}' /etc/bwctld/ips.conf ) )
    IPS_SRC=( $( awk 'NR >= 1  {print $2}' /etc/bwctld/ips.conf ) )
    IPS_DST=( $( awk 'NR >= 1  {print $3}' /etc/bwctld/ips.conf) )
    DSS=( $( awk 'NR >= 1  {print $4}' /etc/bwctld/ips.conf ) )

    # Validations
    if [ ${#KEYS[@]} -gt ${#IPS_SRC[@]} ] || [ ${#KEYS[@]} -gt ${#IPS_DST[@]} ] || [ ${#KEYS[@]} -gt ${#DSS[@]} ]; then
      log err "Error, bad ips.conf format"
      exit $RETURN_BAD_FORMAT
    fi

    # Launch tests
    i=0
    for key in ${KEYS[@]}; do
      launch_test "$key" "${DSS[$i]}" "${IPS_SRC[$i]}" "${IPS_DST[$i]}" 
      i=$(echo "$i + 1"|bc)
    done 
    log notice "Done\n"
  else
    get_time
    log err "[$now] - [FATAL] - No ips.conf file detected, no measurements launched"
  fi
  ;;
stop)
  log notice "Stopping bwctld ..."
  kill -9 $(cat /var/tmp/bwctld.pid)
  log notice "Done\n"
  ;;
*)
  get_time
  log err "[$now] - [FATAL] - Unknow command, only available are start|stop"
  ;;
esac

exit $RETURN_SUCCESS
