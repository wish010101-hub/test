import ipaddress
import re
import socket
from urllib.parse import urlsplit, parse_qs


def canonical_url(value):
    if len(value) > 2048 or re.search(r'[\x00-\x20\\]', value):
        raise ValueError('Некорректная ссылка.')
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise ValueError('Нужна HTTPS-ссылка YouTube или Instagram.')
    host = u.hostname
    if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
        if host == 'youtu.be':
            ident = u.path.removeprefix('/')
        elif u.path == '/watch':
            ids = parse_qs(u.query).get('v', [])
            ident = ids[0] if len(ids) == 1 else ''
        elif u.path.startswith('/shorts/'):
            ident = u.path[len('/shorts/'):].rstrip('/')
        else:
            ident = ''
        if re.fullmatch(r'[\w-]{11}', ident, re.ASCII):
            return 'https://www.youtube.com/watch?v=' + ident
    elif host in ('instagram.com', 'www.instagram.com'):
        m = re.fullmatch(r'/(reel|reels|p)/([A-Za-z0-9_-]{1,64})/?', u.path)
        if m:
            return 'https://www.instagram.com/' + ('reel' if m[1] == 'reels' else m[1]) + '/' + m[2] + '/'
    raise ValueError('Поддерживаются ссылки на видео YouTube, Shorts, Instagram Reels и публикации.')


def public_ip(value):
    ip = ipaddress.ip_address(value.split('%')[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified


def install_network_guard():
    # Each connect (including redirects) is checked and pinned to a numeric public IP.
    original = socket.socket.connect
    def connect(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise OSError('Unsupported network family')
        host, port = address[:2]
        if port not in (80, 443):
            raise OSError('Blocked network port')
        resolved = socket.getaddrinfo(host, port, sock.family, socket.SOCK_STREAM)
        if not resolved or any(not public_ip(r[4][0]) for r in resolved):
            raise OSError('Blocked non-public destination')
        return original(sock, resolved[0][4])
    socket.socket.connect = connect
    def connect_ex(sock, address):
        try:
            connect(sock, address)
            return 0
        except OSError:
            return 13
    socket.socket.connect_ex = connect_ex
