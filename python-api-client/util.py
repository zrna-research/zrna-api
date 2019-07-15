from __future__ import (absolute_import, division,
                        print_function)
from builtins import (ascii, bytes, chr, dict, filter, hex, input,
                      int, map, next, oct, open, pow, range, round,
                      str, super, zip)

from cobs import cobs
from pb_def.proto_python import zr_pb2 as zr
from time import sleep
import Adafruit_GPIO.FT232H as FT232H
import inflection

from google.protobuf.json_format import ParseDict

DUMMY = 0xff
BUSY = 0xff
READY = 0xfe
READ = 0xfd
DUMP_DATA = 0xfc

update_address_index = 1
address_index = 10

import serial
import sys
import serial.tools.list_ports

class ZrnaConnectionError(Exception):
    def __init__(self):
        super().__init__('Unable to connect. Verify that your OS sees a connected USB serial device.')

def enum_value_inflect(path_component_string):
    return inflection.underscore(path_component_string).upper()

class Connection(object):
    def __init__(self, interface='usb_serial', device_path=None, debug=False):
        self.debug = debug
        self.connection = None
        if interface == 'usb_serial' and device_path is None:
            for com_port in serial.tools.list_ports.comports():
                if com_port.description == 'zrna midi/cdc':
                    print(com_port.device)
                    self.connection = self._get_connection(interface, com_port.device)
                    break
        else:
            self.connection = self._get_connection(interface, device_path)
        if not self._ping_ok():
            raise ZrnaConnectionError()

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
            #d0 <-> PA9     ------> USART1_TX
            #d1 <-> PA10     ------> USART1_RX
            return serial.Serial('/dev/ttyUSB0', baudrate=115200)
        elif sys.argv[1] == 'spi':
            FT232H.use_FT232H()
            self.ft232h = FT232H.FT232H()
            # d0 <-> sck / pb13
            # d1 <-> mosi / pb15
            # d2 <-> miso / pb14
            # c8 <-> nss /  pb12, C8 IS C0 on FT BOARD!!
            return FT232H.SPI(
                self.ft232h, cs=8,
                max_speed_hz=1000000, mode=0, bitorder=FT232H.MSBFIRST)
        elif sys.argv[1] == 'i2c':
            #PB10     ------> I2C2_SCL
            #PB9     ------> I2C2_SDA
            FT232H.use_FT232H()
            self.ft232h = FT232H.FT232H()
            return FT232H.I2CDevice(self.ft232h, 0x15)

    def _get_path_component_resource_id(self, path_component_string):
        try:
            return zr.PathComponent.ResourceId.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_module_type(self, path_component_string):
        try:
            return zr.AnalogModule.Type.Value(enum_value_inflect(path_component_string).replace('Lf', 'LF'))
        except ValueError:
            return None

    def _get_path_component_parameter_id(self, path_component_string):
        try:
            return zr.Parameter.Id.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_system_option_id(self, path_component_string):
        try:
            return zr.SystemOption.Id.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_option_id(self, path_component_string):
        try:
            return zr.Option.Id.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_input_id(self, path_component_string):
        try:
            return zr.InputId.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_output_id(self, path_component_string):
        try:
            return zr.OutputId.Value(enum_value_inflect(path_component_string))
        except ValueError:
            return None

    def _get_path_component_integer(self, path_component_string):
        try:
            return int(path_component_string)
        except ValueError:
            return None

    def _build_protobuf_url(self, url_string):
        url = zr.URL()
        for path_component_string in filter(None, url_string.split('/')):
            path_component = url.path_components.add()
            if self._get_path_component_resource_id(path_component_string) is not None:
                path_component.resource_id = self._get_path_component_resource_id(path_component_string)
            elif self._get_path_component_module_type(path_component_string) is not None:
                path_component.module_type = self._get_path_component_module_type(path_component_string)
            elif self._get_path_component_parameter_id(path_component_string) is not None:
                path_component.parameter_id = self._get_path_component_parameter_id(path_component_string)
            elif self._get_path_component_option_id(path_component_string) is not None:
                path_component.option_id = self._get_path_component_option_id(path_component_string)
            elif self._get_path_component_input_id(path_component_string) is not None:
                path_component.input_id = self._get_path_component_input_id(path_component_string)
            elif self._get_path_component_output_id(path_component_string) is not None:
                path_component.output_id = self._get_path_component_output_id(path_component_string)
            elif self._get_path_component_system_option_id(path_component_string) is not None:
                path_component.system_option_id = self._get_path_component_system_option_id(path_component_string)
            elif self._get_path_component_integer(path_component_string) is not None:
                path_component.integer_argument = self._get_path_component_integer(path_component_string)
            else:
                path_component.string_argument = path_component_string
        return url

    def post(self, url, payload=None):
        if self.debug:
            print('POST %s' % url)
        request = zr.Request()
        request.method = zr.Method.Value('POST')
        request.url.CopyFrom(self._build_protobuf_url(url))

        if isinstance(payload, zr.Circuit):
            request.circuit.CopyFrom(payload)
        elif isinstance(payload, zr.StorageDebugRequest):
            request.storageDebugRequest.CopyFrom(payload)
        elif isinstance(payload, zr.AnalogModule):
            request.module.CopyFrom(payload)
        elif isinstance(payload, zr.Net):
            request.net.CopyFrom(payload)
        elif isinstance(payload, zr.ConfigurationByteStream):
            request.bytestream.CopyFrom(payload)
        elif isinstance(payload, zr.MidiListener):
            request.midi_listener.CopyFrom(payload)
        elif isinstance(payload, zr.ParameterSweep):
            request.parameter_sweep.CopyFrom(payload)

        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

    def get(self, url):
        if self.debug:
            print('GET %s' % url)
        request = zr.Request()
        request.method = zr.Method.Value('GET')
        request.url.CopyFrom(self._build_protobuf_url(url))
        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

    def map_to_nullable(self, systemOptionsDict):
        return {k:(zr.System.BoolOption.Value('Enabled')
                   if v else zr.System.BoolOption.Value('Disabled')) for k, v in systemOptionsDict.items()}

    def put(self, url, payload):
        if self.debug:
            print('PUT %s' % url)
        request = zr.Request()
        request.method = zr.Method.Value('PUT')
        request.url.CopyFrom(self._build_protobuf_url(url))

        if isinstance(payload, zr.AnalogModule):
            request.module.CopyFrom(payload)
        elif isinstance(payload, zr.Net):
            request.net.CopyFrom(payload)
        elif isinstance(payload, zr.Option):
            request.option_value = payload.value
        elif isinstance(payload, zr.LookupTable):
            request.lookup_table.CopyFrom(payload)
        elif isinstance(payload, zr.ModuleClockConfiguration):
            request.module_clock_configuration.CopyFrom(payload)
        elif isinstance(payload, float):
            request.requested = payload
        elif isinstance(payload, bool):
            request.system_option_enabled = payload
        elif isinstance(payload, int):
            zr.SystemState.Name(payload)
            request.system_state = payload
        else:
            if 'options' in payload:
                payload['options'] = self.map_to_nullable(payload['options'])
            ParseDict(payload, request.system)

        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

    def patch(self, url, payload, lookupTable=None):
        if self.debug:
            print('PATCH %s' % url)
        request = zr.Request()
        request.method = zr.Method.Value('PATCH')
        request.url.CopyFrom(self._build_protobuf_url(url))

        if isinstance(payload, zr.AnalogModule):
            request.module.CopyFrom(payload)
        elif isinstance(payload, zr.ProcessorClockConfiguration):
            request.processor_clock_configuration.CopyFrom(payload)

        if lookupTable is not None:
            request.lookup_table.data[:] = lookupTable
        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

    def delete(self, url, filter_args=None):
        if self.debug:
            print('DELETE %s' % url)
        request = zr.Request()
        request.method = zr.Method.Value('DELETE')
        request.url.CopyFrom(self._build_protobuf_url(url))
        if isinstance(filter_args, zr.MidiListener):
            request.midiListener.CopyFrom(filter_args)
        raw_response = write_and_wait(self.connection, request, get_payload=True)
        response = zr.Response()
        response.ParseFromString(raw_response)
        return response

def i2c_scan():
    for address in range(127):
        if address <= 7 or address >= 120:
            continue
        i2c = FT232H.I2CDevice(ft232h, address)
        if i2c.ping():
            print('Found I2C device at address 0x{0:02X}'.format(address))

def i2c_write_test():
    i2c = FT232H.I2CDevice(ft232h, 0x15)
    i2c.writeRaw8(0xED)

def i2c_read_test():
    i2c = FT232H.I2CDevice(ft232h, 0x15)
    print(i2c.readRaw8())

def spi_magic(z, payload, get_payload=False):
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
                    print('Bad response from target, dying')
                    sys.exit()
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
        print('Bad response from target, dying')
        sys.exit()
    print('OK')

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
        print('Bad response from target, dying')
        sys.exit()
    print('OK')

def write_and_wait(z, r, get_payload=False):
    spi = isinstance(z, FT232H.SPI)
    i2c = isinstance(z, FT232H.I2CDevice)
    if spi:
        if get_payload:
            return spi_magic(z, r.SerializeToString(), get_payload)
        else:
            spi_magic(z, r.SerializeToString())
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
