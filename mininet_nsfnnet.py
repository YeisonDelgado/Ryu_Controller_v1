"""
Mininet script to create a NSFNET-like topology.

Run on Linux (recommended) with Mininet installed.
Example:
  sudo python3 mininet_nsfnnet.py

Each switch will have one host attached (h1..h14). Links include bandwidth attributes (TCLink).
"""
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class NSFNetTopo(Topo):
    def build(self):
        # NSFNET core nodes (14) - simplified
        switches = {}
        for i in range(1, 15):
            sid = f's{i}'
            switches[i] = self.addSwitch(sid)

        # Attach one host per switch
        for i in range(1, 15):
            hid = f'h{i}'
            h = self.addHost(hid)
            self.addLink(h, switches[i], bw=100)

        # Define NSFNET-like links (undirected). Bandwidths are examples.
        edges = [
            (1,2,50),(1,3,50),(2,4,50),(3,4,50),(2,5,30),(4,6,30),
            (5,6,40),(5,7,20),(6,8,20),(7,9,30),(8,9,30),(8,10,40),
            (9,11,25),(10,11,25),(10,12,50),(11,13,50),(12,13,60),(12,14,60),(13,14,70)
        ]

        for a, b, bw in edges:
            self.addLink(switches[a], switches[b], bw=bw)


def run():
    topo = NSFNetTopo()
    # Use a remote controller (Ryu) on localhost:6653 (or change as needed)
    net = Mininet(topo=topo, link=TCLink, controller=None, switch=OVSKernelSwitch, autoSetMacs=True)
    c = RemoteController('c0', ip='127.0.0.1', port=6633)
    net.addController(c)
    net.start()
    info('*** Network started')
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run()
