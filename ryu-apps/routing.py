# This is a basic routing application used in the article:
#  "A Reinforcement Learning-Based Solution for Intra-Domain Egress Selection" 
#  Authors: Duc-Huy LE, Hai Anh TRAN
#  Conference: HPSR2021

# This application monitor collects topology information, calculates and preinstalls
# routing paths between each switches in the network. 

from ryu.base import app_manager
from ryu.controller import mac_to_port
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import arp
from ryu.lib.packet import ether_types
from ryu.lib import hub
from ryu.topology import event

from collections import defaultdict

import time

class simple_routing(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(simple_routing, self).__init__(*args, **kwargs)
        self.topology_api_app = self
        self.routing_thread = hub.spawn(self.main_routing)
        self.datapaths = {}
        self.switches = []
        self.adjacency = defaultdict(dict)
        self.routing_table = defaultdict(dict)
    
    # Main thread
    def main_routing(self):
        while True:
            hub.sleep(1)
            self.calculate_routing_table()
            if self.routing_table:
                for i in range(0,len(self.switches) - 1):
                    for j in range (i + 1, len(self.switches)):
                        src = self.switches[i].id
                        dst = self.switches[j].id
                        self.install_path(src,dst)
                        self.install_path(dst,src)
                break
            else:
                hub.sleep(4)
    
    # Get all possible path between src and dst switch
    def get_paths(self, src, dst):
        if src == dst:
            # host target is on the same switch
            return [[src]]
        paths = []
        stack = [(src, [src])]
        while stack:
            (node, path) = stack.pop()
            for next in set(self.adjacency[node].keys()) - set(path):
                if next is dst:
                    paths.append(path + [next])
                else:
                    stack.append((next, path + [next]))
        return paths
    
    # Get shortest path from src to dst sw
    def get_shortest_path(self, src, dst):
        paths = self.get_paths(src, dst)
        if not paths:
            return paths
        min = len(paths[0]) + 1
        shortest_path = []
        for path in paths:
            if len(path) < min:
                shortest_path = path
                min = len(path)
        return shortest_path

    # Calculate routing table with shortest path rule
    def calculate_routing_table(self):
        start_time = time.time()
        for i in range(0,len(self.switches) - 1):
            for j in range (i + 1, len(self.switches)):
                src = self.switches[i].id
                dst = self.switches[j].id
                path = self.get_shortest_path(src,dst)
                self.routing_table[src][dst] = path
                self.routing_table[dst][src] = path[::-1]
        elapsed_time = time.time() - start_time
        # self.logger.info('*****Routing table calculating time:' + str(elapsed_time))
        # self.logger.info(self.routing_table)
    
    # install routing rules in defined path between src and dst switch
    def install_path(self, src, dst):
        path = self.routing_table[src][dst]
        ports = []
        for s1, s2 in zip(path[:-1], path[1:]):
            ports.append(self.adjacency[s1][s2])
        ports.append(1)
        
        for i in range(len(path)):
            switch = path[i]
            out_port = ports[i]

            dp = self.datapaths[switch]
            ofp = dp.ofproto
            ofp_parser = dp.ofproto_parser

            match_ip = ofp_parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src = '10.0.0.' + str(src),
                ipv4_dst = '10.0.0.' + str(dst)
            )
            match_arp = ofp_parser.OFPMatch(
                eth_type=0x0806, 
                arp_spa='10.0.0.' + str(src), 
                arp_tpa='10.0.0.' + str(dst)
            )

            action = [ofp_parser.OFPActionOutput(out_port)]
            self.add_flow(dp, 65535, match_ip, action)
            self.add_flow(dp, 65535, match_arp, action)

    # Install a flow to a specific switch
    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst)
        datapath.send_msg(mod)

    # Handle switch connecting and disconnecting events  
    @set_ev_cls(ofp_event.EventOFPStateChange,[MAIN_DISPATCHER, DEAD_DISPATCHER])
    def switch_stat_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info('A switch connect - dpid: %016x', datapath.id)
                self.switches.append(datapath)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info('A switch has just disconnected - dpid: %016x', datapath.id)
                del self.datapaths[datapath.id]
                self.switches.remove(datapath)

    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def link_add_handler(self, ev):
        s1 = ev.link.src
        s2 = ev.link.dst
        self.adjacency[s1.dpid][s2.dpid] = s1.port_no
        self.adjacency[s2.dpid][s1.dpid] = s2.port_no
        # self.logger.info(self.adjacency)

    @set_ev_cls(event.EventLinkDelete, MAIN_DISPATCHER)
    def link_delete_handler(self, ev):
        s1 = ev.link.src
        s2 = ev.link.dst
        # Exception handling if switch already deleted
        try:
            del self.adjacency[s1.dpid][s2.dpid]
            del self.adjacency[s2.dpid][s1.dpid]
        except KeyError:
            pass

