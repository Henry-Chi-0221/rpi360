"""SSH/loopback is the default trust boundary; direct HTTPS can use a token."""

import hmac
import ipaddress

from fastapi import HTTPException


class AccessPolicy:
    def __init__(self, token=None):
        if token is not None and (len(token) < 32 or not token.isascii()):
            raise ValueError("API token must contain at least 32 ASCII characters")
        self.token = token
        self.mode = "bearer" if token is not None else "local"

    @staticmethod
    def local_request(request):
        try:
            peer = ipaddress.ip_address(request.client.host)
            host = request.url.hostname
            local_host = host == "localhost" or ipaddress.ip_address(host).is_loopback
            return peer.is_loopback and local_host
        except (ValueError, AttributeError):
            return False

    def verify(self, request):
        if self.mode == "local":
            if not self.local_request(request):
                raise HTTPException(403, "use an SSH tunnel to the loopback API")
            return "local"
        header = request.headers.get("authorization", "")
        candidate = header[7:] if header.startswith("Bearer ") else ""
        if not candidate.isascii() or not hmac.compare_digest(candidate, self.token):
            raise HTTPException(
                401, "this HTTPS deployment requires its configured API token"
            )
        return "bearer"
