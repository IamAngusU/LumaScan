import argparse
import ipaddress
import socket
import threading
from pathlib import Path
import uvicorn
from .app import create_app
from .tls import tls

def main():
    parser=argparse.ArgumentParser(description='Local LumaScan service')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--port',type=int,default=8772)
    parser.add_argument('--phone-port',type=int,default=8773)
    parser.add_argument('--lan-ip')
    args=parser.parse_args();root=args.root.resolve();hosts=[];origin=f'http://127.0.0.1:{args.port}'
    if args.lan_ip:
        address=ipaddress.ip_address(args.lan_ip)
        if not address.is_private or address.is_loopback or address.is_unspecified or address.version!=4:parser.error('Use a private IPv4 address assigned to this computer')
        with socket.socket() as probe:probe.bind((str(address),0))
        hosts=[str(address)];origin=f'https://{address}:{args.phone_port}';tls(root/'runtime',['127.0.0.1',str(address)])
    app=create_app(root,lan_hosts=hosts,phone_origin=origin)
    phone=None
    if args.lan_ip:
        phone=uvicorn.Server(uvicorn.Config(app,host=args.lan_ip,port=args.phone_port,ssl_certfile=str(root/'runtime/server.pem'),ssl_keyfile=str(root/'runtime/server.key'),proxy_headers=False,access_log=False))
        threading.Thread(target=phone.run,daemon=True).start()
    print(f'LumaScan: http://127.0.0.1:{args.port} | phone: {origin}',flush=True)
    try:uvicorn.run(app,host='127.0.0.1',port=args.port,proxy_headers=False,access_log=False)
    finally:
        if phone:phone.should_exit=True

if __name__=='__main__':main()
