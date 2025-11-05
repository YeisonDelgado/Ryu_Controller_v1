from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event, switches
from ryu.app.wsgi import ControllerBase, WSGIApplication
from ryu.topology.api import get_all_link, get_all_switch, get_all_host
import networkx as nx
import json

DEFAULT_BW = 100.0


class RoutingApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(RoutingApp, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()
        self.hosts = {}  # mac -> {dpid, port, ip}
        self.switches = set()
        self.mode = "dijkstra_bw"  # or 'shortest_hops'

        wsgi = kwargs['wsgi']
        mapper = wsgi.mapper
        wsgi.register(RoutingController, {'app': self})

    @set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        sw = ev.switch
        dpid = sw.dp.id
        self.logger.info(f"Switch enter: {dpid}")
        self.switches.add(dpid)
        self.net.add_node(dpid, type='switch')

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        for link in ev.link:
            src = link.src.dpid
            dst = link.dst.dpid
            bw = getattr(link, 'bw', DEFAULT_BW)
            if bw is None:
                bw = DEFAULT_BW
            weight = 1.0 / float(bw) if float(bw) > 0 else 1.0
            self.net.add_edge(src, dst, weight=weight, bw=bw)
            self.net.add_edge(dst, src, weight=weight, bw=bw)
            self.logger.info(f"Link added: {src} <-> {dst} bw={bw}")

    @set_ev_cls(event.EventHostAdd)
    def host_add_handler(self, ev):
        host = ev.host
        mac = host.mac
        if not host.port:
            return
        dpid = host.port.dpid
        port = host.port.port_no
        ip = host.ipv4[0] if host.ipv4 else None
        self.hosts[mac] = {'dpid': dpid, 'port': port, 'ip': ip}
        host_node = f"host-{mac}"
        self.net.add_node(host_node, type='host', mac=mac, ip=ip)
        # Connect host to switch in graph
        self.net.add_edge(host_node, dpid, weight=0)
        self.net.add_edge(dpid, host_node, weight=0)
        self.logger.info(f"Host added: {mac} at {dpid}:{port} ip={ip}")

    def compute_paths(self):
        # Build routing for each pair of hosts
        routes = {}
        host_nodes = [n for n, d in self.net.nodes(data=True) if d.get('type') == 'host']
        for i in range(len(host_nodes)):
            for j in range(i + 1, len(host_nodes)):
                src = host_nodes[i]
                dst = host_nodes[j]
                try:
                    if self.mode == 'dijkstra_bw':
                        path = nx.shortest_path(self.net, src, dst, weight='weight')
                    else:
                        # For hop count, treat each edge weight as 1
                        path = nx.shortest_path(self.net, src, dst, weight=lambda u, v, d: 1)
                    routes[(src, dst)] = path
                except Exception as e:
                    self.logger.warning(f"No path {src}->{dst}: {e}")
        return routes

    def install_proactive_flows(self):
        routes = self.compute_paths()
        # For each route, install flows on switches along the path
        for (src, dst), path in routes.items():
            # host nodes look like 'host-<mac>'
            if not path:
                continue
            # convert host to attachment switch and ip if available
            # iterate path and install simple L2 forwarding based on dst MAC
            dst_mac = self.net.nodes[dst].get('mac')
            for idx in range(1, len(path)-1):
                sw = path[idx]
                next_hop = path[idx+1]
                # find output port towards next_hop
                out_port = self._port_to_neighbor(sw, next_hop)
                if out_port is None:
                    continue
                # send flow mod to switch
                self._add_flow_to_switch(sw, dst_mac, out_port)

    def _port_to_neighbor(self, dpid, neighbor):
        # Try to find port number by inspecting switches list via topology API
        # This is a best-effort placeholder; real implementation should map ports from link info
        # Return None if unknown
        return 1

    def _add_flow_to_switch(self, dpid, dst_mac, out_port, priority=100):
        # Placeholder: in a real implementation we would get Datapath object and send ofproto messages
        self.logger.info(f"Install flow on {dpid}: dst_mac={dst_mac} -> out_port={out_port}")


class RoutingController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RoutingController, self).__init__(req, link, data, **config)
        self.app = data['app']

    def set_mode(self, req, **_kwargs):
        try:
            data = req.json if hasattr(req, 'json') else json.loads(req.body.decode('utf-8'))
        except Exception:
            data = {}
        mode = data.get('mode') if isinstance(data, dict) else None
        if mode not in ('dijkstra_bw', 'shortest_hops'):
            return (400, {}, json.dumps({'error': 'invalid mode'}))
        self.app.mode = mode
        # Recompute and install flows proactively
        self.app.install_proactive_flows()
        return (200, {}, json.dumps({'message': f'mode set to {mode}'}))

    def get_status(self, req, **_kwargs):
        routes = self.app.compute_paths()
        # return a compact summary
        summary = {f"{s}->{d}": p for (s, d), p in routes.items()}
        return (200, {}, json.dumps({'mode': self.app.mode, 'routes': summary}))

    # mapper binding
    @classmethod
    def register(cls, mapper):
        mapper.connect('set_mode', '/routing/mode', controller=cls, action='set_mode', conditions=dict(method=['POST']))
        mapper.connect('get_status', '/routing/status', controller=cls, action='get_status', conditions=dict(method=['GET']))
