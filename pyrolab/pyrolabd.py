import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
import shutil
from typing import Any, Dict, NamedTuple, Union

import Pyro5.api as api
from pydantic import BaseModel
from tabulate import tabulate

from pyrolab import PYROLABD_DATA, LOCKFILE, USER_CONFIG_FILE
from pyrolab.manager import ProcessManager
from pyrolab.configure import (
    DaemonConfiguration, 
    GlobalConfiguration, 
    NameServerConfiguration, 
    ServiceConfiguration, 
    # update_config, 
    # reset_config, 
    # export_config,
)


RUNTIME_CONFIG = PYROLABD_DATA / "runtime_config.yaml"


log = logging.getLogger(__name__)


class InstanceInfo(BaseModel):
    pid: int
    uri: str


class PSInfo(NamedTuple):
    name: str
    ptype: str
    created: datetime
    status: str
    uri: str


def parse_process(process) -> Dict[str, Any]:
    if process:
        created = process.created
        if datetime.now() - created > timedelta(seconds=86400):
            days = (datetime.now() - created).seconds / 86400
            status = f"Up {int(days)} hours"
        elif datetime.now() - created > timedelta(seconds=3600):
            hrs = (datetime.now() - created).seconds / 3600
            status = f"Up {int(hrs)} hours"
        elif datetime.now() - created > timedelta(seconds=120):
            mins = (datetime.now() - created).seconds / 60
            status = f"Up {int(mins)} minutes"
        elif datetime.now() - created > timedelta(seconds=60):
            status = f"Up 1 minute"
        else:
            status = f"Up {(datetime.now() - created).seconds} seconds"
        uri = ""
        created = created.strftime("%Y-%m-%d %H:%M:%S")
    else:
        created = ""
        status = "Stopped"
        uri = ""
    return {"created": created, "status": status, "uri": uri}


@api.expose
@api.behavior(instance_mode="single")
class PyroLabDaemon:
    def __init__(self):        
        self.manager = ProcessManager.instance()

        if USER_CONFIG_FILE.exists():
            self.gconfig = GlobalConfiguration.instance()
            self.gconfig.load_config(USER_CONFIG_FILE)
            self.gconfig.save_config(RUNTIME_CONFIG)
        else:
            self.gconfig = GlobalConfiguration.instance()

    def reload(self) -> bool:
        """
        Reloads the latest configuration file and restarts services that were 
        running.

        Returns
        -------
        bool
            True if the reload was successful, False otherwise.
        """
        shutil.copy(USER_CONFIG_FILE, RUNTIME_CONFIG)
        self.gconfig.load_config(RUNTIME_CONFIG)
        return self.manager.reload()

    def whoami(self):
        return f"{id(self)} at {os.getpid()}"

    def ps(self):
        """
        List all known processes grouped as nameservers, daemons, and services.

        Lists process names, status (i.e. running, stopped, etc.), start time,
        URI/ports, etc.
        """
        listing = []
        for ns in self.gconfig.get_config().nameservers.keys():
            process = self.manager.get_nameserver_process(ns)
            results = parse_process(process)
            listing.append(PSInfo(ns, "nameserver", **results))
        for daemon in self.gconfig.get_config().daemons.keys():
            process = self.manager.get_daemon_process(daemon)
            results = parse_process(process)
            listing.append(PSInfo(daemon, "daemon", **results))
        for service in self.gconfig.get_config().services.keys():
            listing.append(PSInfo(service, "service", "", "", ""))
        
        return tabulate(listing, headers=["NAME", "TYPE", "CREATED", "STATUS", "URI"])

    def start_nameserver(self, nameserver: str):
        self.manager.launch_nameserver(nameserver)

    def start_daemon(self, daemon: str):
        self.manager.launch_daemon(daemon)

    def stop_nameserver(self, nameserver: str):
        self.manager.stop_nameserver(nameserver)

    def stop_daemon(self, daemon: str):
        self.manager.stop_daemon(daemon)

    # def info(self, name: str):
    #     pass

    # def logs(self, name: str):
    #     pass

    def restart_nameserver(self, name: str):
        pass

    def restart_daemon(self, name: str):
        pass

    def add_nameserver(self, name: str, config: NameServerConfiguration):
        if name not in self.gconfig.get_config().nameservers:
            self.gconfig.get_config().nameservers[name] = config
            self.gconfig.save_config(RUNTIME_CONFIG)

    def rm_nameserver(self, name: str):
        if name in self.gconfig.get_config().nameservers:
            del self.gconfig.get_config().nameservers[name]
            self.gconfig.save_config(RUNTIME_CONFIG)

    def add_daemon(self, name: str, config: DaemonConfiguration):
        if name not in self.gconfig.get_config().daemons:
            self.gconfig.get_config().daemons[name] = config
            self.gconfig.save_config(RUNTIME_CONFIG)

    def rm_daemon(self, name: str):
        if name in self.gconfig.get_config().daemons:
            del self.gconfig.get_config().daemons[name]
            self.gconfig.save_config(RUNTIME_CONFIG)

    def add_service(self, name: str, config: ServiceConfiguration):
        if name not in self.gconfig.get_config().services:
            self.gconfig.get_config().services[name] = config
            self.gconfig.save_config(RUNTIME_CONFIG)

    def rm_service(self, name: str):
        if name in self.gconfig.get_config().services:
            del self.gconfig.get_config().services[name]
            self.gconfig.save_config(RUNTIME_CONFIG)

    @api.oneway
    def shutdown(self):
        self._pyroDaemon.shutdown()


if __name__ == "__main__":
    if LOCKFILE.exists():
        raise RuntimeError(f"Lockfile already exists. Is another instance running?")
    else:
        import sys
        if len(sys.argv) > 1:
            port = int(sys.argv[1])
        else:
            port = 0

        try:
            LOCKFILE.touch(exist_ok=False)
            daemon = api.Daemon(port=port)
            pyrolabd = PyroLabDaemon()
            uri = daemon.register(pyrolabd, "pyrolabd")
            ii = InstanceInfo(pid=os.getpid(), uri=str(uri))
            with LOCKFILE.open("w") as f:
                f.write(ii.json())
            daemon.requestLoop()
        finally:
            LOCKFILE.unlink()
            RUNTIME_CONFIG.unlink()
