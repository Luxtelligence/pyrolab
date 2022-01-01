# -*- coding: utf-8 -*-
#
# Copyright © PyroLab Project Contributors
# Licensed under the terms of the GNU GPLv3+ License
# (see pyrolab/__init__.py for details)

"""
Z825B
=====

Submodule containing drivers for the ThorLabs Z825B linear stage.
"""

from pyrolab.api import behavior, expose
from pyrolab.drivers.motion.kinesis.kdc101 import KDC101, HomingMixin


@behavior(instance_mode="single")
@expose
class Z825B(KDC101, HomingMixin):
    """
    A Z825B motorized linear actuator controlled by a KCube DC Servo motor. 

    Parameters
    ----------
    serialno : int
        The serial number of the device to connect to.
    polling : int
        The polling rate in milliseconds.
    """
    # def __init__(self, serialno, polling=200, home=False):
    #     super().__init__(serialno, polling, home)
