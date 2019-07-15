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

from cobs import cobs
from google.protobuf.json_format import ParseDict
from time import sleep
import inflection
import serial
import serial.tools.list_ports
import sys
import zrna.zr_pb2 as zr

FT232H_ENABLED = False

if FT232H_ENABLED:
    # Optional support for communication via FT232H
    # which supports UART, I2C and SPI
    import Adafruit_GPIO.FT232H as FT232H

class Connection(object):
    def __init__(self, interface='usb_serial', device_path=None, debug=False):
        self.debug = debug
        self.connection = None
        if interface == 'usb_serial' and device_path is None:
            for com_port in serial.tools.list_ports.comports():
                if com_port.description == 'zrna midi/cdc':
                    if self.debug:
                        print(com_port.device)
                    self.connection = self._get_connection(interface, com_port.device)
                    break
        else:
            self.connection = self._get_connection(interface, device_path)
        if not self._ping_ok():
            raise ConnectionError()

    def _ping_ok(self):
        if self.connection is None:
            return False
        response = self.get('/ping')
        ack_bytes = bytearray(response.acknowledge.data)
        return all(
            [response.status_code == zr.StatusCode.Value('OK'),
             ack_bytes[0] == 0xc0,
             ack_bytes[1] == 0xff,
             ack_bytes[2] == 0xee])

    def _get_connection(self, connection_type, device_path):
        if connection_type == 'usb_serial':
            if device_path is not None:
                return serial.Serial(device_path)
        elif sys.argv[1] == 'uart':
            # FT232H, D0 <-> PA9, USART1_TX
            # FT232H, D1 <-> PA10, USART1_RX
            return serial.Serial('/dev/ttyUSB0', baudrate=115200)
        elif FT232H_ENABLED and sys.argv[1] == 'spi':
            FT232H.use_FT232H()
            self.ft232h = FT232H.FT232H()
            # FT232H, D0 <-> PB13, SCK
            # FT232H, D1 <-> PB15, MOSI
            # FT232H, D2 <-> PB14, MISO
            # FT232H, C8 <-> PB12, NSS
            return FT232H.SPI(
                self.ft232h, cs=8,
                max_speed_hz=1000000, mode=0, bitorder=FT232H.MSBFIRST)
        elif FT232H_ENABLED and sys.argv[1] == 'i2c':
            # FT232H, D0, pullup <-> PB10, I2C2_SCL
            # FT232H, D1 + D2 tied together, pullup <-> PB9, I2C2_SDA
            FT232H.use_FT232H()
            self.ft232h = FT232H.FT232H()
            return FT232H.I2CDevice(self.ft232h, 0x15)

    def _as_path_component(self, url_substring):
        enum_inflected = enum_value_inflect(url_substring)
        path_component_type = {
            'resource_id': (lambda: zr.PathComponent.ResourceId.Value(enum_inflected)),
            'module_type': (lambda: zr.AnalogModule.Type.Value(enum_inflected.replace('Lf', 'LF'))),
            'parameter_id': (lambda: zr.Parameter.Id.Value(enum_inflected)),
            'option_id': (lambda: zr.Option.Id.Value(enum_inflected)),
            'input_id': (lambda: zr.InputId.Value(enum_inflected)),
            'output_id': (lambda: zr.OutputId.Value(enum_inflected)),
            'system_option_id': (lambda: zr.SystemOption.Id.Value(enum_inflected)),
            'integer_argument': (lambda: int(url_substring))
        }
        for name, from_string in path_component_type.items():
            try:
                return (name, from_string())
            except ValueError:
                continue

        return 'string_argument', url_substring

    def _build_protobuf_url(self, url_string):
        url = zr.URL()
        for url_substring in filter(None, url_string.split('/')):
            path_component = url.path_components.add()
            path_component_type, value = self._as_path_component(url_substring)
            setattr(path_component, path_component_type, value)
        return url

    def _populate_post_payload(self, request, payload):
        payload_types = {
            'circuit': zr.Circuit,
            'storage_debug_request': zr.StorageDebugRequest,
            'module': zr.AnalogModule,
            'net': zr.Net,
            'bytestream': zr.ConfigurationByteStream,
            'midi_listener': zr.MidiListener,
            'parameter_sweep': zr.ParameterSweep
        }
        for name, payload_type in payload_types.items():
            if isinstance(payload, payload_type):
                getattr(request, name).CopyFrom(payload)

    def _send_and_await_response(self, request):
        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

    def _new_request(self, method, url):
        if self.debug:
            print('%s %s' % (method, url))
        request = zr.Request()
        request.method = zr.Method.Value(method)
        request.url.CopyFrom(self._build_protobuf_url(url))
        return request

    def post(self, url, payload=None):
        request = self._new_request('POST', url)
        self._populate_post_payload(request, payload)
        return self._send_and_await_response(request)

    def get(self, url):
        return self._send_and_await_response(
            self._new_request('GET', url))

    def _populate_put_payload(self, request, payload):
        payload_types = {
            'module': zr.AnalogModule,
            'net': zr.Net,
            'option_value': zr.Option,
            'lookup_table': zr.LookupTable,
            'module_clock_configuration': zr.ModuleClockConfiguration,
            'requested': float,
            'system_option_enabled': bool,
            'system_state': int,
        }
        for name, payload_type in payload_types.items():
            if isinstance(payload, payload_type):
                if name == 'option_value':
                    setattr(request, name, payload.value)
                elif payload_type in [float, bool, int]:
                    setattr(request, name, payload)
                else:
                    getattr(request, name).CopyFrom(payload)

    def put(self, url, payload):
        request = self._new_request('PUT', url)
        self._populate_put_payload(request, payload)
        return self._send_and_await_response(request)

    def patch(self, url, payload, lookupTable=None):
        request = self._new_request('PATCH', url)

        if isinstance(payload, zr.AnalogModule):
            request.module.CopyFrom(payload)
        elif isinstance(payload, zr.ProcessorClockConfiguration):
            request.processor_clock_configuration.CopyFrom(payload)

        if lookupTable is not None:
            request.lookup_table.data[:] = lookupTable

        return self._send_and_await_response(request)

    def delete(self, url, filter_args=None):
        request = self._new_request('DELETE', url)

        if isinstance(filter_args, zr.MidiListener):
            request.midiListener.CopyFrom(filter_args)

        return self._send_and_await_response(request)

class ConnectionError(Exception):
    def __init__(self):
        super().__init__(
            'Unable to connect. Verify that your OS sees a connected USB serial device.')

class StatusCodeError(Exception):
    def __init__(self, status_code):
        super().__init__(
            'Expected OK status code in response but received %s' % (zr.StatusCode.Name(status_code)))

def i2c_scan():
    if FT232H_ENABLED:
        for address in range(127):
            if address <= 7 or address >= 120:
                continue
            i2c = FT232H.I2CDevice(ft232h, address)
            if i2c.ping():
                print('Found I2C device at address 0x{0:02X}'.format(address))

def i2c_write_test():
    if FT232H_ENABLED:
        i2c = FT232H.I2CDevice(ft232h, 0x15)
        i2c.writeRaw8(0xED)

def i2c_read_test():
    if FT232H_ENABLED:
        i2c = FT232H.I2CDevice(ft232h, 0x15)
        return i2c.readRaw8()

def handle_spi(z, payload, get_payload=False):
    while True:
        b = bytearray()
        b.append(DUMMY)
        c = z.transfer(b)
        if c[0] == READY:
            b = bytearray(cobs.encode(payload))
            b.append(0x00)
            l = len(b)
            lb = bytearray()
            lb.append((l & 0xff00) >> 8)
            lb.append(l & 0x00ff);
            z.write(lb)
            z.write(b)
        elif c[0] == BUSY:
            pass
        elif c[0] == READ:
            b = z.read(2)
            length = b[0] << 8 | b[1]
        elif c[0] == DUMP_DATA:
            b = z.read(length)

            if not get_payload:
                response = zr.Response()
                response.ParseFromString(cobs.decode(bytes(b[:-1])))
                if response.status_code != zr.OK:
                    raise StatusCodeError(response.status_code)
                return
            else:
                return cobs.decode(bytes(b[:-1]))
        sleep(0.02)

def read_framed(z):
    b = bytearray()
    b.append(z.read(1)[0])
    while b[-1] != 0x00:
        b.append(z.read(1)[0])
    return cobs.decode(bytes(b[:-1]))

def write_framed(z, payload):
    b = bytearray(cobs.encode(payload))
    b.append(0x00)
    z.write(b)

def wait_for_ok(z):
    response = zr.Response()
    response.ParseFromString(read_framed(z))
    if response.status_code != zr.OK:
        raise StatusCodeError(response.status_code)

def read_framed_i2c(z):
    b = bytearray()
    b.append(z.readRaw8())
    while b[-1] != 0x00:
        b.append(z.readRaw8())
    return cobs.decode(bytes(b[:-1]))

def write_framed_i2c(z, payload):
    b = bytearray(cobs.encode(payload))
    b.append(0x00)
    for byte in b:
        z.writeRaw8(byte)

def wait_for_ok_i2c(z):
    response = zr.Response()
    response.ParseFromString(read_framed_i2c(z))
    if response.status_code != zr.OK:
        raise StatusCodeError(response.status_code)

def write_and_wait(z, r, get_payload=False):
    spi = FT232H_ENABLED and isinstance(z, FT232H.SPI)
    i2c = FT232H_ENABLED and isinstance(z, FT232H.I2CDevice)
    if spi:
        if get_payload:
            return handle_spi(z, r.SerializeToString(), get_payload)
        else:
            handle_spi(z, r.SerializeToString())
    elif i2c:
        write_framed_i2c(z, r.SerializeToString())
        sleep(0.1)
        if get_payload:
            return read_framed_i2c(z)
        else:
            wait_for_ok_i2c(z)
    else:
        write_framed(z, r.SerializeToString())
        if get_payload:
            return read_framed(z)
        else:
            wait_for_ok(z)

def within_tolerance(requested, realized, tolerance):
    if requested != 0:
        return ((abs(realized - requested)
                 / float(requested) * 100) < tolerance)
    else:
        return requested == realized

def update_lookup_table(obj, module_description):
    if 'lookupTable' in module_description:
        obj.lookup_table.data[:] = module_description['lookupTable']

def update_module(m, module):
    m.ClearField('clock_configuration')
    m.ClearField('options')
    m.ClearField('parameters')

    if module.get('clockConfiguration'):
        if module['clockConfiguration'].get('clockA'):
            m.clock_configuration.clock_a = module['clockConfiguration']['clockA']
        if module['clockConfiguration'].get('clockB'):
            m.clock_configuration.clock_b = module['clockConfiguration']['clockB']

    if module.get('type'):
        m.type = module['type']
    for option, value in module.get('options', {}).items():
        o = m.options.add()
        o.id = zr.Option.Id.Value(enum_value_inflect(option))
        o.value = value
    for parameter, value in module.get('parameters', {}).items():
        p = m.parameters.add()
        p.id = zr.Parameter.Id.Value(enum_value_inflect(parameter))
        p.requested = value

def add_nets(circuit, nets):
    if nets is not None:
        for net in nets:
            n = circuit.nets.add()
            n.output_address.module_id = net['output_address']['module_id']
            n.output_address.output_id = net['output_address']['output_id']
            n.input_address.module_id = net['input_address']['module_id']
            n.input_address.input_id = net['input_address']['input_id']

def print_raw_bytestream(bytestream):
    for i, d in enumerate(bytearray(bytestream.data)):
        print(hex(d))

def validate_bytestream(bytestream, expected, address_index):
    for i, d in enumerate(bytearray(bytestream.data)):
        print(hex(d), expected[i])
        if i == address_index:
            assert d == 0
        else:
            assert d == int(expected[i], 16)

def validate_wire_bytestream(bytestream, expected, address_index):
    for i, d in enumerate(bytearray(bytestream.data)):
        print(hex(d), hex(expected[i]))
        if i == address_index:
            assert d == 0
        else:
            assert d == expected[i]

def to_path_name(resource_id):
    return inflection.dasherize(resource_id.lower())

def camel_to_path_name(resource_id):
    return inflection.dasherize(inflection.underscore(resource_id))

def to_field_name(resource_id):
    return resource_id.lower()

def to_class_name(resource_id):
    return inflection.camelize(resource_id.lower()).replace('Lf', 'LF')

def ok(response):
    return response.status_code == zr.StatusCode.Value('OK')

def invalid(response):
    return response.status_code == zr.StatusCode.Value('INVALID_REQUEST_ERROR')

def enum_value_inflect(path_component_string):
    return inflection.underscore(path_component_string).upper()

DUMMY = 0xff
BUSY = 0xff
READY = 0xfe
READ = 0xfd
DUMP_DATA = 0xfc
