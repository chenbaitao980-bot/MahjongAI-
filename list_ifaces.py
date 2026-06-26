from scapy.all import get_working_ifaces
for i in get_working_ifaces():
    print(repr(i.name), '|', getattr(i,'description',''), '|', getattr(i,'ip',''))
