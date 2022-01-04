# -*- coding: utf-8 -*-
#
# Copyright © PyroLab Project Contributors
# Licensed under the terms of the GNU GPLv3+ License
# (see pyrolab/__init__.py for details)

"""
Configuration Settings
======================

Default configuration settings for PyroLab and methods for persisting 
configurations between settings or using YAML files.

Server Configuration
--------------------

Note the difference between the two ``servertypes``:

1. Threaded server

   Every proxy on a client that connects to the daemon will be assigned to a 
   thread to handle the remote method calls. This way multiple calls can 
   potentially be processed concurrently. This means your Pyro object may have 
   to be made thread-safe! 

2. Multiplexed server

   This server uses a connection multiplexer to process all remote method 
   calls sequentially. No threads are used in this server. It means only one 
   method call is running at a time, so if it takes a while to complete, all 
   other calls are waiting for their turn (even when they are from different 
   proxies).

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Union

import Pyro5
from pydantic import BaseModel, BaseSettings, validator
from pydantic.fields import PrivateAttr
from yaml import dump, load
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

from pyrolab import NAMESERVER_STORAGE, USER_CONFIG_FILE
from pyrolab.utils import generate_random_name, get_ip

log = logging.getLogger(__name__)


class UniqueOrAutoKeyLoader(Loader):
    """
    A loader specific for PyroLab configuration files.

    If the "auto" keyword is found, along with an optional number for name 
    length, the name will be dynamically generated.

    .. warning::
       The YAML ``load`` function can run arbitrary code on your machine. Only
       load trusted or untampered files! If in doubt, examine the file first.
       It's a short text file, and should not be hard to vet.

    Examples
    --------
    >>> from yaml import load
    >>> from pyrolab.configure import UniqueOrAutoKeyLoader
    >>> with open("config.yaml", "r") as f:
    ...     data = load(f, Loader=UniqueOrAutoKeyLoader)
    ...     print(data)
    """
    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):
            raise ConstructorError(None, None,
                    "expected a mapping node, but found %s" % node.id,
                    node.start_mark)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                       "found unacceptable key (%s)" % exc, key_node.start_mark)
            
            # Translate "auto" keyword to unique names.
            if key == "auto" or key.startswith("auto "):
                try:
                    _, count = key.split(" ")
                except ValueError:
                    count = 3

                try:
                    count = int(count)
                except ValueError as exc:
                    raise ConstructorError("while constructing a mapping", node.start_mark,
                           "unacceptable argument for 'auto' key (%s)" % exc, key_node.start_mark)

                key = generate_random_name(count)
                while key in mapping:
                    key = generate_random_name(count)

            # Check for duplicate keys
            if key in mapping:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                       "found duplicate key", key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping


class PyroConfigMixin:
    """
    Mixin for pydantic models, updates fields that are Pyro5 configuration options.
    """
    def update_pyro_config(self, values: dict=None) -> Dict[str, Any]:
        """
        Sets all key-value attributes that are Pyro5 configuration options.

        Pyro5 attributes that this function automatically translates:
        | * HOST: "public" is translated to the machine's ip address
        | * NS_HOST: "public" is translated to the machine's ip address
        | * NS_BCHOST: "public" is translated to the machine's ip address

        Parameters
        ----------
        values : dict, optional
            A dictionary of key-value pairs to update the configuration. If not
            provided, the model's attributes will be used.
        
        Returns
        -------
        dict
            A dictionary of Pyro5 key-value pairs that were updated, for 
            debugging or informational purposes.
        """
        if values is None:
            values = self.dict()

        for key in ['host', 'ns_host', 'ns_bchost']:
            if key in values:
                if values[key] == 'public':
                    values[key] = get_ip()

        pyroset = {}
        for key, value in values.items():
            key = key.upper()
            if key in Pyro5.config.__slots__:
                # All Pyro config options are fully uppercased
                setattr(Pyro5.config, key, value)
                pyroset[key] = value
        return pyroset


class YAMLMixin:
    def yaml(self, 
             sort_keys: bool=False, 
             default_flow_style: bool=False,
             exclude_defaults: bool=False) -> str:
        """
        Returns a YAML representation of the configuration.

        Parameters
        ----------
        sort_keys : bool, optional
            Sorts the keys of the dictionary alphabetically if True, else 
            leaves them in the order as declared by the model (default False).
        default_flow_style : bool, optional
            Uses the default flow style if True, or formats in human-readable
            from if False (default False).
        exclude_defaults : bool, optional
            Excludes default values from the YAML output if True, else
            includes them (default False).
        """
        return dump(self.dict(exclude_defaults=exclude_defaults), sort_keys=sort_keys, default_flow_style=default_flow_style)

    @classmethod
    def from_yaml(cls, yaml: Union[bytes, IO[bytes], str, IO[str]]) -> PyroLabConfiguration:
        """
        Loads a YAML representation of the configuration.

        .. warning::
           The YAML ``load`` function can run arbitrary code on your machine. Only
           load trusted or untampered files! If in doubt, examine the file first.
           It's a short text file, and should not be hard to vet.

        Parameters
        ----------
        yaml : bytes, str, IO[bytes], IO[str]
            The YAML to load.
        """
        loaded = load(yaml, Loader=UniqueOrAutoKeyLoader)
        cfg = cls.parse_obj(loaded)
        return cfg

    @classmethod
    def from_file(cls, filename: Union[str, Path]) -> PyroLabConfiguration:
        """
        Loads a configuration from a YAML file.

        .. warning::
           The YAML ``load`` function can run arbitrary code on your machine. Only
           load trusted or untampered files! If in doubt, examine the file first.
           It's a short text file, and should not be hard to vet.

        Parameters
        ----------
        filename : str, Path
            The filename of the YAML configuration file to load.

        Returns
        -------
        PyroLabConfiguration
            The configuration object.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        filename = Path(filename)
        if filename.exists():
            with filename.open("r") as f:
                return cls.from_yaml(f)
        else:
            raise FileNotFoundError(f"File does not exist: '{filename}'")


class NameServerConfiguration(BaseSettings, PyroConfigMixin, YAMLMixin):
    """
    The NameServer Settings class. 
    
    Contains all applicable configuration parameters for running a nameserver.

    Parameters
    ----------
    host : str, optional
        The hostname of the nameserver. Defaults to "localhost" for security.
        Can be set to "public", which is dynamically translated to the 
        machine's ip address when the nameserver is started.
    ns_port : int, optional
        The port of the nameserver. Defaults to 9090.
    broadcast : bool, optional
        Whether to launch a broadcast server. Defaults to False.
    ns_bchost : str, optional
        The hostname of the broadcast server. Defaults to None.
    ns_bcport : int, optional
        The port of the broadcast server. Defaults to 9091.
    ns_autoclean : float, optional
        The interval in seconds at which the nameserver will ping registered
        objects and clean up unresponsive ones. Default is 0.0 (off).
    storage : str, optional
        A Pyro5-style storage string. You have several options:

        * ``memory``: Fast, volatile in-memory database. This is the default.  
        * ``dbm[:dbfile]``: Persistent database using dbm. Optionally provide 
          the filename to use (ignore for PyroLab to create automatically). This 
          storage type does not support metadata.  
        * ``sql[:dbfile]``: Persistent database using sqlite. Optionally 
          provide the filename to use (ignore for PyroLab to create 
          automatically).

    Examples
    --------
    The following are examples of valid YAML configurations for nameservers.
    Keys not defined assume the default values.

    .. code-block:: yaml

        host: localhost
        ns_port: 9090
        ns_autoclean: 0.0
        storage: memory
    
    .. code-block:: yaml

        host: public
        ns_port: 9100
        broadcast: false
        ns_bchost: null
        ns_bcport: 9091
        ns_autoclean: 15.0
        storage: sql
    """
    host: str = "localhost"
    ns_port: int = 9090
    broadcast: bool = False
    ns_bchost: Optional[bool] = None
    ns_bcport: int = 9091
    ns_autoclean: float = 0.0
    storage: str = "memory"
    _name: str = PrivateAttr("")

    @validator('storage')
    def valid_memory_format(cls, v: str):
        if v == "memory":
            return v
        elif any(v.startswith(storage) for storage in ["dbm", "sql"]):
            return v
        else:
            raise ValueError(f"Invalid storage specification: {v}")

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str) -> None:
        self._name = name

    def get_storage_location(self) -> Path:
        """
        Returns the storage location for the given name.

        Returns
        -------
        Path
            The path to the storage location.
        """
        if self.storage in ["sql", "dbm"]:
            return f"{self.storage}:" + str(NAMESERVER_STORAGE / f"ns_{self.name}.{self.storage}")
        return self.storage


class DaemonConfiguration(BaseSettings, PyroConfigMixin, YAMLMixin):
    """
    Server configuration object.

    Note that for the ``host`` parameter, the string "public" will always be
    reevaluated to the computer's public IP address.

    Parameters
    ----------
    module : str, optional
        The module that contains the Daemon class (default "pyrolab.server").
    classname : str, optional
        The name of the Daemon class to use (default is basic "Daemon").
    host : str, optional
        The hostname of the local server, or the string "public", which 
        is converted to the host's public IP address (default "localhost").
    ns_host : str, optional
        The hostname of the nameserver (default "localhost").
    ns_port : int, optional
        The port of the nameserver (default 9090).
    ns_bcport : int, optional
        The port of the broadcast server (default 9091).
    ns_bchost : bool, optional
        Whether to broadcast the nameserver (default None).
    servertype : str, optional
        Either ``thread`` or ``multiplex`` (default "thread").
    nameservers : List[str], optional
        Whether to register the daemon itself with known nameservers. Useful
        if the daemon provides functions for managing local instruments that
        would be useful to remote clients.

    Examples
    --------
    The following is an example of a valid configuration file "daemons" 
    section. Keys not defined assume the default values.

    .. code-block:: yaml

        daemons:
            lockable:
                classname: LockableDaemon
                host: public
                servertype: thread
                nameservers:
                    - production
            multiplexed: 
                host: public
                servertype: multiplex
    """
    module: str = "pyrolab.daemon"
    classname: str = "Daemon"
    host: str = "localhost"
    port: int = 0
    unixsocket: Optional[str] = None
    nathost: Optional[str] = None
    natport: int = 0
    servertype: str = "thread"
    nameservers: List[str] = []


class ServiceConfiguration(BaseSettings, PyroConfigMixin, YAMLMixin):
    """
    Groups together information about a PyroLab service. 
    
    Includes connection parameters for ``autoconnect()``. Services defined in
    other modules or libaries can also be included here, so long as the module
    can be found by the Python environment.

    Parameters
    ----------
    name : str
        A unique human-readable name for identifying the instrument. If you're
        not creative, you can use :py:func:`pyrolab.utils.generate_random_name`
        to generate a random name.
    module : str
        The PyroLab module the class belongs to, as a string.
    classname : str
        The classname of the object to be registered, as a string.
    parameters : Dict[str, Any]
        A dictionary of parameters passed to the object's ``connect()`` 
        function when ``autoconnect()`` is invoked.        
    description : str
        Description string for providing more information about the device.
        Will be displayed in the nameserver.
    instancemode : str, optional
        The mode of the object to be created. See ``Service.set_behavior()``.
        Default is ``session``.
    server : str, optional
        The name of the daemon configuration to register the service with.
        Default is ``default``.
    nameservers : List[str], optional
        A list of nameservers to register the service with. Default is [] (no
        registration).

    Examples
    --------
    The following is an example of a valid configuration file "services" 
    section. Keys not defined assume the default values.

    .. code-block:: yaml

        services:
            asgard.wolverine:
                module: pyrolab.drivers.motion.prm1z8
                classname: PRM1Z8
                parameters:
                    - serialno: 27003366
                description: Rotational motion
                instancemode: single
                daemon: lockable
                nameservers: 
                    - production
            asgard.hulk:
                module: pyrolab.drivers.motion.z825b
                classname: Z825B
                parameters:
                    - serialno: 27003497
                description: Longitudinal motion
                instancemode: single
                daemon: lockable
                nameservers: 
                    - production
    """
    module: str
    classname: str
    parameters: Dict[str, Any] = {}
    description: str = ""
    instancemode: str = "session"
    daemon: str = "default"
    nameservers: List[str] = []


class AutolaunchSettings(BaseSettings, YAMLMixin):
    nameservers: List[str] = []
    daemons: List[str] = []


class PyroLabConfiguration(BaseSettings, YAMLMixin):
    """
    Global configuration options for PyroLab.

    .. warning::
       The YAML ``load`` function can run arbitrary code on your machine. Only
       load trusted or untampered files! If in doubt, examine the file first.
       It's a short text file, and should not be hard to vet.

    Please call ``initialize_nameservers()`` anytime after modifying the
    nameservers dictionary. Nameservers themselves contain a private attribute
    of their own name, which can only be given to them by the parent 
    configuration object.

    """
    version: str = "1.0"
    nameservers: Dict[str, NameServerConfiguration] = {}
    daemons: Dict[str, DaemonConfiguration] = {}
    services: Dict[str, ServiceConfiguration] = {}
    autolaunch: AutolaunchSettings = AutolaunchSettings()

    def initialize_nameservers(self):
        for name, nscfg in self.nameservers.items():
            nscfg.set_name(name)

    def get_nameserver_settings(self, nameserver: str) -> NameServerConfiguration:
        return self.nameservers[nameserver]

    def get_daemon_settings(self, daemon: str) -> DaemonConfiguration:
        return self.daemons[daemon]


class GlobalConfiguration:
    """
    A Singleton global configuration object that can read and write configuration files.

    .. warning::
       The GlobalConfiguration should only be accessed by MainProcess threads.
       Any spawned or forked processes should simply load the 
       ``RUNTIME_CONFIG`` using the PyroLabConfiguration parser.

    PyroLab configurations are stored in a YAML file. This class provides a
    singleton object that can be used to read and write the configuration file.
    The YAML files contain three sections: ``nameservers``, ``daemons``, and
    ``services``. See the documentation for examples of valid YAML files.

    The user configuration file is stored in 
    ``pyrolab.configure.USER_CONFIG_FILE``. PyroLab instances maintain the 
    configuration state of the file when the program was launched; in other 
    words, if the file is updated, the configuration state of running instances 
    is not modified by default. There are features and switches to turn on
    autoreload, however; see the documentation.

    To ensure all processes have access to the same configuration, the 
    configuration of an active instance is locked to a single file separate 
    from where user-defined configuration files are stored. This class is a 
    singleton; only the main process can modify the configuration. All spawned 
    child processes will use the configuration from the locked file.

    Attributes
    ----------
    config: PyroLabConfiguration
    """
    _instance = None

    def __init__(self) -> None:
        raise RuntimeError("Cannot directly instantiate singleton, call ``instance()`` instead.")

    @classmethod
    def instance(cls) -> "GlobalConfiguration":
        """
        Returns the singleton instance of the GlobalConfiguration class.

        Returns
        -------
        GlobalConfiguration
            The singleton instance of the GlobalConfiguration class.
        """
        if cls._instance is None:
            inst = cls.__new__(cls)
            inst.config = PyroLabConfiguration()
            cls._instance = inst
        return cls._instance

    def clear_all(self) -> None:
        """
        Clears all configuration data without reloading built-in defaults.
        """
        self.config = PyroLabConfiguration()

    def load_config(self, filename: Union[str, Path]) -> None:
        """
        Reads the configuration file and updates the internal configuration.

        Parameters
        ----------
        filename : str or Path, optional
            The path to the configuration file.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        if not filename:
            self.config = PyroLabConfiguration()
            return
        self.config = PyroLabConfiguration.from_file(filename)
        self.config.initialize_nameservers()

    def save_config(self, filename: Union[str, Path]) -> None:
        """
        Persists the configuration to a file.

        This method writes the current configuration to the given filepath.

        Parameters
        ----------
        filename : str or Path
            The path to save the configuration file to.
        """
        filename = Path(filename)
        with filename.open("w") as f:
            f.write(self.config.yaml())

    def set_config(self, cfg: PyroLabConfiguration) -> None:
        """
        Sets the global configuration to the given configuration.

        Parameters
        ----------
        cfg : PyroLabConfiguration
            The configuration to set.
        """
        self.config = cfg

    def get_config(self) -> PyroLabConfiguration:
        """
        Returns the global configuration.

        Returns
        -------
        config : PyroLabConfiguration
            The global configuration.
        """
        return self.config

    def get_nameserver_config(self, nameserver: str) -> NameServerConfiguration:
        """
        Returns the configuration for the given nameserver.

        Parameters
        ----------
        nameserver : str
            The name of the nameserver.

        Returns
        -------
        NameServerConfiguration
            The configuration for the given nameserver.
        """
        return self.config.nameservers[nameserver]

    def get_daemon_config(self, daemon: str) -> DaemonConfiguration:
        """
        Returns the configuration for the given daemon.

        Parameters
        ----------
        daemon : str
            The name of the daemon.

        Returns
        -------
        DaemonConfiguration
            The configuration for the given daemon.
        """
        return self.config.daemons[daemon]

    def get_service_config(self, service: str) -> ServiceConfiguration:
        """
        Returns the configuration for the given service.

        Parameters
        ----------
        service : str
            The name of the service.

        Returns
        -------
        ServiceConfiguration
            The configuration for the given service.
        """
        return self.config.services[service]

    def get_service_configs_for_daemon(self, daemon: str) -> Dict[str, DaemonConfiguration]:
        """
        Returns the services for the given daemon.

        Parameters
        ----------
        daemon : str
            The name of the daemon.

        Returns
        -------
        Dict[str, DaemonConfiguration]
            The services for the given daemon.
        """
        return {k: v for k, v in self.config.services.items() if v.daemon == daemon}


def update_config(filename: Union[str, Path]) -> None:
    """
    Updates the internal configuration file with a user configuration file.

    Performs validation on the configuration file before updating.

    Parameters
    ----------
    filename : str or Path, optional
        The path to the configuration file to load.

    Raises
    ------
    FileNotFoundError
        If the configuration file does not exist.
    ValidationError
        If the configuration file is invalid.
    """
    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError(f"File does not: '{filename}'")
    config = PyroLabConfiguration.from_file(filename)
    with open(USER_CONFIG_FILE, "w") as f:
        f.write(config.yaml())


def reset_config() -> None:
    """
    Resets the configuration to the default.

    This function deletes the user configuration file, reverting to the default
    configuration each time PyroLab is started.
    """
    USER_CONFIG_FILE.unlink(missing_ok=True)

def export_config(config: PyroLabConfiguration, filename: Union[str, Path]) -> None:
    """
    Exports the current configuration to a file.

    Parameters
    ----------
    config : PyroLabConfiguration
        The configuration to export.
    filename : str or Path
        The path to the configuration file or directory to export to.
    """
    with Path(filename).open("w") as f:
        f.write(config.yaml())
