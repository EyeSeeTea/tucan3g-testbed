#!/usr/bin/python 
# To kick off the script, run the following from the python directory:
#   PYTHONPATH=`pwd` python testdaemon.py start

import logging
import time
from os.path import join, isfile
import json
import ConfigParser
import itertools
from daemon import runner
import sys
import os

class TUCANDaemon():
    TUCANConfFolder = '/etc/TUCAN3G'
    TUCANLogFolder = '/var/log/TUCAN3G'
    TUCANTmpFolder = '/var/tmp'
    TUCANIpsFile = join(TUCANConfFolder, 'ips.conf') 
    TUCANPidFile = 'var/run/tucand.pid'


    def __init__(self):
        # Extract some useful paths from config file
        try:
            TUCANConfFolder = config.get('general', 'etcFolder')
            TUCANLogFolder = config.get('general', 'logFolder')
            TUCANTmpFolder = config.get('general', 'tmpFolder')
            TUCANIpsFile = config.get('general', 'confFile')
            TUCANPidFile = config.get('general', 'pidPath')
        except:
            logger.setLevel(logging.ERROR)
            logger.error('Config file tucand.conf malformed. Mandatory fields missing!')
            raise

        # Daemon
        self.stdin_path = '/dev/null'
        self.stdout_path = join(TUCANLogFolder, 'tucandaemon.log') # '/dev/tty' for debugging
        self.stderr_path = join(TUCANLogFolder, 'tucandaemon.log') # '/dev/tty' for debugging
        self.pidfile_path =  '/var/run/tucand.pid'
        self.pidfile_timeout = 5


    def run(self):
        # To avoid strange behaviors if we modify file while the daemon is in execution, we first look at the file content and then 
        # we operate all the time using our memory cached file content.
        tests = dict()
        with open(self.TUCANIpsFile) as ipsConfFile:
            # Save the content of the file in a dictionary where the key is the first entry of the file, and the rest of the line is stored as a list
            for line in ipsConfFile:
                # turn a list like ['a', 'b', 'c', 'd'] into a dict like {'a': ['b', 'c', 'd']}
                key = line.split()[0]
                values = line.split()[1:]
                tests.update(dict(itertools.izip_longest(*[iter([key, values])] * 2, fillvalue="")))
        # Initial conditions
        if config.getboolean('general', 'edge'):
            if not config.getboolean('general', 'isOptimal'):
                logger.info('Suboptimal algorithm selected')
                rates = []
                # Global capacity calculus
                if config.get('general', 'edgeType') == 'UL':
                    rates = json.loads(config.get('suboptimal', 'initialDlMin'))
                elif config.get('general', 'edgeType') == 'DL':
                    rates = json.loads(config.get('suboptimal', 'initialUlMin'))
                else:
                    logger.setLevel(logging.ERROR)
                    logger.error('edge type not allowed (Only UL or DL are allowed')
                    sys.exit()
                logger.info('Initial capacity: %f kbps' % sum(rates))
                for i, iface in enumerate(json.loads(config.get('general', 'ingressIfaces'))):
                    os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                    os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                    os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, sum(rates))) # introduce a PRIO queuewith policing to maximum capacity
            else:
                logger.info('Optimal algorithm selected')
 
        # Main loop 
        while True:
            # If it is an edge node we have to configure queues according to measured bw
            if config.getboolean('general', 'edge'):
                logger.info('this is an edge node')
                # parse json results file
                data = dict()
                with open(join(self.TUCANTmpFolder, key + '.json')) as jsonFile:
                    data = json.load(jsonFile)
                # Suboptimal algorithm
                if not config.getboolean('general', 'isOptimal'):
                    senderBw = data['end']['streams'][0]['sender']['bits_per_second']
                    receiverBw = data['end']['streams'][0]['receiver']['bits_per_second']
                    logger.info("key: %s -- IP_ORIG: %s -- IP_DST: %s -- DS: %s -- SENDER BW: %s, RECEIVER BW: %s" % (key, tests[key][0], tests[key][1], tests[key][2], senderBw, receiverBw))
                    

                else:
                    logger.info('Optimal algorithm')
            else:
                # Normal node must read configuration set by edge nodes in tmp folder
                logger.info('this is a normal node')
 
            time.sleep(10)


if __name__ == "__main__":
    # Parse config file
    config = ConfigParser.ConfigParser()
    config.read('/etc/TUCAN3G/tucand.conf')
    
    daemon = TUCANDaemon()
    logger = logging.getLogger("DaemonLog")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.FileHandler("/var/log/TUCAN3G/tucandaemon.log")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    if len(sys.argv) == 2:    
        if 'stop' == sys.argv[1]:
        # To do just before deleting the object (so when stop is called)
            for i, iface in enumerate(json.loads(config.get('general', 'ingressIfaces'))):
                logger.info("cleaning ingress policing on interface %s" % iface)
                os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning

    daemon_runner = runner.DaemonRunner(daemon)
    #This ensures that the logger file handle does not get closed during daemonization
    daemon_runner.daemon_context.files_preserve=[handler.stream]
    daemon_runner.do_action()
