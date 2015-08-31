#!/bin/bash
set -x
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

until $(bwctl -T iperf3 -f m -D $2 --sender $3 --receiver $4 --format c --parsable -P 2 > /var/tmp/${1}.results); do
    now=$(date +"%F %k:%M:%S")
    logger -p local0.notice -t [TUCAN3G] -s "[$now] - bwctl measurement finished with exit code $?. Respawning..."
  sleep 30
done
