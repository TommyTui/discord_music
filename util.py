import re

from urllib.parse import urlparse, parse_qs


def get_bv_and_p(url):
    parsed_url = urlparse(url)
    path = parsed_url.path
    match = re.search(r'/BV', path)
    bv = "BV" + path[match.end():]
    if bv.endswith('/'):
        bv = bv[:-1]
    query_params = parse_qs(parsed_url.query)
    pid = query_params.get('p', None)
    if pid:
        pid = int(pid[0]) - 1
    return bv, pid
