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
import math
import operator
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
        self.registers = Register(int(config.get('algorithms', 'capacityStability')))


    def run(self):
        # To avoid strange behaviors if we modify file while the daemon is in execution, we first look at the file content and then 
        # we operate all the time using our memory cached file content.
        tests = self.parseTests()
        # Set initial conditions (the UL edge is in charge of this)
        if config.getboolean('rol', 'edge') and config.get('rol', 'edgeType') == 'UL':
            self.initializeIngress()
        # nodes and gateways to hnbs from conf file
        hnbGateways = json.loads(config.get('hnbs', 'hnbGateways'))
        nodes = json.loads(config.get('algorithms', 'nodes'))

        # Main loop 
        while True:
            # if there's a configuration order from an edge node, we follow it
            for sense in ['UL', 'DL']:
                if isfile('/var/tmp/node-%s.conf' % sense):
                    self.updateIngress('/var/tmp/node-%s.conf' % sense)
            # if we have to configure egress queues, we do it
            if (isfile('/etc/TUCAN3G/node-egress.conf')):
                self.updateEgress('/etc/TUCAN3G/node-egress.conf')
            # algorithms
            if config.getboolean('rol', 'edge') and config.get('rol', 'edgeType') == 'UL':
                try:
                    dynamicCapacity = self.readDynamicCapacity(tests)
                except:
                    logger.info("error reading capacity")
                    continue
                for netIndex, key in enumerate(tests.keys()):
                    k = json.loads(config.get('algorithms', 'k'))[netIndex]
                    beta = config.get('algorithms', 'beta')
                    capacity = dynamicCapacity[key] * k
                    self.registers.add('dynamicCapacity', key, capacity)
                    logger.info("adding %f to %s capacity" % (capacity, key))
                    # Only when we consider measurements stable we start changing network parameters
                    if self.registers.isStable('dynamicCapacity', key):
                        logger.info("%s has become stable" % key)
                        # Minimum margin calculus
                        ulMins = json.loads(config.get('algorithms', 'initialULMin'))
                        ulMinSum = sum(ulMins)
                        dlMins = json.loads(config.get('algorithms', 'initialDLMin'))
                        dlMinSum = sum(dlMins)
                        minMargin = capacity - (ulMinSum + dlMinSum)
                        logger.info('Mean Dynamic Capacity: %f' % self.registers.getAverage('dynamicCapacity', key))
                        # Effective margin calculus
                        previouslyAdmittedTraffic = 0.0
                        for hnb in hnbGateways:
                            for senses in ['UL', 'DL']:
                                previouslyAdmittedTraffic += self.registers.last('%sLimits' % sense, hnb)

                        effectiveMargin = capacity - previouslyAdmittedTraffic 
                        # Link margin calculus
                        linkMargin = min([minMargin, effectiveMargin])

                        # Traffic flux margins
                        # In a network, the most close to the UL edge
                        for hnbIndex, hnb in enumerate(hnbGateways):
                            for sense in ['UL', 'DL']:
                                self.registers.add('flux%smargin' % sense, hnb, ulMins[hnbIndex]/(ulMinSum+dlMinSum))

                                logger.info('Minimums margin: %f -- Effective margin: %f -- Link margin: %f -- %s: %f ' % (minMargin, effectiveMargin, linkMargin, 'flux%smargin' % sense, self.registers.last('flux%smargin' % sense, hnb)))
                                
                                # Allowed traffics
                                uldlMin = (ulMins[hnbIndex]) if sense == 'UL' else (dlMins[hnbIndex])
                                traffic = self.getAdmitted(self.registers.last('%sLimits' % sense, hnb),  uldlMin, self.registers.last('flux%smargin' % sense, hnb), beta, self.registers.getAverage('%sLimits' % sense, hnb))
                                self.registers.add('%sLimits' % sense, hnb, traffic)
       
                                logger.info('Allowed %s traffic for %s: %f' % (sense, hnb, self.registers.last('%sLimits' % sense, hnb)))
    
                        # Create ingress configuration files and send to DL edge
                        self.updateIngressConfFiles()
 
            time.sleep(10)

    def updateIngressConfFiles(self):
        # Some needed vars
        nodes = json.loads(config.get('hnbs', 'hnbGateways'))
        hnbNetworks = json.loads(config.get('hnbs', 'hnbNetworks'))

        ulIfaces = json.loads(config.get('hnbs', 'ulIfaces'))
        ulIfbIfaces = json.loads(config.get('hnbs', 'ulIfbIfaces'))
        ulHtbQueues = json.loads(config.get('hnbs', 'ulHtbQueues'))
        ulMarks = json.loads(config.get('hnbs', 'ulMarks'))
        ulRates = [self.registers.last('ULLimits', nodes[0]), self.registers.last('ULLimits', nodes[1])]

        dlIfaces = json.loads(config.get('hnbs', 'dlIfaces'))
        dlIfbIfaces = json.loads(config.get('hnbs', 'dlIfbIfaces'))
        dlHtbQueues = json.loads(config.get('hnbs', 'dlHtbQueues'))
        dlMarks = json.loads(config.get('hnbs', 'dlMarks'))
        dlRates = [self.registers.last('DLLimits', nodes[0]), self.registers.last('DLLimits', nodes[1])]
        
            

        for sense, edge, ifaces, ifbIfaces, htbQueues, marks, rates in zip(['UL', 'DL-remote'], [0, 1], [ulIfaces, dlIfaces], [ulIfbIfaces, dlIfbIfaces], [ulHtbQueues, dlHtbQueues], [ulMarks, dlMarks], [ulRates, dlRates]):

            remoteConfig = ConfigParser.ConfigParser()
            remoteConfFile = open('/var/tmp/node-%s.conf' % sense, 'w')

            # Section policing
            remoteConfig.add_section('policing')

            # ingressIfaces
            ifacesToWrite = reduce(operator.add, ifaces)
            logger.info('ifaces to write %s' % ifacesToWrite)
            remoteConfig.set('policing', 'ingressIfaces', json.dumps(ifacesToWrite))

            # ifbIfaces
            ifacesToWrite = reduce(operator.add, ifbIfaces)
            logger.info('ifb ifaces to write %s' % ifacesToWrite)
            remoteConfig.set('policing', 'ifbIfaces', json.dumps(ifacesToWrite))
            
            # htbQueues
            htbQueuesToWrite = reduce(operator.add, htbQueues)
            logger.info('htb queues to write %s' % htbQueuesToWrite)
            remoteConfig.set('policing', 'htbQueues', json.dumps(htbQueuesToWrite))

            # marks
            marksToWrite = reduce(operator.add, marks)
            logger.info('marks to write %s' % marksToWrite)
            remoteConfig.set('policing', 'marks', json.dumps(marksToWrite))

            # networks
            networksToWrite = reduce(operator.add, hnbNetworks)
            logger.info('networks to write %s' % networksToWrite)
            remoteConfig.set('policing', 'hnbNetworks', json.dumps(networksToWrite))
            
            # limits
            logger.info('rates: %s' % rates)
            remoteConfig.set('policing', 'limit', json.dumps(rates))
            # limits
            #remoteConfig.set('policing', 'limit', ([ulRates[edge]]*len(ulIfaces[edge])+([dlRates[edge]]*len(dlIfaces[edge]))))
            #logger.info('limit-old: %s' % [ulRates[edge]]*len(ulIfaces[edge])+([dlRates[edge]]*len(dlIfaces[edge])))
            remoteConfig.write(remoteConfFile)
            remoteConfFile.close()

        ssh = self.createSSHClient(nodes[1])
        scp = SCPClient(ssh.get_transport())
        scp.put('/var/tmp/node-DL-remote.conf', '/var/tmp/node-UL.conf')
       

    def getAdmitted(self, previousAdmitted, minTraffic, margin, beta, averageTraffic):
        previousAdmitted = float(previousAdmitted)
        minTraffic = float(minTraffic)
        margin = float(margin)
        beta = float(beta)
        if not config.getboolean('algorithms', 'altFormula'):
            logger.info('prev: %f -- min: %f -- margin: %f -- beta: %f' % (previousAdmitted, minTraffic, margin, beta))
            return max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0])
        else:
            return min([max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0]), averageTraffic])


    def updateIngress(self, confPath):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        limits = json.loads(updateConfig.get('policing', 'limit'))
        ifaces = json.loads(updateConfig.get('policing', 'ingressIfaces'))
        ifbIfaces = json.loads(updateConfig.get('policing', 'ifbIfaces'))
        htbQueues = json.loads(updateConfig.get('policing', 'htbQueues'))
        marks = json.loads(updateConfig.get('policing', 'marks'))
        hnbNetworks = json.loads(updateConfig.get('policing', 'hnbNetworks'))
        logger.info("reading %s file" % confPath)
        
        os.system("iptables -t mangle -F") 
        logger.info("iptables -t mangle -F") 
        os.system("iptables -t mangle -X QOS") 
        logger.info("iptables -t mangle -X QOS") 
        os.system("iptables -t mangle -N QOS")
        logger.info("iptables -t mangle -N QOS")
        for ifaceNumber, iface in enumerate(ifaces):
            if math.floor(float(limits[ifaceNumber])) == 0:
                logger.info('cannot establish rate 0')
                continue
            os.system("iptables -t mangle -A FORWARD -o %s -j QOS" % iface)
            logger.info("iptables -t mangle -A FORWARD -o %s -j QOS" % iface)
            os.system("iptables -t mangle -A OUTPUT -o %s -j QOS" % iface)
            logger.info("iptables -t mangle -A OUTPUT -o %s -j QOS" % iface)
            # preventive ingress cleaning
            os.system("tc qdisc del dev %s ingress" % iface) 
            logger.info("tc qdisc del dev %s ingress" % iface)
            os.system("tc qdisc del dev %s root" % ifbIfaces[ifaceNumber])
            logger.info("tc qdisc del dev %s root" % ifbIfaces[ifaceNumber])
            os.system("tc qdisc del dev %s ingress" % ifbIfaces[ifaceNumber])
            logger.info("tc qdisc del dev %s ingress" % ifbIfaces[ifaceNumber])
            # adding ingress queue
            os.system("tc qdisc add dev %s ingress handle ffff:" % iface)
            logger.info("tc qdisc add dev %s ingress handle ffff:" % iface)
            # parent HTB default traffic to 3:31
            os.system("tc qdisc add dev %s root handle 3: htb default 31" % ifbIfaces[ifaceNumber])
            logger.info("tc qdisc add dev %s root handle 3: htb default 31" % ifbIfaces[ifaceNumber])
            os.system("tc class add dev %s parent 3: classid 3:3 htb rate %dkbit" % (ifbIfaces[ifaceNumber], math.floor(float(limits[ifaceNumber]))))
            logger.info("tc class add dev %s parent 3: classid 3:3 htb rate %dkbit" % (ifbIfaces[ifaceNumber], math.floor(float(limits[ifaceNumber]))))
            # HTB 3:31 to receive default traffic
            os.system("tc class add dev %s parent 3:3 classid 3:31 htb rate 100kbit ceil %dkbit" % (ifbIfaces[ifaceNumber], math.floor(float(limits[ifaceNumber]))))
            logger.info("tc class add dev %s parent 3:3 classid 3:31 htb rate 100kbit ceil %dkbit" % (ifbIfaces[ifaceNumber], math.floor(float(limits[ifaceNumber]))))

            # per-HNB queues
            for queueNumber, queue in enumerate(htbQueues):
                logger.info('setting iface %s -- ifbIface %s -- queue %s -- network %s' % (iface, ifbIfaces[ifaceNumber], queue, hnbNetworks[queueNumber]))
                os.system("tc class add dev %s parent 3:3 classid %s htb rate %dkbit ceil %dkbit" % (ifbIfaces[ifaceNumber], queue, math.floor(float(limits[ifaceNumber])), math.floor(float(limits[ifaceNumber]))))
                logger.info("tc class add dev %s parent 3:3 classid %s htb rate %dkbit ceil %dkbit" % (ifbIfaces[ifaceNumber], queue, math.floor(float(limits[ifaceNumber])), math.floor(float(limits[ifaceNumber]))))
                os.system("tc filter add dev %s parent 3:0 protocol ip handle %s fw flowid %s" % (ifbIfaces[ifaceNumber], marks[queueNumber], queue))
                logger.info("tc filter add dev %s parent 3:0 protocol ip handle %s fw flowid %s" % (ifbIfaces[ifaceNumber], marks[queueNumber], queue))
                os.system("iptables -t mangle -A QOS -j CONNMARK --restore-mark")
                logger.info("iptables -t mangle -A QOS -j CONNMARK --restore-mark")
                os.system("iptables -t mangle -A QOS -s %s -m mark --mark 0 -j MARK --set-mark %s" % (hnbNetworks[queueNumber], marks[queueNumber]))
                logger.info("iptables -t mangle -A QOS -s %s -m mark --mark 0 -j MARK --set-mark %s" % (hnbNetworks[queueNumber], marks[queueNumber]))
                os.system("iptables -t mangle -A QOS -j CONNMARK --save-mark")
                logger.info("iptables -t mangle -A QOS -j CONNMARK --save-mark")
                os.system("tc filter add dev %s parent ffff: protocol ip u32 match u32 0 0 action xt -j CONNMARK --restore-mark action mirred egress redirect dev %s flowid ffff:%d" % (iface, ifbIfaces[ifaceNumber], queueNumber+1))


    def updateEgress(self, confPath):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        logger.info("reading %s file" % confPath)
        for ifaceNumber, iface in enumerate(json.loads(updateConfig.get('queues', 'egressIfaces'))):
            # preventive egress cleaning
            os.system("tc qdisc del dev %s root" % iface) 
            logger.info("tc qdisc del dev %s root" % iface) 
            # we configure a PRIO with 3 pfifo_fast queues inside
            os.system("tc qdisc add dev %s root handle 1: prio" % iface)
            logger.info("tc qdisc add dev %s root handle 1: prio" % iface)
            os.system("tc qdisc add dev %s parent 1:1 handle 10: pfifo_fast" % iface)
            logger.info("tc qdisc add dev %s parent 1:1 handle 10: pfifo_fast" % iface)
            os.system("tc qdisc add dev %s parent 1:2 handle 20: pfifo_fast" % iface)
            logger.info("tc qdisc add dev %s parent 1:2 handle 20: pfifo_fast" % iface)
            os.system("tc qdisc add dev %s parent 1:3 handle 30: pfifo_fast" % iface)
            logger.info("tc qdisc add dev %s parent 1:3 handle 30: pfifo_fast" % iface)
        
 
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
        if config.getboolean('rol', 'edge'):
            rates = []
            edgePosition = 0
            nodes = json.loads(config.get('algorithms', 'nodes'))
            logger.info('%s' % config.get('hnbs', 'ulIfaces'))
            ulIfaces = json.loads(config.get('hnbs', 'ulIfaces'))
            dlIfaces = json.loads(config.get('hnbs', 'dlIfaces'))
            logger.info('this is an edge node')
            ulRates = json.loads(config.get('algorithms', 'initialUlMin'))
            dlRates = json.loads(config.get('algorithms', 'initialDlMin'))
            dlEdgePosition = len(nodes)-1
            for node in range(0, len(nodes)):
                # for this node, we directly configure queues
                if node == 0: # UL
                    logger.info('Applying initial policing')
                    for iface in ulIfaces[0]:
                        os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                        os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                        os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %dkbit burst 18k drop flowid :1" % (iface, math.floor(ulRates[0]))) # introduce a PRIO queuewith policing to maximum capacity
                    for iface in dlIfaces[0]:
                        os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning
                        os.system("tc qdisc add dev %s handle ffff: ingress" % iface) # add ingress root
                        os.system("tc filter replace dev %s parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate %dkbit burst 18k drop flowid :1" % (iface, math.floor(dlRates[0]))) # introduce a PRIO queuewith policing to maximum capacity
                    
                # for the rest of nodes we create a config file and send it to them by SSH protocol
                elif node == dlEdgePosition:
                    remoteConfig = ConfigParser.ConfigParser()
                    remoteConfFile = open('/var/tmp/node-remote-initialization.conf', 'w')
                    remoteConfig.add_section('policing')
                    remoteConfig.set('policing', 'ingressIfaces', json.dumps(ulIfaces[1]+dlIfaces[1]))
                    remoteConfig.set('policing', 'limit', ([ulRates[1]]*len(ulIfaces[1])+([dlRates[1]]*len(dlIfaces[1]))))
                    remoteConfig.write(remoteConfFile)
                    remoteConfFile.close()
                    ssh = self.createSSHClient(nodes[node])
                    scp = SCPClient(ssh.get_transport())
                    scp.put('/var/tmp/node-remote-initialization.conf', '/var/tmp/node-UL.conf')
       

    def createSSHClient(self, server):
        logger.info('connecting to %s...' % server)
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
    #        for i, iface in enumerate(json.loads(config.get('policing', 'ingressIfaces'))):
    #            logger.info("cleaning ingress policing on interface %s" % iface)
    #            os.system("tc qdisc del dev %s ingress" % iface) # preventive ingress cleaning

    daemon_runner = runner.DaemonRunner(daemon)
    #This ensures that the logger file handle does not get closed during daemonization
    daemon_runner.daemon_context.files_preserve=[handler.stream]
    daemon_runner.do_action()
