import contextlib
import os
import subprocess
import tempfile
from typing import Optional
from urllib.parse import urlparse

from blaze.action import Policy
from blaze.logger import logger

from blaze.mahimahi.server.dns import DNSServer
from blaze.mahimahi.server.filestore import FileStore
from blaze.mahimahi.server.interfaces import Interfaces
from blaze.mahimahi.server.nginx_config import Config


@contextlib.contextmanager
def start_server(
    replay_dir: str,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    push_policy: Optional[Policy] = None,
    preload_policy: Optional[Policy] = None,
):
    log = logger.with_namespace("replay_server")
    push_policy = push_policy.as_dict if push_policy else {}
    preload_policy = preload_policy.as_dict if preload_policy else {}

    # Load the file store into memory
    if not os.path.isdir(replay_dir):
        raise NotADirectoryError(f"{replay_dir} is not a directory")
    filestore = FileStore(replay_dir)

    # Create host-ip mapping
    hosts = filestore.hosts
    interfaces = Interfaces(hosts)
    host_ip_map = interfaces.mapping

    # Save files and create nginx configuration
    config = Config()
    with tempfile.TemporaryDirectory() as file_dir:
        log.debug("storing temporary files in", file_dir=file_dir)

        for host, files in filestore.files_by_host.items():
            log.info("creating host", host=host, address=host_ip_map[host])
            uris_served = set()

            # Create a server block for this host
            server = config.http_block.add_server(
                server_name=host, server_addr=host_ip_map[host], cert_path=cert_path, key_path=key_path, root=file_dir
            )

            for file in files:
                # Handles the case where we may have duplicate URIs for a single host
                if file.uri in uris_served:
                    continue

                # Handles a case where URIs in nginx cannot be too long
                if len(file.uri) > 3600 or len(file.headers.get("location", "")) > 3600:
                    continue

                uris_served.add(file.uri)
                log.debug(
                    "serve",
                    file_name=file.file_name,
                    status=file.status,
                    method=file.method,
                    uri=file.uri,
                    host=file.host,
                )

                # Create entry for this resource
                if file.status == 200:
                    loc = server.add_location_block(
                        uri=file.uri, file_name=file.file_name, content_type=file.headers.get("content-type", None)
                    )
                elif "location" in file.headers:
                    loc = server.add_location_block(uri=file.uri, redirect_uri=file.headers["location"])
                else:
                    log.warn("skipping", file_name=file.file_name, method=file.method, uri=file.uri, host=file.host)
                    continue

                # Save the file's body to file
                file_path = os.path.join(file_dir, file.file_name)
                with open(os.open(file_path, os.O_CREAT | os.O_WRONLY, 0o644), "wb") as f:
                    f.write(file.body)

                # Add headers
                for key, value in file.headers.items():
                    loc.add_header(key, value)

                # Look up push and preload policy
                full_source = f"https://{file.host}{file.uri}"
                push_res_list = push_policy.get(full_source, push_policy.get(full_source + "/", []))
                preload_res_list = preload_policy.get(full_source, preload_policy.get(full_source + "/", []))

                for res in push_res_list:
                    path = urlparse(res["url"]).path
                    log.debug("create push rule", source=file.uri, push=path)
                    loc.add_push(path)
                for res in preload_res_list:
                    log.debug("create preload rule", source=file.uri, preload=res["url"], type=res["type"])
                    loc.add_preload(res["url"], res["type"])

        # Save the nginx configuration
        conf_file = "/tmp/m_nginx.conf"  # os.path.join(file_dir, "nginx.conf")
        log.debug("writing nginx config", conf_file=conf_file)
        with open(conf_file, "w") as f:
            f.write(str(config))

        # Create the interfaces, start the DNS server, and start the NGINX server
        with interfaces:
            with DNSServer(host_ip_map):
                # If wait lasts for more than 3 seconds, a TimeoutError will be raised, which is okay since it
                # means that dnsmasq is running successfully. If it finishes sooner, it means it crashed and
                # we should raise an exception
                try:
                    proc = subprocess.Popen(["/usr/local/openresty/nginx/sbin/nginx", "-c", conf_file])
                    proc.wait(1)
                    raise RuntimeError("nginx exited unsuccessfully")
                except subprocess.TimeoutExpired:
                    yield
                finally:
                    proc.terminate()
