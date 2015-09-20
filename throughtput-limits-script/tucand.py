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


class Register():
    registers = dict()
    stability = 0
    
    def __init__(self, stability):
        self.stability = stability

    def add(self, register, key, value):
        registerDict = self.registers.get(register)
        if registerDict == None:
            registerDict = {key: [value]}
        else:
            registerList = registerDict.get(key)
            if registerList == None:
                registerList = [value]
            else:
                if len(registerList) == int(self.stability):
                    registerList.reverse()
                    registerList.pop()
                    registerList.reverse()
                registerList.append(value)
            registerDict.update({key: registerList})
        self.registers.update({register: registerDict})

    def last(self, register, key):
        if self.registers.get(register) == None or self.registers.get(register).get(key) == None:
            return 0
        return self.registers.get(register).get(key)[-1]

    def isStable(self, register, key):
        registerDict = self.registers.get(register)
        if registerDict == None:
            return False
        registerList = registerDict.get(key)
        return registerList != None and (len(registerList) == int(self.stability))

    def getAverage(self, register, key):
        registerDict = self.registers.get(register)
        if registerDict == None:
            return 0.0
        registerList = registerDict.get(key)
        if registerList == None:
            return 0.0
        return sum(registerList)/len(registerList)


class TUCANDaemon():
    # path vars
    TUCANConfFolder = '/etc/TUCAN3G'
    TUCANLogFolder = '/var/log/TUCAN3G'
    TUCANTmpFolder = '/var/tmp'
    TUCANIpsFile = join(TUCANConfFolder, 'ips.conf') 
    TUCANPidFile = 'var/run/tucand.pid'
    config = None

    # registers that stores, stableDynamicCapacity, traffic UL and DL limits
    registers = None

    # flux UL margin by node
    fluxUlMargin = dict()
    # flux DL margin by node
    fluxDlMargin = dict()
    

    def __init__(self, config):
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
        self.config = config
        self.registers = Register(int(config.get('suboptimal', 'capacityStability')))


    def run(self):
        # To avoid strange behaviors if we modify file while the daemon is in execution, we first look at the file content and then 
        # we operate all the time using our memory cached file content.
        tests = self.parseTests()
        # Set initial conditions (the UL edge is in charge of this
        if config.getboolean('general', 'edge') and config.get('general', 'edgeType') == 'UL':
            self.initializeIngress()
        # nodes from conf file
        nodes = json.loads(config.get('suboptimal', 'nodes'))

        # Main loop 
        while True:
            # if there's a configuration order from an edge node, we follow it
            for sense in ['UL', 'DL']:
                if isfile('/var/tmp/node-%s' % sense):
                    self.updateIngress('/var/tmp/node-%s' % sense)
            # if we have to configure egress queues, we do it
            if (isfile('/etc/TUCAN3G/node-egress.conf')):
                self.updateEgress('/etc/TUCAN3G/node-egress.conf')
            # algorithms
            if config.getboolean('general', 'edge') and config.get('general', 'edgeType') == 'UL':
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
                        self.registers.add('dynamicCapacity', key, capacity)
                        logger.info("adding %f to %s capacity" % (capacity, key))
                        # Only when we consider measurements stable we start changing network parameters
                        if self.registers.isStable('dynamicCapacity', key):
                            logger.info("%s has become stable" % key)
                            # Minimum margin calculus
                            ulMins = json.loads(config.get('suboptimal', 'initialULMin'))
                            ulMin = sum(ulMins[netIndex:netIndex+1])
                            dlMins = json.loads(config.get('suboptimal', 'initialDLMin'))
                            dlMin = sum(dlMins[netIndex:netIndex+1])
                            minMargin = capacity - (sum(ulMins) + sum(dlMins))
                            # Effective margin calculus
                            logger.info('Mean Dynamic Capacity: %f' % self.registers.getAverage('dynamicCapacity', key))
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
                            traffic = self.getAdmitted(self.registers.last('ulLimits', nodes[netIndex]), ulMins[netIndex], self.fluxUlMargin.get(nodes[netIndex]), beta, self.registers.getAverage('ulLimits', nodes[netIndex]))
                            self.registers.add('ulLimits', nodes[netIndex], traffic)

                            traffic = self.getAdmitted(self.registers.last('ulLimits', nodes[netIndex+1]), ulMins[netIndex+1], self.fluxUlMargin.get(nodes[netIndex+1]), beta, self.registers.getAverage('ulLimits', nodes[netIndex+1]))
                            self.registers.add('ulLimits', nodes[netIndex+1], traffic)

                            traffic = self.getAdmitted(self.registers.last('dlLimits', nodes[netIndex]), dlMins[netIndex], self.fluxDlMargin.get(nodes[netIndex]), beta, self.registers.getAverage('dlLimits', nodes[netIndex]))
                            self.registers.add('dlLimits', nodes[netIndex], traffic)

                            traffic = self.getAdmitted(self.registers.last('dlLimits', nodes[netIndex+1]), dlMins[netIndex+1], self.fluxDlMargin.get(nodes[netIndex+1]), beta, self.registers.getAverage('dlLimits', nodes[netIndex+1]))
                            self.registers.add('dlLimits', nodes[netIndex+1], traffic)

                            logger.info('Allowed UL traffic 1: %f -- Allowed UL traffic 2: %f -- Allowed DL traffic 1: %f -- Allowed DL traffic 2: %f' % (self.registers.last('ulLimits', nodes[netIndex]), self.registers.last('ulLimits', nodes[netIndex+1]), self.registers.last('dlLimits', nodes[netIndex]), self.registers.last('dlLimits', nodes[netIndex+1])))

                            # Create ingress configuration files and send DL edge file to it
                            updateIngressConfFiles()
                else:
                    logger.info('Optimal algorithm')
 
            time.sleep(10)

    def updateIngressConfFiles():
        # Some needed vars
        nodes = json.loads(config.get('suboptimal', 'nodes'))
        ulIfaces = json.loads(config.get('general', 'ulIfaces'))
        dlIfaces = json.loads(config.get('general', 'dlIfaces'))
        ulRates = [self.registers.last('ulLimits', nodes[0]), self.registers.last('ulLimits', nodes[1])]
        dlRates = [self.registers.last('dlLimits', nodes[0]), self.registers.last('ulLimits', nodes[1])]

        for sense, edge in ['UL', 'DL'], [0, 1]:
            remoteConfig = ConfigParser.ConfigParser()
            remoteConfFile = open('/var/tmp/node-%s.conf' % sense, 'w')
            remoteConfig.add_section('general')
            remoteConfig.set('general', 'ingressIfaces', ulIfaces[edge]+dlIfaces[edge])
            remoteConfig.set('general', 'limit', [ulRates[edge]]*len(ulIfaces[edge]+[dlRates[edge]]*len(dlIfaces[edge])))
            remoteConfig.write(remoteConfFile)
            remoteConfFile.close()

        ssh = self.createSSHClient(nodes[1])
        scp = SCPClient(ssh.get_transport())
        scp.put('/var/tmp/node-DL.conf' % config.get('general', 'edgeType'), '/var/tmp/')
 

    def getAdmitted(self, previousAdmitted, minTraffic, margin, beta, averageTraffic):
        previousAdmitted = float(previousAdmitted)
        minTraffic = float(minTraffic)
        margin = float(margin)
        beta = float(beta)
        if not config.getboolean('suboptimal', 'altFormula'):
            logger.info('prev: %f -- min: %f -- margin: %f -- beta: %f' % (previousAdmitted, minTraffic, margin, beta))
            return max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0])
        else:
            return min([max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0]), averageTraffic])


    def updateIngress(self, confPath):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        for ifaceNumber, iface in enumerate(json.loads(updateConfig.get('general', 'ingressIfaces'))):
            os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
            os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
            os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, json.loads(updateConfig.get('general', 'limit'))[ifaceNumber])) # introduce a PRIO queuewith policing to maximum capacity


    def updateEgress(self, confPath):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        limits = json.loads(updateConfig.get('general', 'limit'))
        for ifaceNumber, iface in enumerate(json.loads(updateConfig.get('general', 'egressIfaces'))):
            # preventive egress cleaning
            os.system("tc qdisc del dev %s root" % iface) 
            # main dsmark & classifier
            os.system("tc qdisc add dev %s handle 1:0 root dsmark indices 64 set_tc_index" % iface)
            os.system("tc filter add dev %s parent 1:0 protocol ip prio 1 tcindex mask 0xfc shift 2" % iface)
            # main htb qdisc & class
            os.system("tc qdisc add dev %s parent 1:0 handle 2:0 htb default 20" % iface)
            os.system("tc class add dev %s parent 2:0 classid 2:1 htb rate %fkbps ceil %fkbps" % (iface, float(limits[ifaceNumber]), float(limits[ifaceNumber])))
            # EF Class (2:10)
            os.system("tc class add dev %s parent 2:1 classid 2:10 htb rate %fkbps ceil %fkbps prio 1" % (iface, 0.1 * float(limits[ifaceNumber]), float(limits[ifaceNumber])))
            os.system("tc qdisc add dev %s parent 2:10 pfifo limit 5" % iface)
            os.system("tc filter add dev %s parent 2:0 protocol ip prio 1 handle 0x2e tcindex classid 2:10 pass_on" % iface)
            # BE Class (2:20)
            os.system("tc class add dev %s parent 2:1 classid 2:20 htb rate %fkbps ceil %fkbps prio 0" % (iface, 0.9 * float(limits[ifaceNumber]), float(limits[ifaceNumber])))
            os.system("tc qdisc add dev %s parent 2:20 red limit 60KB min 15KB max 45KB burst 20 avpkt 1000 bandwidth %fkbps probability 0.4" % (iface, float(limits[ifaceNumber])))
            os.system("tc filter add dev %s parent 2:0 protocol ip prio 2 handle 0 tcindex mask 0 classid 2:20 pass_on" % iface)
        
 
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
            ulIfaces = json.loads(config.get('general', 'ulIfaces'))
            dlIfaces = json.loads(config.get('general', 'dlIfaces'))
            logger.info('this is an edge node')
            ulRates = json.loads(config.get('suboptimal', 'initialUlMin'))
            dlRates = json.loads(config.get('suboptimal', 'initialDlMin'))
            dlEdgePosition = len(nodes)-1
            for node in range(0, len(nodes)):
                # for this node, we directly configure queues
                if node == 0: # UL
                    logger.info('Applying initial policing')
                    for iface in ulIfaces[0]:
                        os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                        os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                        os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, ulRates[0])) # introduce a PRIO queuewith policing to maximum capacity
                    for iface in dlIfaces[0]:
                        os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                        os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                        os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %fkbps burst 18k drop flowid :1" % (iface, dlRates[0])) # introduce a PRIO queuewith policing to maximum capacity
                    
                # for the rest of nodes we create a config file and send it to them by SSH protocol
                elif node == dlEdgePosition:
                    remoteConfig = ConfigParser.ConfigParser()
                    remoteConfFile = open('/var/tmp/node-%s.conf' % config.get('general', 'edgeType'), 'w')
                    remoteConfig.add_section('general')
                    remoteConfig.set('general', 'ingressIfaces', ulIfaces[1]+dlIfaces[1])
                    remoteConfig.set('general', 'limit', [ulRates[1]]*len(ulIfaces[1]+[dlRates[1]]*len(dlIfaces[1])))
                    remoteConfig.write(remoteConfFile)
                    remoteConfFile.close()
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
    
    daemon = TUCANDaemon(config)
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
