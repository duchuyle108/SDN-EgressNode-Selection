# This is ryu application used in the article:
#  "A Reinforcement Learning-Based Solution for Intra-Domain Egress Selection" 
#  Authors: Duc-Huy LE, Hai Anh TRAN
#  Conference: HPSR2021

# This application periodically choose a new egressnode using one of the mentioned algorithms
# for the MAB problem and install new path for the external traffic.


from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4
from ryu.topology import event
from ryu.lib import hub

from decimal import *
import time
from collections import defaultdict

from mab import *

ETH_ADD_PREFIX = 'ff:ff:ff:ff:ff:'

# Manually setup the egressnode set
EGRESS_NODES = [4,6,11,12,14]
INGRESS_NODE = 1 #default ingress

OUTBOUND_SRC_IP = '11.0.0.1'
OUTBOUND_DST_IP = '11.0.0.2'

class enode_select(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(enode_select, self).__init__( *args, **kwargs)
        self.monitor_thread = hub.spawn(self.monitor)
        self.selecting_thread = hub.spawn(self.selecting)

        self.datapaths = {}
        self.switches = []
        self.adjacency = defaultdict(dict)
        self.routing_table = defaultdict(dict)

        self.current_egressnode = 0

        self.delay_start_time = defaultdict(dict)
        self.delay_end_time = defaultdict(dict)
        self.delay_status = defaultdict(dict)

        self.rx_flow_stats = defaultdict(dict)
        self.tx_flow_stats = defaultdict(dict)

    # Monitor and update routing table
    def monitor(self):
        hub.sleep(2)
        self.calculate_routing_table()
        while True:
            hub.sleep(60)
            self.calculate_routing_table()
    
    # Main thread, choose egress node using pre-defined algorithm
    def selecting(self):
        hub.sleep(3)
        # Import egress nodes into MAB actions
        action_list = []
        for node in EGRESS_NODES:
            action_list.append(Action(node))
        mab_model = SP_UCB2(action_list, len(action_list),0.1)
        self.logger.info(mab_model.actions)
        
        # Beginning phase, each egress node is chosen once
        for i in range(len(action_list)):
            enode = action_list[i].id
            self.change_egress_node(action_list[i].id)
            tx1, rx1 = self.get_path_stats(INGRESS_NODE, enode)
            hub.sleep(3)
            delays = []
            for j in xrange(10):
                delay = self.calculate_link_delay(INGRESS_NODE, enode)
                if delay != -1:
                    delays.append(delay)
                hub.sleep(1)
            mean_delay = float(sum(delays) / len(delays))
            tx2, rx2 = self.get_path_stats(INGRESS_NODE, enode)
            loss = self.calculate_loss(tx1,rx1,tx2,rx2)
            self.logger.info("DELAY: " + str(mean_delay))
            self.logger.info("LOSS: " + str(loss))
            reward = self.calculate_reward(loss, mean_delay)
            self.logger.info(reward)
            action_list[i].update(reward)

        with open('funet-light-reward.txt', 'a') as f:
            f.write('----------------Funet-Light-Network-------------------------- \n')
        round = 1
        while True:
            self.logger.info("*************************ROUND" + str(round) + "*****************")
            time_start = time.time()
            total_reward = []
            for timestep in xrange(20):
                enode = mab_model.choose_action()
                dpid = enode.id
                self.change_egress_node(dpid)
                hub.sleep(2)
                tx1, rx1 = self.get_path_stats(INGRESS_NODE, dpid)
                delays = []
                for j in xrange(20):
                    delay = self.calculate_link_delay(INGRESS_NODE, dpid)
                    if delay != -1:
                        delays.append(delay)
                    hub.sleep(5)
                mean_delay = float(sum(delays) / len(delays))
                tx2, rx2 = self.get_path_stats(INGRESS_NODE, dpid)
                loss = self.calculate_loss(tx1,rx1,tx2,rx2)
                self.logger.info("LOSS: " + str(loss))
                self.logger.info("DELAY: " + str(mean_delay))
                reward = self.calculate_reward(loss, mean_delay)
                enode.update(reward)
                total_reward.append(reward)
                self.logger.info("REWARD: " + str(reward))

            mean_reward = float(sum(total_reward) / len(total_reward))
            with open('funet-light-reward.txt', 'a') as f:
                f.write(str(mean_reward) + '\n')
            self.logger.info("Loop finished in " + str(time.time() - time_start) +"s")
            round += 1
            # Stop for 
            if round == 13:
                with open('funet-light-reward.txt', 'a') as f:
                    f.write(str(mab_model.actions) + '\n')
                break
    
    def change_egress_node(self, new_enode_dpid):
        self.logger.info("******** Change egressnode to switch: dpid: " + str(new_enode_dpid))
        if new_enode_dpid == self.current_egressnode:
            return
        if self.current_egressnode != 0:
            self.delete_path(INGRESS_NODE,self.current_egressnode)
        hub.sleep(0.5)
        self.current_egressnode = new_enode_dpid
        self.install_path(INGRESS_NODE, new_enode_dpid)
    
    # Install external path from src switch to dst switch
    def install_path(self, src, dst):
        if src != INGRESS_NODE or dst not in EGRESS_NODES:
            self.logger.info("!!!!WARNING: NOT RIGHT PATH INSTALL FUNCTION")
            return
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
                ipv4_src = OUTBOUND_SRC_IP,
                ipv4_dst = OUTBOUND_DST_IP
            )

            action = [ofp_parser.OFPActionOutput(out_port)]
            self.add_flow(dp, 65000, match_ip, action)

    # Delete an old path (when changing egress node)
    def delete_path(self, src, dst):
        if src != INGRESS_NODE or dst not in EGRESS_NODES:
            self.logger.info("!!!!WARNING: NOT RIGHT PATH DELETE FUNCTION")
            return
        old_path = self.routing_table[src][dst]
        for i in range(len(old_path)):
            switch = old_path[i]

            dp = self.datapaths[switch]
            ofp = dp.ofproto
            ofp_parser = dp.ofproto_parser

            match_ip = ofp_parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src = OUTBOUND_SRC_IP,
                ipv4_dst = OUTBOUND_DST_IP
            )

            self.delete_flow(dp, match_ip)

    # Reward function
    def calculate_reward(self, loss, delay):
        alpha = 150
        beta = 25
        return 11 - alpha * loss - beta * delay / 100
    
    # Get flow statistics of a path
    def get_path_stats(self, src, dst):
        dp_src = self.datapaths[src]
        parser = dp_src.ofproto_parser

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src = '10.0.0.' + str(src),
            ipv4_dst = '10.0.0.' + str(dst)
        )

        self.request_stats(src,match)
        self.request_stats(dst,match)
        hub.sleep(1.5)
        tx = self.tx_flow_stats[src][dst]
        rx = self.rx_flow_stats[src][dst]
        return tx, rx

    # Loss calculating function
    def calculate_loss(self, tx1, rx1, tx2, rx2):
        tx_diff = tx2 - tx1
        rx_diff = rx2 - rx1
        loss = (1.0 - float(rx_diff) / tx_diff) if tx_diff > 0 else 0
        return max(0,loss)

    def calculate_link_delay(self, src, dst):
        eth_src = ETH_ADD_PREFIX + str(src)
        eth_dst = ETH_ADD_PREFIX + str(dst)
        pkt = DelayPacket.delay_packet(eth_src,eth_dst)
        self.install_delay_path(src, dst)
        self.delay_status[src][dst] = 0
        path = self.routing_table[src][dst]
        out_port = self.adjacency[src][path[1]]

        dp = self.datapaths[src]
        ofproto = dp.ofproto
        parser = dp.ofproto_parser

        action = [parser.OFPActionOutput(out_port)]
        msg = parser.OFPPacketOut(
            datapath=dp, in_port=ofproto.OFPP_CONTROLLER,
            buffer_id=ofproto.OFP_NO_BUFFER,actions = action, data=pkt
        )
        hub.sleep(0.5)
        self.delay_start_time[src][dst] = Decimal(time.time())
        dp.send_msg(msg)
        hub.sleep(1)
        if not self.delay_status[src][dst]:
            self.delay_status[src][dst] = 1
            return -1

        delay = self.delay_end_time[src][dst] - self.delay_start_time[src][dst]
        self.delete_delay_path(src, dst)
        return delay * 1000

    # Install delay packet forwarding in a specific path    
    def install_delay_path(self, src, dst):
        path = self.routing_table[src][dst]        
        ports = []
        for s1, s2 in zip(path[:-1], path[1:]):
            ports.append(self.adjacency[s1][s2])
        ports.append(1)

        if len(path) > 2 :
            for i in range(1, len(path) - 1):
                switch = path[i]
                out_port = ports[i]

                dp = self.datapaths[switch]
                ofp = dp.ofproto
                ofp_parser = dp.ofproto_parser
                if dst < 10:
                    match = ofp_parser.OFPMatch(
                        eth_type = DelayPacket.DELAY_ETH_TYPE, 
                        eth_src = ETH_ADD_PREFIX + '0' + str(src), 
                        eth_dst = ETH_ADD_PREFIX + '0' + str(dst)
                    )
                else:
                    match = ofp_parser.OFPMatch(
                        eth_type = DelayPacket.DELAY_ETH_TYPE, 
                        eth_src = ETH_ADD_PREFIX + str(src), 
                        eth_dst = ETH_ADD_PREFIX + str(dst)
                    )

                action = [ofp_parser.OFPActionOutput(out_port)]
                self.add_flow(dp, 1, match, action)
                self.add_flow(dp, 1, match, action)

        delay_dst_sw = self.datapaths[dst]
        ofp = delay_dst_sw.ofproto
        ofp_parser = delay_dst_sw.ofproto_parser
        match = ofp_parser.OFPMatch(
            eth_type = DelayPacket.DELAY_ETH_TYPE, 
            eth_src = ETH_ADD_PREFIX + str(src), 
            eth_dst = ETH_ADD_PREFIX + str(dst)
        )
        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_CONTROLLER)]
        self.add_flow(delay_dst_sw, 1, match, actions)
    
    def delete_delay_path(self, src, dst):
        path = self.routing_table[src][dst]
        for i in range(len(path)):
                switch = path[i]
                dp = self.datapaths[switch]
                ofp_parser = dp.ofproto_parser

                match = ofp_parser.OFPMatch(
                    eth_type = DelayPacket.DELAY_ETH_TYPE, 
                    eth_src = ETH_ADD_PREFIX + str(src), 
                    eth_dst = ETH_ADD_PREFIX + str(dst)
                )
                self.delete_flow(dp, match)
    
    def delete_flow(self, datapath, match):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        command = ofproto.OFPFC_DELETE

        msg = parser.OFPFlowMod(datapath=datapath, match = match, command = command,
                                out_port = ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY)
        datapath.send_msg(msg)

    def add_flow(self, datapath, priority, match, actions):
        # print "Adding flow ", match, actions
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]

        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    # Handle delay packet
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev): 
        rx_time = Decimal(time.time())
        data = ev.msg.data
        pkt = packet.Packet(data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype != DelayPacket.DELAY_ETH_TYPE:
            return
        
        eth_src = eth.src
        eth_dst = eth.dst
        sw_src = int(eth_src.split(':')[-1])
        sw_dst = int(eth_dst.split(':')[-1])

        dp = ev.msg.datapath
        if dp.id == sw_dst:
            self.delay_end_time[sw_src][sw_dst] = rx_time
            self.delay_status[sw_src][sw_dst] = 1

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
    
    def get_optimal_path(self, src, dst):
        paths = self.get_paths(src, dst)
        if not paths:
            return paths
        min = len(paths[0]) + 1
        optimal_path = []
        for path in paths:
            if len(path) < min:
                optimal_path = path
                min = len(path)
        return optimal_path

    def calculate_routing_table(self):
        start_time = time.time()
        for i in range(0,len(self.switches) - 1):
            for j in range (i + 1, len(self.switches)):
                src = self.switches[i].id
                dst = self.switches[j].id
                path = self.get_optimal_path(src,dst)
                self.routing_table[src][dst] = path
                self.routing_table[dst][src] = path[::-1]
        elapsed_time = time.time() - start_time
        self.logger.info('*****Routing table calculating time:' + str(elapsed_time))

    def request_stats(self, dpid, match):
        dp = self.datapaths[dpid]
        parser = dp.ofproto_parser

        msg = parser.OFPFlowStatsRequest(dp,match = match)
        dp.send_msg(msg)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def handle_port_stat_reply(self, ev):
        msg = ev.msg
        dp = msg.datapath
        body = msg.body
        for stat in body:
            src_ip = stat.match.get('ipv4_src')
            src_dpid = int(src_ip.split('.')[-1])
            dst_ip = stat.match.get('ipv4_dst')
            dst_dpid = int(dst_ip.split('.')[-1])
            if dp.id == src_dpid:
                self.tx_flow_stats[src_dpid][dst_dpid] = stat.packet_count
            if dp.id == dst_dpid:
                self.rx_flow_stats[src_dpid][dst_dpid] = stat.packet_count
        
    @set_ev_cls(ofp_event.EventOFPStateChange,[MAIN_DISPATCHER, DEAD_DISPATCHER])
    def switch_stat_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                # self.logger.info('A switch connect - dpid: %016x', datapath.id)
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

# Customized packet used to calculating delay
class DelayPacket(object):
    DELAY_ETH_TYPE = 0x7777

    @staticmethod
    def delay_packet(eth_src, eth_dst, payload = ''):
        # pkt = packet.Packet(data=payload)
        pkt = packet.Packet()

        ethernet_pkt = ethernet.ethernet(dst=eth_dst, src=eth_src,
                                        ethertype=DelayPacket.DELAY_ETH_TYPE)
        pkt.add_protocol(ethernet_pkt)
        ip_pk = ipv4.ipv4()
        pkt.add_protocol(ip_pk)
        pkt.serialize()

        return pkt.data

