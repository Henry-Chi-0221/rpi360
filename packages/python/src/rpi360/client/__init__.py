"""Dependency-free Python client for the authenticated camera API."""

import json
import uuid
from urllib.request import Request, urlopen


class DeviceClient:
    def __init__(self, base_url, token=None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path, body=None, method=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method or ("GET" if body is None else "POST"),
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def pair(self, code, name="Python client"):
        self.token = self.request("/v1/pair", {"code": code, "name": name})["token"]
        return self.token

    def status(self):
        return self.request("/v1/status")

    def start_capture(self):
        return self.request("/v1/capture/start", {})

    def start_recording(self, request_id=None):
        return self.request(
            "/v1/recordings/start", {"request_id": request_id or uuid.uuid4().hex}
        )

    def stop_recording(self, request_id=None):
        return self.request(
            "/v1/recordings/stop", {"request_id": request_id or uuid.uuid4().hex}
        )

    def recordings(self):
        return self.request("/v1/recordings")["items"]
