#!/bin/bash
#set -x
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
# Script params:
# $1: Unique keyword
# $2: DSCP
# $3: Sender IP
# $4: Receiver IP
# $5: Total amount of tests

while $(bwctl -T iperf3 -f m -D $2 --sender $3 --receiver $4 --format c --parsable -P 1 > /var/tmp/${1}.tmp); do
  now=$(date +"%F %k:%M:%S")
  logger -p local0.notice -t [TUCAN3G] -s "[$now] - bwctl measurement finished with exit code $?. Respawning..."
  # bwctl create bad formed jsons as it introduced a tag in the start and ending of the file we have to manually remove
  lines_number=$(wc -l /var/tmp/${1}.tmp|cut -d ' ' -f 1)
  lines_number=$(($lines_number - 2))
  head -n $lines_number /var/tmp/${1}.tmp > /var/tmp/${1}-tmp.tmp
  lines_number=$(($lines_number - 2))
  tail -n $lines_number /var/tmp/${1}-tmp.tmp > /var/tmp/${1}.json
  rm /var/tmp/${1}-tmp.tmp
  sleep 1
done
