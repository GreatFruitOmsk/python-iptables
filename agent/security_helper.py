import iptc
import psutil
import socket
from xml.etree import ElementTree as ET
from sh import nmap


def nmap_scan(target):
    """
    Performs an nmap portscan against the
    target on all TCP/UDP ports.
    """
    try:
        scan = nmap([target, '-sS', '-sU', '-oX', '-'])
    except:
        return []
    dom = ET.fromstring(scan.stdout)
    result = []

    for dhost in dom.findall('host'):
        host = dhost.find('address').get('addr')
        for dport in dhost.findall('ports/port'):
            proto = dport.get('protocol')
            port = int(dport.get('portid'))
            state = dport.find('state').get('state')

            result.append({
                'host': host,
                'proto': proto,
                'port': port,
                'state': state
            })
    return result


def is_firewall_enabled():
    """Check if FILTER INPUT chain contains any rule"""
    try:
        chain = iptc.Chain(iptc.Table(iptc.Table.FILTER), "INPUT")
        return len(chain.rules) > 0
    except iptc.ip4tc.IPTCError:
        print('IPTC ERROR')
        return False


def netstat_scan():
    """
    Returns all open inet connections with their addresses and PIDs.
    """
    connections = psutil.net_connections(kind='inet')
    return [{
        'ip_version': 4 if c.family == socket.AF_INET else 6,
        'type': 'udp' if c.type == socket.SOCK_DGRAM else 'tcp',
        'local_address': c.laddr,
        'remote_address': c.raddr,
        'status': c.status if c.type == socket.SOCK_STREAM else None,
        'pid': c.pid
    } for c in connections]


def process_scan():
    processes = []
    for proc in psutil.process_iter():
        try:
            processes.append(proc.as_dict(attrs=[
                'pid', 'name', 'cmdline', 'username'
            ]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return processes


def is_app_armor_enabled():
    """
    Returns a True/False if AppArmor is enabled.
    """
    try:
        from sh import aa_status
    except ImportError:
        return False

    # Returns 0 if enabled and 1 if disable
    get_aa_status = aa_status(['--enabled'], _ok_code=[0, 1]).exit_code
    if get_aa_status == 1:
        return False
    return True


def selinux_status():
    """
    Returns a dict as similar to:
        {'enabled': False, 'mode': 'enforcing'}
    """
    selinux_enabled = None
    selinux_mode = None

    try:
        from sh import sestatus
    except ImportError:
        return {'enabled': False}

    # Manually parse out the output for SELinux status
    for line in sestatus().stdout.split(b'\n'):
        row = line.split(b':')

        if row[0].startswith(b'SELinux status'):
            selinux_enabled = row[1].strip() == b'enabled'

        if row[0].startswith(b'Current mode'):
            selinux_mode = row[1].strip()

    return {'enabled': selinux_enabled, 'mode': selinux_mode}


TABLE = 'filter'
DROP_CHAIN = 'WOTT_LOG_DROP'
OUTPUT_CHAIN = 'OUTPUT'
INPUT_CHAIN = 'INPUT'
WOTT_COMMENT = { 'comment': 'added by WoTT' }


def prepare_iptables():
    if not iptc.easy.has_chain(TABLE, DROP_CHAIN):
        iptc.easy.add_chain(TABLE, DROP_CHAIN)
        iptc.easy.add_rule(TABLE, DROP_CHAIN, {'target': {'LOG': {'log-prefix': 'DROP: ', 'log-level': '3'}}})
        iptc.easy.add_rule(TABLE, DROP_CHAIN, {'target': 'DROP'})


def update_iptables(table, chain, rules):
    existing = iptc.easy.dump_chain(table, chain)
    for r in existing:
        if r.get('comment', None) == WOTT_COMMENT and r not in rules:
            iptc.easy.delete_rule(table, chain, r)
    for r in rules:
        if r not in existing:
            iptc.easy.add_rule(table, chain, r)


def block_ports(port_list):
    prepare_iptables()
    rules = [{
                'protocol': 'tcp',
                'tcp': {'dport': str(p)},
                'target': DROP_CHAIN,
                'comment': WOTT_COMMENT
            } for p in port_list]
    update_iptables(TABLE, INPUT_CHAIN, rules)


def block_networks(network_list):
    prepare_iptables()
    rules = [{
            'dst': n,
            'target': DROP_CHAIN,
            'comment': WOTT_COMMENT
        } for n in network_list]
    update_iptables(TABLE, OUTPUT_CHAIN, rules)
