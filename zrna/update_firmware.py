# Copyright 2019 Zrna Research LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

from __future__ import (absolute_import, division,
                        print_function)
from builtins import (ascii, bytes, chr, dict, filter, hex, input,
                      int, map, next, oct, open, pow, range, round,
                      str, super, zip)

import serial
import serial.tools.list_ports
import sys
import os
import math
import platform

def usage():
    print('usage: python -m zrna.update_firmware /path/to/m.sfb [device_path_or_com_port]')
    sys.exit()

def main():
    if not (len(sys.argv) > 1):
        usage()

    device = sys.argv[2] if len(sys.argv) == 3 else None
    if device is None:
        for com_port in serial.tools.list_ports.comports():
            if com_port.description == 'zrna bootloader':
                device = com_port.device

    if device is None:
        print("Couldn't connect to the zrna bootloader. Check connections and try specifying the device path:")
        usage()

    try:
        s = serial.Serial(device)
        if platform.system() == 'Darwin':
            os.system('stty -f %s 1200' % device)
    except serial.serialutil.SerialException:
        print("Couldn't open a connection to path %s. Check connections and verify device path." % device)
        sys.exit()

    print('Connected to bootloader.')

    path = sys.argv[1]
    if not os.path.exists(path):
        print("Couldn't find the specified firmware image.")
    filesize = os.path.getsize(path)
    packet_size = 1024
    packet_count = math.ceil(filesize / packet_size)

    filesize_bytes = bytearray()
    filesize_bytes.append((filesize & 0xff000000) >> 24)
    filesize_bytes.append((filesize & 0xff0000) >> 16)
    filesize_bytes.append((filesize & 0xff00) >> 8)
    filesize_bytes.append((filesize & 0xff))

    print('Firmware image size: %d bytes' % filesize)
    print('Pushing image size to device.')

    s.write(filesize_bytes)

    packet_index = 0
    with open(path, 'rb') as f:
        while True:
            packet = f.read(packet_size)
            if not packet:
                break
            print('Writing packet %d of %d.' % (packet_index + 1, packet_count))
            s.write(packet)
            s.read(1)
            packet_index += 1
        print('Firmware flash complete. Device rebooting.')

if __name__ == "__main__":
    main()
