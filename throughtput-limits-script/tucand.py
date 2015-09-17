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
import paramiko
from scp import SCPClient

class TUCANDaemon():
    # path vars
    TUCANConfFolder = '/etc/TUCAN3G'
    TUCANLogFolder = '/var/log/TUCAN3G'
    TUCANTmpFolder = '/var/tmp'
    TUCANIpsFile = join(TUCANConfFolder, 'ips.conf') 
    TUCANPidFile = 'var/run/tucand.pid'

    # dictionary that stores, one by link of the network, the measured dynamic capacity
    stableDynamicCapacity = dict()
    # flux UL margin by node
    fluxUlMargin = dict()
    # flux DL margin by node
    fluxDlMargin = dict()
    # dictionary that stores, one by node, the UL allowed traffic
    ulAdmittedTraffic = dict()
    # dictionary that stores, one by node, the DL allowd traffic
    dlAdmittedTraffic = dict()
    

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
            logger.setLevel(logging.INFO)
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
        tests = self.parseTests()
        # Initial conditions
        self.initializeIngress()
        # nodes from conf file
        nodes = json.loads(config.get('suboptimal', 'nodes'))

        # Main loop 
        while True:
            # if there's a configuration order from an edge node, we follow it
            for sense in ['UL', 'DL']:
                if isfile('/var/tmp/node-%s' % sense):
                    self.updateIngress('/var/tmp/node-%s' % sense)
            if config.getboolean('general', 'edge'):
                # Suboptimal algorithm
                if not config.getboolean('general', 'isOptimal'):
                    try:
                        dynamicCapacity = self.readDynamicCapacity(tests)
                    except:
                        logger.info("error reading capacity")
                        continue
                    for netIndex, key in enumerate(tests.keys()):
                        k = json.loads(config.get('suboptimal', 'k'))[netIndex]
                        beta = config.get('suboptimal', 'beta')
                        capacity = dynamicCapacity[key] * k
                        self.addDynamicCapacity(key, capacity)
                        logger.info("adding %f to %s capacity" % (capacity, key))
                        #self.logDynamicList()
                        # Only when we consider measurements stable we start changing network parameters
                        if self.isStable(key):
                            logger.info("%s has become stable" % key)
                            # Minimum margin calculus
                            ulMins = json.loads(config.get('suboptimal', 'initialULMin'))
                            ulMin = sum(ulMins[netIndex:netIndex+1])
                            dlMins = json.loads(config.get('suboptimal', 'initialDLMin'))
                            dlMin = sum(dlMins[netIndex:netIndex+1])
                            minMargin = capacity - (sum(ulMins) + sum(dlMins))
                            # Effective margin calculus
                            logger.info('Mean Dynamic Capacity: %f' % self.getMeanDynamicCapacity(key))
                            # FIXME: create effectiveMargin taking into account dynamically configured limits and not fixed limits
                            effectiveMargin = capacity - (sum(ulMins) + sum(dlMins))
                            # Link margin calculus
                            linkMargin = min([minMargin, effectiveMargin])

                            # Traffic flux margins
                            # In a network, the most close to the UL edge
                            self.fluxUlMargin.update({nodes[netIndex]: (ulMins[netIndex] / (sum(ulMins) + sum(dlMins))) * linkMargin})
                            self.fluxUlMargin.update({nodes[netIndex+1]: (ulMins[netIndex+1] / (sum(ulMins) + sum(dlMins))) * linkMargin})
                            self.fluxDlMargin.update({nodes[netIndex]: (dlMins[netIndex] / (sum(ulMins) + sum(dlMins))) * linkMargin})
                            self.fluxDlMargin.update({nodes[netIndex+1]: (dlMins[netIndex+1] / (sum(ulMins) + sum(dlMins))) * linkMargin})
                            logger.info('Minimums margin: %f -- Effective margin: %f -- Link margin: %f -- UL flux margin 1: %f -- UL flux margin 2: %f -- DL flux margin 1: %f -- DL flux margin 2: %f' % (minMargin, effectiveMargin, linkMargin, self.fluxUlMargin.get(nodes[netIndex]), self.fluxUlMargin.get(nodes[netIndex+1]), self.fluxDlMargin.get(nodes[netIndex]), self.fluxDlMargin.get(nodes[netIndex+1])))
                            
                            # Allowed traffics
                            # Initialization
                            if self.ulAdmittedTraffic.get(nodes[netIndex]) == None:
                                self.ulAdmittedTraffic.update({nodes[netIndex]: 0})
                            if self.ulAdmittedTraffic.get(nodes[netIndex+1]) == None:
                                self.ulAdmittedTraffic.update({nodes[netIndex+1]: 0})
                            if self.dlAdmittedTraffic.get(nodes[netIndex]) == None:
                                self.dlAdmittedTraffic.update({nodes[netIndex]: 0})
                            if self.dlAdmittedTraffic.get(nodes[netIndex+1]) == None:
                                self.dlAdmittedTraffic.update({nodes[netIndex+1]: 0})
                            # Calculus
                            self.ulAdmittedTraffic.update({nodes[netIndex]: self.getAdmitted(self.ulAdmittedTraffic.get(nodes[netIndex]), ulMins[netIndex], self.fluxUlMargin.get(nodes[netIndex]), beta)})
                            self.ulAdmittedTraffic.update({nodes[netIndex+1]: self.getAdmitted(self.ulAdmittedTraffic.get(nodes[netIndex+1]), ulMins[netIndex+1], self.fluxUlMargin.get(nodes[netIndex+1]), beta)})
                            self.dlAdmittedTraffic.update({nodes[netIndex]: self.getAdmitted(self.dlAdmittedTraffic.get(nodes[netIndex]), dlMins[netIndex], self.fluxDlMargin.get(nodes[netIndex]), beta)})
                            self.dlAdmittedTraffic.update({nodes[netIndex+1]: self.getAdmitted(self.dlAdmittedTraffic.get(nodes[netIndex+1]), dlMins[netIndex+1], self.fluxDlMargin.get(nodes[netIndex+1]), beta)})
                            logger.info('Allowed UL traffic 1: %f -- Allowed UL traffic 2: %f -- Allowed DL traffic 1: %f -- Allowed DL traffic 2: %f' % (self.ulAdmittedTraffic.get(nodes[netIndex]), self.ulAdmittedTraffic.get(nodes[netIndex+1]), self.dlAdmittedTraffic.get(nodes[netIndex]), self.dlAdmittedTraffic.get(nodes[netIndex+1])))
                else:
                    logger.info('Optimal algorithm')
 
            time.sleep(10)


    def getAdmitted(self, previousAdmitted, minTraffic, margin, beta):
          previousAdmitted = float(previousAdmitted)
          minTraffic = float(minTraffic)
          margin = float(margin)
          beta = float(beta)
          if not config.getboolean('suboptimal', 'altFormula'):
              logger.info('prev: %f -- min: %f -- margin: %f -- beta: %f' % (previousAdmitted, minTraffic, margin, beta))
              return max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0])
          else:
              return min([max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0]), 0]) # FIXME: Implement a mean 



    def updateIngress(self, confPath):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        for iface in json.loads(updateConfig.get('general', 'ingressIfaces')):
            os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
            os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
            os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, updateConfig.get('general', 'limit'))) # introduce a PRIO queuewith policing to maximum capacity


    def getMeanDynamicCapacity(self, key):
        dynCapList = self.stableDynamicCapacity.get(key)
        if dynCapList == None:
            return 0.0
        return sum(dynCapList)/len(dynCapList)


    def logDynamicList(self):
        for entry in self.stableDynamicCapacity.keys():
            capList = self.stableDynamicCapacity.get(entry)
            logger.info('----')
            for cap in capList:
                logger.info('[ %f ]' % cap)
            logger.info('----')


    def addDynamicCapacity(self, key, dynamicCapacity):
        # We need a stack of 10 elements to calculate a valid capacity
        dynCapList = self.stableDynamicCapacity.get(key)
        if dynCapList == None:
            dynCapList = [ dynamicCapacity ]
        else:
            logger.info('stability configured: %d' % int(config.get('suboptimal', 'capacityStability')))
            if len(dynCapList) == int(config.get('suboptimal', 'capacityStability')):
                dynCapList.reverse()
                dynCapList.pop()
                dynCapList.reverse()
            dynCapList.append(dynamicCapacity)
        self.stableDynamicCapacity.update({key: dynCapList})


    def isStable(self, key):
        dynCapList = self.stableDynamicCapacity.get(key)
        if dynCapList != None:
            logger.info("dynamic list contains %d elements" % len(dynCapList))
        return dynCapList != None and len(dynCapList) == int(config.get('suboptimal', 'capacityStability'))


    def readDynamicCapacity(self, tests):
        # parse json results file and return them in a dictionary we will use later
        data = dict()
        dynamicCapacity = dict()
        for key in tests.keys():
            linkDynamicCapacity = 0.0
            for sense in [ 'out', 'in' ]:
                with open('%s-%s.json' % (join(self.TUCANTmpFolder, key), sense)) as jsonFile:
                    try:
                        data = json.load(jsonFile)
                    except:
                        logger.info("json file couldn't be parsed. This is normal for the first minute of operation, while the first measurements are being done. If this message persist after that time, please, check out your ips.conf configuration.")
                        raise
                senderBw = data['end']['streams'][0]['sender']['bits_per_second']
                receiverBw = data['end']['streams'][0]['receiver']['bits_per_second']
                logger.info("key: %s -- in <--> out: %s <--> %s -- DS: %s -- SENDER BW: %s, RECEIVER BW: %s SENSE: %s" % (key, tests[key][0], tests[key][1], tests[key][2], senderBw, receiverBw, sense))
                linkDynamicCapacityBySense = receiverBw/1000.0
                linkDynamicCapacity+=linkDynamicCapacityBySense
            logger.info("link dynamic capacity = %f" % linkDynamicCapacity)
            dynamicCapacity.update({key: linkDynamicCapacity})
        return dynamicCapacity


    def parseTests(self):
        tests = dict() 
        with open(self.TUCANIpsFile) as ipsConfFile:
            # Save the content of the file in a dictionary where the key is the first entry of the file, and the rest of the line is stored as a list
            for line in ipsConfFile:
                # turn a list like ['a', 'b', 'c', 'd'] into a dict like {'a': ['b', 'c', 'd']}
                key = line.split()[0]
                values = line.split()[1:]
                tests.update(dict(itertools.izip_longest(*[iter([key, values])] * 2, fillvalue="")))
        return tests


    def initializeIngress(self):
        # edge nodes must schedule every other node ingress queues
        if config.getboolean('general', 'edge'):
            rates = []
            edgePosition = 0
            nodes = json.loads(config.get('suboptimal', 'nodes'))
            ingressIfaces = json.loads(config.get('general', 'ingressIfaces'))
            logger.info('this is an edge node')
            if config.get('general', 'edgeType') == 'UL':
                rates = json.loads(config.get('suboptimal', 'initialDlMin'))
                edgePosition = 0
            elif config.get('general', 'edgeType') == 'DL':
                rates = json.loads(config.get('suboptimal', 'initialUlMin'))
                edgePosition = len(nodes)-1
            else:
                logger.setLevel(logging.ERROR)
                logger.error('edge type not allowed (Only UL or DL are allowed')
                sys.exit()
            for node in range(0, len(nodes)):
                # for this node, we directly configure queues
                if node == edgePosition:
                    logger.info('Limiting ingress ifaces to %f kbps' % rates[edgePosition])
                    for i, iface in enumerate(ingressIfaces[edgePosition]):
                        os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                        os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                        os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, rates[edgePosition])) # introduce a PRIO queuewith policing to maximum capacity
                # for the rest of nodes we create a config file and send it to them by SSH protocol
                else:
                    logger.info('Limiting remote ingress ifaces to %f kbps' % rates[node])
                    remoteConfig = ConfigParser.ConfigParser()
                    remoteConfFile = open('/var/tmp/node-%s.conf' % config.get('general', 'edgeType'), 'w')
                    remoteConfig.add_section('general')
                    remoteConfig.set('general', 'ingressIfaces', ingressIfaces[node])
                    remoteConfig.set('general', 'limit', rates[node])
                    remoteConfig.write(remoteConfFile)
                    remoteConfFile.close()
                    # TODO: send it with paramiko
                    ssh = self.createSSHClient(nodes[node])
                    scp = SCPClient(ssh.get_transport())
                    scp.put('/var/tmp/node-%s.conf' % config.get('general', 'edgeType'), '/var/tmp/')
       

    def createSSHClient(self, server):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(server)
        logger.info('connected to %s' % server)
        return client


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

    # TODO: when we stop the daemon we must restore the interfaces queues
    #if len(sys.argv) == 2:    
    #    if 'stop' == sys.argv[1]:
    #        # Remove ingress queues previously configured
    #        for i, iface in enumerate(json.loads(config.get('general', 'ingressIfaces'))):
    #            logger.info("cleaning ingress policing on interface %s" % iface)
    #            os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning

    daemon_runner = runner.DaemonRunner(daemon)
    #This ensures that the logger file handle does not get closed during daemonization
    daemon_runner.daemon_context.files_preserve=[handler.stream]
    daemon_runner.do_action()
