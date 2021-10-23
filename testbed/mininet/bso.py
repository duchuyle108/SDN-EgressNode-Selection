from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.link import TCLink, TCULink, OVSLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

import time

def bso():
    net = Mininet(controller=RemoteController, link=TCULink)

    node_num = 14

    # Create switches
    for i in range(1, node_num + 1):
        net.addSwitch('s%d' %i)

    # Create nodes
    for i in range(1, node_num + 1):
        net.addHost('h%d' %i, ip = '10.0.0.%d' %i)

    print "*** Creating host-switch links"
    for i in range(1, node_num + 1):
        net.addLink('h%d'%i, 's%d' %i, bw=100)

    print "*** Creating switch-switch links"
    link_from = [1,2,2,2,2,2,3,3,5,7,8,8,9,9,10,11,12,13]
    link_to =   [2,3,4,5,7,8,4,5,6,9,9,12,10,13,11,13,13,14]

    #create links between switches with bandwidth (bw)
    for lf, lt in zip(link_from, link_to):
        if lf == 1 and lt == 2: # link's capacity from sw1 to sw2 need to be larger to prevent bottle necks
            net.addLink('s%d' % int(lf), 's%d' % int(lt), bw=41)
        elif (lf == 2 and lt == 7) or (lf == 7 and lt == 9) or (lf == 9 and lt == 13):
            net.addLink('s%d' % int(lf), 's%d' % int(lt), bw=20)
        else:
            net.addLink('s%d' % int(lf), 's%d' % int(lt), bw=10)
    # Add Controllers
    c0 = net.addController( 'c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    net.start()
    CLI( net )

    for host in net.hosts:
        print(host)
    net.stop()

if __name__ == '__main__':
    setLogLevel( 'info' )
    bso()