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
echo "DS: $1"
echo "Sender: $2"
echo "Receiver: $3"
until $(bwctl -T iperf3 -f m -D $1 --sender $2 --receiver $3 --streaming -p -d /var/tmp --format c --parsable); do
    now=$(date +"%F %k:%M:%S")
    logger -p local0.notice -t [TUCAN3G] -s "[$now] - [FATAL] - bwctl crashed with exit code $?. Respawning..."
  sleep 100
done
