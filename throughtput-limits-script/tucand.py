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
import subprocess
import paramiko
import math
import operator
import time
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
        self.stderr_path = join(TUCANLogFolder, 'tucandaemon.err') # '/dev/tty' for debugging
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
            self.updateIngressConfFiles(initialize=True)
        if config.getboolean('rol', 'edge'):
            for sense in ['UL', 'DL']:
                if isfile('/var/tmp/node-%s.conf' % sense):
                    self.updateIngress('/var/tmp/node-%s.conf' % sense, initialize=True)
        # if we have to configure egress queues, we do it
        if (isfile('/etc/TUCAN3G/node-egress.conf')):
            self.updateEgress('/etc/TUCAN3G/node-egress.conf')
        # nodes and gateways to hnbs from conf file
        hnbGateways = json.loads(config.get('hnbs', 'hnbGateways'))
        nodes = json.loads(config.get('algorithms', 'nodes'))

        ulMins = json.loads(config.get('algorithms', 'initialULMin'))
        ulMinSum = 0
        for minTraffic in ulMins:
            ulMinSum += sum(minTraffic)
        
        dlMins = json.loads(config.get('algorithms', 'initialDLMin'))
        dlMinSum = 0
        for minTraffic in dlMins:
            dlMinSum += sum(minTraffic)

        # Main loop 
        while True:
            # if there's a configuration order from an edge node, we follow it
            for sense in ['UL', 'DL']:
                if isfile('/var/tmp/node-%s.conf' % sense):
                    self.updateIngress('/var/tmp/node-%s.conf' % sense)
            # algorithms
            if config.getboolean('rol', 'edge'):
                for hnbIndex, hnb in enumerate(hnbGateways):
                    self.parseBytesFromIface(config.get('rol', 'edgeType'), hnbIndex)
                if config.get('rol', 'edgeType') == 'UL':
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
                            minMargin = capacity - (ulMinSum + dlMinSum)
                            logger.info('Mean Dynamic Capacity: %f' % self.registers.getAverage('dynamicCapacity', key))

                            # Effective margin calculus
                            previouslyAdmittedTraffic = 0.0
                            for hnbNumber, hnb in enumerate(hnbGateways):
                                for senses in ['UL', 'DL']:
                                    previouslyAdmittedTraffic += self.registers.last('%sLimits' % sense, hnbNumber)
                            effectiveMargin = capacity - previouslyAdmittedTraffic 

                            # Link margin calculus
                            linkMargin = min([minMargin, effectiveMargin])

                            # Traffic flux margins
                            # In a network, the most close to the UL edge
                            for hnbIndex, hnb in enumerate(hnbGateways):
                                for sense, mins in zip(['UL', 'DL'], [reduce(operator.add, ulMins), reduce(operator.add, dlMins)]):
                                    logger.info('mins: %s -- mins[hnbIndex]: %s -- ulMinSum+dlMinSum: %s' % (mins, mins[hnbIndex], ulMinSum+dlMinSum))
                                    self.registers.add('flux%smargin' % sense, hnbIndex, mins[hnbIndex]/(ulMinSum+dlMinSum))

                                    logger.info('Minimums margin: %f -- Effective margin: %f -- Link margin: %f -- %s: %f ' % (minMargin, effectiveMargin, linkMargin, 'flux%smargin' % sense, self.registers.last('flux%smargin' % sense, hnbIndex)))
                                    
                                    # Get traffic hitting interface before ingress
                                    uldlMin = mins[hnbIndex]
                                    tic = self.registers.last('%sTimestamp' % sense, hnbIndex)
                                    ticBytes = self.registers.last('%sBytes' % sense, hnbIndex)
                                    toc, tocBytes = self.getTimeBytesFromFile('/var/tmp/bytes-time-%s-%d.conf' % (sense, hnbIndex), sense, hnbIndex)
                                    logger.info('TIME: TIC %f TOC %f -- BYTES: TIC %d TOC %d' % (tic, toc, ticBytes, tocBytes))
                                    delta = toc-tic
                                    deltaBytes = tocBytes - ticBytes
                                    logger.info('adding %d bytes and %f seconds' % (toc, tocBytes))
                                    self.registers.add('%sTimestamp' % sense, hnbIndex, toc)
                                    self.registers.add('%sBytes' % sense, hnbIndex, tocBytes)
                                    # prevent division by zero
                                    if delta == 0.0:
                                        throughput = 0
                                    else:
                                        throughput = ((deltaBytes*8)/1000)/delta # (in kbps)
                                    logger.info('throughput hitting external interface: %s' % throughput)

                                    # Allowed traffics
                                    traffic = self.getAdmitted(self.registers.last('%sLimits' % sense, hnbIndex),  uldlMin, self.registers.last('flux%smargin' % sense, hnbIndex), beta, throughput)
                                    self.registers.add('%sLimits' % sense, hnbIndex, traffic)
       
                                    logger.info('Allowed %s traffic for %s: %f' % (sense, hnb, self.registers.last('%sLimits' % sense, hnbIndex)))
    
                            # Create ingress configuration files and send to DL edge
                            self.updateIngressConfFiles()
 
            time.sleep(10)

    
    def parseBytesFromIface(self, sense, hnbIndex):
        logger.info('getting time and bytes for sense: %s -- hnb: %s' % (sense, hnbIndex))
        bytesTimeConfig = ConfigParser.ConfigParser()
        bytesTimeConfFile = open('/var/tmp/bytes-time-%s-%d.conf' % (sense, hnbIndex), 'w')
        bytesTimeConfig.add_section('snapshot')
        ifbIfaces = []
        htbQueues = []
        edge = config.get('rol', 'edgeType')
        if  edge == 'UL':
            htbQueues = json.loads(config.get('hnbs', 'ulHtbQueues'))
            ifbIfaces = json.loads(config.get('hnbs', 'ulIfbIfaces'))
        else:
            htbQueues = json.loads(config.get('hnbs', 'dlHtbQueues'))
            ifbIfaces = json.loads(config.get('hnbs', 'dlIfbIfaces'))
        logger.info('htbQueues: %s -- ifbIfaces: %s' % (htbQueues, ifbIfaces))

        timeStamps = []
        ifaceBytes = []
        Pos = 0
        for hnbIter, hnb in enumerate(ifbIfaces):
            timeStampsIface = []
            ifaceBytesIface = []
            for ifaceIndex, iface in enumerate(hnb):
                output = subprocess.check_output('tc -s -d class show dev %s' % iface, shell=True)
                timeStamp = time.time()
                logger.info('Timestamp from iface %s: %f seconds' % (iface, timeStamp))
                queue = ''
                for row in output.split('\n'):
                    if queue != '':
                        ifaceByte = row.split(' ')[2]
                        logger.info('timeStamp: %s -- ifaceBytes: %s' % (timeStamp, ifaceByte))
                        timeStampsIface.append(timeStamp)
                        ifaceBytesIface.append(ifaceByte)
                        queue = ''
                    if 'class' in row:
                        queue = row.split(' ')[2]
                        if (hnb[ifaceIndex], queue) not in self.getCombinations(ifbIfaces, htbQueues):
                            queue = ''
                timeStamps += [timeStampsIface]
                ifaceBytes += [ifaceBytesIface]
        logger.info('ifbIfaces: %s' % ifbIfaces)
        logger.info('htbQueues: %s' % htbQueues)
        logger.info('timeStamps: %s' % timeStamps)
        logger.info('ifaceBytes: %s' % ifaceBytes)
        
        bytesTimeConfig.set('snapshot', 'ifbIfaces', json.dumps(ifbIfaces))
        bytesTimeConfig.set('snapshot', 'htbQueues', json.dumps(htbQueues))
        bytesTimeConfig.set('snapshot', 'timeStamps', json.dumps(timeStamps))
        bytesTimeConfig.set('snapshot', 'ifaceBytes', json.dumps(ifaceBytes))
        bytesTimeConfig.write(bytesTimeConfFile)
        bytesTimeConfFile.close()

        if edge == 'DL':
            nodes = json.loads(config.get('algorithms', 'nodes'))
            ssh = self.createSSHClient(nodes[0])
            scp = SCPClient(ssh.get_transport())
            scp.put('/var/tmp/bytes-time-%s-%d.conf' % (sense, hnbIndex), '/var/tmp/bytes-time-%s-%d.conf' % (sense, hnbIndex))


    def getCombinations(self, list1, list2):
        combinations=[]
        for index, elem in enumerate(list1):
            combinations+=list(itertools.product(*[elem, list2[index]]))
        return combinations


    def getTimeBytesFromFile(self, filePath, sense, hnbIndex):
        if not isfile(filePath):
            return 0,0
        updateConfig = ConfigParser.ConfigParser() 
        updateConfig.read(filePath)
        ifbIfaces = json.loads(updateConfig.get('snapshot', 'ifbIfaces'))
        htbQueues = json.loads(updateConfig.get('snapshot', 'htbQueues'))
        timeStamps = json.loads(updateConfig.get('snapshot', 'timeStamps'))
        ifaceBytes = json.loads(updateConfig.get('snapshot', 'ifaceBytes'))
        logger.info('getTimeBytes ifbIfaces: %s' % ifbIfaces)
        logger.info('getTimeBytes htbQueues: %s' % htbQueues)
        logger.info('getTimeBytes timeStamps: %s' % timeStamps)
        logger.info('getTimeBytes ifaceBytes: %s' % ifaceBytes)

        return float(reduce(operator.add, timeStamps)[hnbIndex]), int(reduce(operator.add, ifaceBytes)[hnbIndex])



    def updateIngressConfFiles(self, initialize=False):
        # Some needed vars
        nodes = json.loads(config.get('hnbs', 'hnbGateways'))
        hnbNetworks = json.loads(config.get('hnbs', 'hnbNetworks'))

        ulIfaces = json.loads(config.get('hnbs', 'ulIfaces'))
        ulIfbIfaces = json.loads(config.get('hnbs', 'ulIfbIfaces'))
        ulHtbQueues = json.loads(config.get('hnbs', 'ulHtbQueues'))
        ulMarks = json.loads(config.get('hnbs', 'ulMarks'))
        ulRates = []
        if initialize:
            ulRates = json.loads(config.get('algorithms', 'initialULMin'))
        else:
            hnbPos = 0
            for ifaceIndex, ifbIface in enumerate(ulIfbIfaces):
                limits = []
                for htbQueueIndex, htbQueue in enumerate(ulHtbQueues[ifaceIndex]):
                    limits.append(self.registers.last('ULLimits', hnbPos))
                    hnbPos+=1
                ulRates.append(limits)

        dlIfaces = json.loads(config.get('hnbs', 'dlIfaces'))
        dlIfbIfaces = json.loads(config.get('hnbs', 'dlIfbIfaces'))
        dlHtbQueues = json.loads(config.get('hnbs', 'dlHtbQueues'))
        dlMarks = json.loads(config.get('hnbs', 'dlMarks'))
        dlRates = []
        if initialize:
            dlRates = json.loads(config.get('algorithms', 'initialDLMin'))
        else:
            hnbPos = 0
            for ifaceIndex, ifbIface in enumerate(dlIfbIfaces):
                limits = []
                for htbQueueIndex, htbQueue in enumerate(dlHtbQueues[ifaceIndex]):
                    limits.append(self.registers.last('DLLimits', hnbPos))
                    hnbPos+=1
                dlRates.append(limits)
            

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
            htbQueuesToWrite = []
            for queues in htbQueues:
                htbQueuesToWrite += [queues]
            logger.info('htb queues to write %s' % htbQueuesToWrite)
            remoteConfig.set('policing', 'htbQueues', json.dumps(htbQueuesToWrite))

            # marks
            remoteConfig.set('policing', 'marks', json.dumps(marks))

            # networks
            networksToWrite = reduce(operator.add, hnbNetworks)
            logger.info('networks to write %s' % networksToWrite)
            remoteConfig.set('policing', 'hnbNetworks', json.dumps(networksToWrite))
            
            # limits
            logger.info('rates: %s' % rates)
            remoteConfig.set('policing', 'limit', json.dumps(rates))
            # limits
            remoteConfig.write(remoteConfFile)
            remoteConfFile.close()

        ssh = self.createSSHClient(nodes[1])
        scp = SCPClient(ssh.get_transport())
        scp.put('/var/tmp/node-DL-remote.conf', '/var/tmp/node-UL.conf')
       

    def getAdmitted(self, previousAdmitted, minTraffic, margin, beta, interfaceTraffic):
        previousAdmitted = float(previousAdmitted)
        minTraffic = float(minTraffic)
        margin = float(margin)
        beta = float(beta)
        allowedTraffic = 0
        if not config.getboolean('algorithms', 'altFormula'):
            logger.info('prev: %f -- min: %f -- margin: %f -- beta: %f' % (previousAdmitted, minTraffic, margin, beta))
            allowedTraffic = max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0])
        else:
            allowedTraffic = min([max([previousAdmitted, minTraffic]) + margin - max([beta * (previousAdmitted - minTraffic),0]), max([interfaceTraffic, minTraffic])])
        if allowedTraffic < 10: # To avoid blocking the interface, we don't allow less than 10kbps
            allowedTraffic = 10
        return allowedTraffic


    def updateIngress(self, confPath, initialize=False):
        updateConfig = ConfigParser.ConfigParser()
        updateConfig.read(confPath)
        limits = json.loads(updateConfig.get('policing', 'limit'))
        ifaces = json.loads(updateConfig.get('policing', 'ingressIfaces'))
        ifbIfaces = json.loads(updateConfig.get('policing', 'ifbIfaces'))
        htbQueues = json.loads(updateConfig.get('policing', 'htbQueues'))
        marks = json.loads(updateConfig.get('policing', 'marks'))
        hnbNetworks = json.loads(updateConfig.get('policing', 'hnbNetworks'))
        logger.info("reading %s file" % confPath)

        # this controls if tc commands must add the rules or simply change previous one
        action = 'change'
        if initialize:
            action = 'add'
        # this controls that filter matching hnb networks search in the appropiate ip field
        field = 'dst'
        if config.get('rol', 'edgeType') == 'DL':
            field = 'src'
        # this sets the maximum rate allowed for each
        ceil = []
        for ifbIfacesIndex, ifbIface in enumerate(ifbIfaces):
            ceil.append(float(sum(limits[ifbIfacesIndex])))
            

        if initialize:        
            os.system("iptables -t mangle -F") 
            logger.info("iptables -t mangle -F") 
            os.system("iptables -t mangle -X QOS") 
            logger.info("iptables -t mangle -X QOS") 
            os.system("iptables -t mangle -N QOS")
            logger.info("iptables -t mangle -N QOS")
            os.system("iptables -t mangle -A QOS -j CONNMARK --restore-mark")
            logger.info("iptables -t mangle -A QOS -j CONNMARK --restore-mark")
        for ifaceNumber, iface in enumerate(ifaces):
            if initialize:
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
                # preventively we set the ingress interface up
                os.system("ip link set dev %s up" % ifbIfaces[ifaceNumber])
                logger.info("ip link set dev %s up" % ifbIfaces[ifaceNumber])
                # parent HTB default traffic to 3:31
                os.system("tc qdisc add dev %s root handle 3: htb default 31" % ifbIfaces[ifaceNumber])
                logger.info("tc qdisc add dev %s root handle 2: htb default 31" % ifbIfaces[ifaceNumber])

            # add or change queues traffic limit
            os.system("tc class %s dev %s parent 3: classid 3:3 htb rate %dkbit" % (action, ifbIfaces[ifaceNumber], math.floor(ceil[ifaceNumber])))
            logger.info("tc class %s dev %s parent 3: classid 3:3 htb rate %dkbit" % (action, ifbIfaces[ifaceNumber], math.floor(ceil[ifaceNumber])))
            # HTB 3:31 to receive default traffic
            os.system("tc class %s dev %s parent 3:3 classid 3:31 htb rate 10kbit ceil %dkbit" % (action, ifbIfaces[ifaceNumber], math.floor(ceil[ifaceNumber])))
            logger.info("tc class %s dev %s parent 3:3 classid 3:31 htb rate 10kbit ceil %dkbit" % (action, ifbIfaces[ifaceNumber], math.floor(ceil[ifaceNumber])))
                

            # per-HNB queues
            for queueNumber, queue in enumerate(htbQueues[ifaceNumber]):
                logger.info('setting iface %s -- ifbIface %s -- queue %s -- network %s' % (iface, ifbIfaces[ifaceNumber], queue, hnbNetworks[queueNumber]))
                os.system("tc class %s dev %s parent 3:3 classid %s htb rate %dkbit ceil %dkbit" % (action, ifbIfaces[ifaceNumber], queue, math.floor(float(limits[ifaceNumber][queueNumber])), math.floor(ceil[ifaceNumber])))
                logger.info("tc class %s dev %s parent 3:3 classid %s htb rate %dkbit ceil %dkbit" % (action, ifbIfaces[ifaceNumber], queue, math.floor(float(limits[ifaceNumber][queueNumber])), math.floor(ceil[ifaceNumber])))
                if initialize:
                    os.system("tc filter add dev %s parent 3:0 protocol ip handle %s fw flowid %s" % (ifbIfaces[ifaceNumber], marks[ifaceNumber][queueNumber], queue))
                    logger.info("tc filter add dev %s parent 3:0 protocol ip handle %s fw flowid %s" % (ifbIfaces[ifaceNumber], marks[ifaceNumber][queueNumber], queue))
                    os.system("tc filter add dev %s parent 3:0 protocol ip prio 1 u32 match ip %s %s flowid %s" % (ifbIfaces[ifaceNumber], field, hnbNetworks[queueNumber], queue))
                    logger.info("tc filter add dev %s parent 3:0 protocol ip prio 1 u32 match ip %s %s flowid %s" % (ifbIfaces[ifaceNumber], field, hnbNetworks[queueNumber], queue))
                    os.system("iptables -t mangle -A QOS -s %s -m mark --mark 0 -j MARK --set-mark %s" % (hnbNetworks[queueNumber], marks[ifaceNumber][queueNumber]))
                    logger.info("iptables -t mangle -A QOS -s %s -m mark --mark 0 -j MARK --set-mark %s" % (hnbNetworks[queueNumber], marks[ifaceNumber][queueNumber]))
            if initialize:
                os.system("tc filter add dev %s parent ffff: protocol ip u32 match u32 0 0 action xt -j CONNMARK --restore-mark action mirred egress redirect dev %s flowid ffff:1" % (iface, ifbIfaces[ifaceNumber]))
                logger.info("tc filter add dev %s parent ffff: protocol ip u32 match u32 0 0 action xt -j CONNMARK --restore-mark action mirred egress redirect dev %s flowid ffff:1" % (iface, ifbIfaces[ifaceNumber]))
        if initialize:
            os.system("iptables -t mangle -A QOS -j CONNMARK --save-mark")
            logger.info("iptables -t mangle -A QOS -j CONNMARK --save-mark")


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
