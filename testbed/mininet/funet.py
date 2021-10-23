from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.link import TCLink, TCULink, OVSLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

import time

def bso():
    net = Mininet(controller=RemoteController, link=TCULink)

    node_num = 24

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
    link_from = [1,1,1,2,3,3,4,5,6,6,7,7,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23]
    link_to =   [3,21,23,23,4,6,5,7,7,10,8,9,13,11,12,13,14,15,16,17,18,19,20,21,22,23,24]

    #create links between switches with bandwidth (bw)
    for lf, lt in zip(link_from, link_to):
        if (lf == 1 and lt == 3) or (lf == 1 and lt == 23) or (lf == 1 and lt == 21) or (lf == 21 and lt == 20) or (lf == 20 and lt == 19) or (lf == 3 and lt == 6) or (lf == 6 and lt == 7) or (lf == 9 and lt == 13):
            net.addLink('s%d' % int(lf), 's%d' % int(lt), bw=30)
        else:
            net.addLink('s%d' % int(lf), 's%d' % int(lt), bw=15)
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