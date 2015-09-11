#!/usr/bin/python 
# To kick off the script, run the following from the python directory:
#   PYTHONPATH=`pwd` python testdaemon.py start

#standard python libs
import logging
import time
from os.path import join, isfile
import json
import ConfigParser

#third party libs
from daemon import runner

class TUCANDaemon():
   
    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/tty'
        self.stderr_path = '/dev/tty'
        self.pidfile_path =  '/var/run/testdaemon/testdaemon.pid'
        self.pidfile_timeout = 5
           
    def run(self):
        # Extract some useful paths from config file
        try:
            TUCANConfFolder = config.get('tucan', 'EtcFolder')
            TUCANVarFolder = config.get('tucan', 'LogFolder')
            TUCANTmpFolder = config.get('tucan', 'TmpFolder')
            TUCANIpsFile = config.get('tests', 'confFile')
        except:
            logger.setLevel(logging.ERROR)
            logger.error('Config file tucand.conf malformed. Mandatory fields missing!')
            raise

        # To avoid strange behaviors if we modify file while the daemon is in execution, we first look at the file content and then 
        # we operate all the time using our memory cached file content.
        tests = dict()
        with open(TUCANIpsFile) as ipsConfFile:
        # Save the content of the file in a dictionary where the key is the first entry of the file, and the rest of the line is stored as a list
        for line in ipsConfFile:
            # turn a list like ['a', 'b', 'c', 'd'] into a dict like {'a': ['b', 'c', 'd']}
            key = line.split()[0]
            values = line.split()[1:]
            tests.update(dict(itertools.izip_longest(*[iter([key, values])] * 2, fillvalue="")))
                 
        while True:
            for key in tests.keys():
                # locate results file for each key found in config
                if isfile(join(TUCANTmpFolder, key + '.json')):
                    # parse json results file
                    data = dict()
                    with open(join(TUCANTmpFolder, key + '.json')) as jsonFile:
                        data = json.load(jsonFile)
                    senderBw = data['end']['streams'][0]['sender']['bits_per_second']
                    receiverBw = data['end']['streams'][0]['receiver']['bits_per_second']
                    logger.info("key: %s -- IP_ORIG: %s -- IP_DST: %s -- DS: %s -- SENDER BW: %s, RECEIVER BW: %s" % (key, tests[key][0], tests[key][1], tests[key][2], senderBw, receiverBw))
                    # If it is an edge node we have to configure queues according to measured bw
                    if config.getboolean('tucan', 'edge'):
                        logger.info('this is an edge node')
 
            #Note that logger level needs to be set to logging.DEBUG before this shows up in the logs
            logger.info("Info message")
            time.sleep(10)

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

daemon_runner = runner.DaemonRunner(daemon)
#This ensures that the logger file handle does not get closed during daemonization
daemon_runner.daemon_context.files_preserve=[handler.stream]
daemon_runner.do_action()
