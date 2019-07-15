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

from .util import Connection
from .util import to_path_name, to_field_name, to_class_name
from collections import OrderedDict
from functools import wraps
from google.protobuf import text_format
from google.protobuf.json_format import MessageToDict, MessageToJson
from inflection import camelize
import json
import pprint
import sys
import textwrap
import zrna.zr_pb2 as zr

class Input(object):
    def __init__(self, zr, module, input_id, enabled):
        self.zr = zr
        self.module = module
        self.input_id = input_id
        self.enabled = enabled
        self.connected_to = None

    def connect(self, module_output):
        output_phase = module_output.phase
        input_phase = self.phase
        self.zr._assert_phase_ok(output_phase, input_phase)

        self.zr._add_net(
            module_output.module.id,
            module_output.output_id,
            self.module.id,
            self.input_id)
        self.connected_to = module_output
        module_output.connected_to = self

    @property
    def phase(self):
        return self.zr._get_input_phase(self.module.id, self.input_id)

    def disconnect(self):
        self.zr._disconnect_input(self.module.id, self.input_id)
        self.connected_to.connected_to = None
        self.connected_to = None

class Output(object):
    def __init__(self, zr, module, output_id):
        self.zr = zr
        self.module = module
        self.output_id = output_id
        self.connected_to = None

    def connect(self, module_input):
        output_phase = self.phase
        input_phase = module_input.phase
        self.zr._assert_phase_ok(output_phase, input_phase)

        self.zr._add_net(
            self.module.id,
            self.output_id,
            module_input.module.id,
            module_input.input_id)
        self.connected_to = module_input
        module_input.connected_to = self

    @property
    def phase(self):
        return self.zr._get_output_phase(self.module.id, self.output_id)

    def disconnect(self):
        self.zr._disconnect_output(self.module.id, self.output_id)
        self.connected_to.connected_to = None
        self.connected_to = None

class Parameter(float):
    def __new__(self, zr, module, parameter_id, value):
        return float.__new__(self, value)

    def __init__(self, zr, module, parameter_id, value):
        float.__init__(value)
        self.zr = zr
        self.module = module
        self.parameter_id = parameter_id
        self.dummy_value = 42

    def _get_listener_template(self):
        listener = zr.MidiListener()
        listener.module_id = self.module.id
        listener.parameter_id = zr.Parameter.Id.Value(self.parameter_id.upper())
        return listener

    def stop_listening(self, **kwargs):
        listener = self._get_listener_template()
        if kwargs.get('midi') == self.zr.CC:
            listener.cc.number = self.dummy_value
        elif kwargs.get('midi') == self.zr.Note:
            listener.note.custom_value_map = False;
        elif kwargs.get('midi') == self.zr.Trigger:
            listener.trigger.parameter_value = self.dummy_value
        elif kwargs.get('midi') == self.zr.Gate:
            listener.gate.parameter_value_open = self.dummy_value
        self.zr.delete('/circuit/midi/listener', listener)

    def listen(self, **kwargs):
        listener = zr.MidiListener()
        listener.module_id = self.module.id
        listener.parameter_id = zr.Parameter.Id.Value(self.parameter_id.upper())
        if kwargs.get('midi') == self.zr.CC:
            listener.cc.parameter_value_range.min = kwargs['min']
            listener.cc.parameter_value_range.max = kwargs['max']
            listener.cc.parameter_value_range.cc_min = kwargs.get('cc_min', 0)
            listener.cc.parameter_value_range.cc_max = kwargs.get('cc_max', 127)
            if kwargs.get('cc_num'):
                listener.cc.controller_number = kwargs['cc_num']
            else:
                listener.cc.match_any = True
        elif kwargs.get('midi') == self.zr.Note:
            if 'value_for_note' in kwargs:
                listener.note.custom_value_map = True
                listener.note.parameter_map.values[:] = kwargs.get('value_for_note')
            else:
                listener.note.custom_value_map = False;
        elif kwargs.get('midi') == self.zr.Trigger:
            listener.trigger.parameter_value = kwargs['value']
        elif kwargs.get('midi') == self.zr.Gate:
            listener.gate.parameter_value_open = kwargs['open']
            listener.gate.parameter_value_closed = kwargs['closed']

        if listener.WhichOneof('type') is not None:
            self.zr.post('/circuit/midi/listeners', listener)
        return self

    def sweep(self, **kwargs):
        s = zr.ParameterSweep()
        if not ('target' in kwargs and
                'duration_ms' in kwargs and
                'steps' in kwargs):
            self.zr._error(".sweep() expects kwargs: target, duration_ms and steps")
        s.target_value = kwargs['target']
        s.duration_microseconds = kwargs['duration_ms'] * 1000
        s.step_count = kwargs['steps']
        self.zr.post('/circuit/module/%d/parameter/%s/sweep' %
                     (self.module.id, to_path_name(self.parameter_id)), s)

    @property
    def requested(self):
        return self

    @property
    def realized(self):
        response = self.zr.get('/circuit/module/%d/parameter/%s/realized' %
                               (self.module.id, to_path_name(self.parameter_id)))
        return response.realized

    @property
    def maximum(self):
        response = self.zr.get('/circuit/module/%d/parameter/%s/maximum' %
                               (self.module.id, to_path_name(self.parameter_id)))
        return response.maximum

    @property
    def minimum(self):
        response = self.zr.get('/circuit/module/%d/parameter/%s/minimum' %
                               (self.module.id, to_path_name(self.parameter_id)))
        return response.minimum

class LookupTable(object):
    def __init__(self, zr, module):
        self.zr = zr
        self.module = module
        self.requested_lookup_table = [0.0] * 256

    @property
    def requested(self):
        return self.requested_lookup_table

    @requested.setter
    def requested(self, lookup_table):
        self.requested_lookup_table = lookup_table

    def push(self):
        if self.module.id is not None:
            t = zr.LookupTable()
            t.data[:] = self.requested_lookup_table
            self.zr.put('/circuit/module/%d/lookup-table' % self.module.id, t)

    @property
    def realized(self):
        if self.module.id is not None:
            return self.zr.get('/circuit/module/%d/lookup-table' % self.module.id).lookup_table.data
        return None

class Option(int):
    def __new__(self, zr, module, option_id, value, valid_values):
        return int.__new__(self, value)

    def __init__(self, zr, module, option_id, value, valid_values):
        self.zr = zr
        self.module = module
        self.option_id = option_id
        self.value = value
        self.valid_values = valid_values
        self.dummy_value = 42

    def _get_listener_template(self):
        listener = zr.MidiListener()
        listener.module_id = self.module.id
        listener.option_id = zr.Option.Id.Value(self.option_id.upper())
        return listener

    def stop_listening(self, **kwargs):
        listener = self._get_listener_template()
        if kwargs.get('midi') == self.zr.CC:
            listener.cc.number = self.dummy_value
        elif kwargs.get('midi') == self.zr.Note:
            listener.note.custom_value_map = False;
        elif kwargs.get('midi') == self.zr.Trigger:
            listener.trigger.option_value = self.dummy_value
        elif kwargs.get('midi') == self.zr.Gate:
            listener.gate.option_value_open = self.dummy_value
        self.zr.delete('/circuit/midi/listener', listener)

    def listen(self, **kwargs):
        listener = zr.MidiListener()
        listener.module_id = self.module.id
        listener.option_id = zr.Option.Id.Value(self.option_id.upper())
        if kwargs.get('midi') == self.zr.CC:
            if kwargs.get('cc_option_range') is None:
                self.zr._error("kwarg cc_option_range needs to be specified to bind an option to cc")

            for value, cc_lower, cc_upper in kwargs['cc_option_range']:
                i = listener.cc.option_value_range.items.add()
                i.value = value
                i.cc_value_lower_bound_inclusive = cc_lower
                i.cc_value_upper_bound_exclusive = cc_upper

            if kwargs.get('cc_num'):
                listener.cc.controller_number = kwargs['cc_num']
            else:
                listener.cc.match_any = True
        elif kwargs.get('midi') == self.zr.Trigger:
            listener.trigger.option_value = kwargs['value']
        elif kwargs.get('midi') == self.zr.Gate:
            listener.gate.option_value_open = kwargs['open']
            listener.gate.option_value_closed = kwargs['closed']

        if listener.WhichOneof('type') is not None:
            self.zr.post('/circuit/midi/listeners', listener)
        return self

    @property
    def value(self):
        return self.__value

    @value.setter
    def value(self, v):
        self.__value = v

    def __str__(self):
        return zr.Option.Value.Name(self.value)

class Storage(object):
    def __init__(self, zr):
        self.zr = zr

    def __str__(self):
        return str(self.debug())

    def _storage_request(self, cmd, path, new_path='', data=''):
        debugRequest = zr.StorageDebugRequest()
        debugRequest.command = zr.StorageDebugRequest.Command.Value(cmd.upper())
        debugRequest.path = path
        debugRequest.new_path = new_path
        debugRequest.data = data
        return self.zr.post('/storage/debug', debugRequest)

    def debug(self):
        return self.zr._as_pretty_dict(self.zr.get('/storage/debug'))

    def cat(self, path):
        return self._storage_request('cat', path)

    def ls(self, path):
        return self._storage_request('ls', path)

    def put(self, path, data):
        return self._storage_request('put', path, data=data)

    def remove(self, path):
        return self._storage_request('remove', path)

    def rename(self, path, new_path):
        return self._storage_request('rename', path, new_path)

    def mkdir(self, path):
        return self._storage_request('mkdir', path)

class ZrnaException(Exception):
    pass

class Client(object):
    def __init__(self):
        self.connection = None
        self.module_instances = []

        for k, v in zr.Option.Value.items():
            setattr(self, k, v)

        for k, v in zr.ClockId.items():
            setattr(self, k, v)

        for v, k in enumerate(
                ['CC', 'Note', 'Trigger', 'Gate']):
            setattr(self, k, v)

    def _error(self, msg):
        raise ZrnaException(msg)

    def _is_ok(self, response):
        if response.status_code == zr.StatusCode.Value('OK'):
            return
        self._error(
            "remote responded with error code: %s" % zr.StatusCode.Name(response.status_code))

    def request(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            self = args[0]
            if self.connection is not None:
                response = f(*args, **kwargs)
                self._is_ok(response)
                return response
            self._error("issued request before connecting to remote device")
        return decorated

    @request
    def post(self, url, payload=None):
        return self.connection.post(url, payload)

    @request
    def patch(self, url, payload, lookup_table=None):
        return self.connection.patch(url, payload, lookup_table)

    @request
    def put(self, url, payload):
        return self.connection.put(url, payload)

    @request
    def get(self, url):
        return self.connection.get(url)

    @request
    def delete(self, url, filter_args=None):
        return self.connection.delete(url, filter_args)

    @property
    def version(self):
        d = MessageToDict(self.get('/version'), True)['version']
        return '%d.%d.%d' % (
            d['major'],
            d['minor'],
            d['patch'])

    def _transition_to(self, state):
        self.put('/system/state', state)

    def _get_module_dict(self, module_message, moduleType, moduleName):
        d = MessageToDict(module_message, True)
        m = {}

        slots = ['id', '_option_valid_values', '_inputs']

        if d.get('hasLookupTable'):
            slots.append('lookup_table')
        if 'clockConfiguration' in d:
            slots.append('clock_configuration')

        m['options'] = []
        m['parameters'] = []
        m['type'] = moduleType
        m['type_name'] = to_class_name(moduleName)

        for option in d.get('options', []):
            option_id = to_field_name(option.get('id', zr.Option.Id.Name(0)))
            slots.append(option_id)
            m['options'].append(option_id)
        for parameter in d.get('parameters', []):
            parameter_id = to_field_name(parameter.get('id', zr.Parameter.Id.Name(0)))
            slots.append(parameter_id)
            m['parameters'].append(parameter_id)

        response = self.get('/module/%s/inputs' % to_path_name(moduleName))
        m['_all_inputs'] = response.inputs.input

        response = self.get('/module/%s/outputs' % to_path_name(moduleName))
        m['outputs'] = MessageToDict(response)['outputs']
        if m['outputs']:
            m['outputs'] = list(map(to_field_name, m['outputs']['output']))
            slots.extend(m['outputs'])
        else:
            m['outputs'] = []

        def module_init(module_self, **kwargs):
            module_self.id = None
            module_self._option_valid_values = {}
            module_self._inputs = {}

            for option in d.get('options', []):
                option_id = to_field_name(option.get('id', zr.Option.Id.Name(0)))
                module_self._option_valid_values[option_id] = option['validValues']
                setattr(module_self, option_id, zr.Option.Value.Value(option.get('value', zr.Option.Value.Name(0))))

            for parameter in d.get('parameters', []):
                parameter_id = to_field_name(parameter.get('id', zr.Parameter.Id.Name(0)))
                setattr(module_self, parameter_id, parameter['requested'])

            for i in m['_all_inputs']:
                module_input = to_field_name(zr.InputId.Name(i.id))
                if i.conditionally_enabled:
                    enabled = lambda: getattr(module_self, to_field_name(zr.Option.Id.Name(i.enabled_if.option_id))) == i.enabled_if.option_value
                else:
                    enabled = lambda: True

                module_self._inputs[module_input] = Input(self, module_self, module_input, enabled)

            for module_output in m['outputs']:
                setattr(module_self,
                        module_output,
                        Output(self, module_self, module_output))

            if d.get('hasLookupTable'):
                setattr(module_self,
                        'lookup_table',
                        LookupTable(self, module_self))

            if 'clockConfiguration' in d:
                clock_configuration = zr.ModuleClockConfiguration()
                clock_configuration.CopyFrom(module_message.clock_configuration)
                setattr(module_self,
                        'clock_configuration',
                        clock_configuration)

            for key, value in kwargs.items():
                if not hasattr(module_self, key):
                    raise ValueError("%s doesn't have %s as a parameter or option" % (to_class_name(moduleName), key))
                setattr(module_self, key, value)

        def module_setattr(module_self, attr, value):
            if attr in m['parameters'] and module_self.id is not None:
                self.put('/circuit/module/%d/parameter/%s/requested' % (module_self.id, to_path_name(attr)), float(value))
            elif attr in m['options'] and module_self.id is not None:
                o = zr.Option()
                o.value = value
                self.put('/circuit/module/%d/option/%s/value' % (module_self.id, to_path_name(attr)), o)
            elif attr in m['options']:
                if zr.Option.Value.Name(value) not in module_self._option_valid_values[attr]:
                    self._error("'%s' isn't valid value for module option '%s'" % (
                        zr.Option.Value.Name(value), attr))

            object.__setattr__(module_self, attr, value)

        def module_getattribute(module_self, attr):
            if attr == 'inputs':
                return [i.input_id for i in module_self._inputs.values() if i.enabled()]
            elif attr in object.__getattribute__(module_self, '_inputs'):
                i = object.__getattribute__(module_self, '_inputs')[attr]
                if i.enabled():
                    return i
                else:
                    self._error('%s input is currently disabled' % attr)
            elif attr in m['parameters']:
                return Parameter(self, module_self, attr, object.__getattribute__(module_self, attr))
            elif attr in m['options']:
                return Option(
                    self, module_self, attr, object.__getattribute__(module_self, attr),
                    module_self._option_valid_values[attr])
            else:
                return object.__getattribute__(module_self, attr)

        def module_set_clock(module_self, clock_id):
            if hasattr(module_self, 'clock_configuration'):
                module_self.clock_configuration.clock_a = clock_id
                module_self.put_clock_configuration()

        def module_set_secondary_clock(module_self, clock_id):
            if hasattr(module_self, 'clock_configuration'):
                module_self.clock_configuration.clock_b = clock_id
                module_self.put_clock_configuration()

        def module_get_clock_configuration(module_self):
            if module_self.id is not None:
                return self.get('/circuit/module/%d/clock' % module_self.id)

        def module_put_clock_configuration(module_self):
            if (module_self.id is not None and
                hasattr(module_self, 'clock_configuration')):
                self.put('/circuit/module/%d/clock' % module_self.id,
                         getattr(module_self, 'clock_configuration'))

        def has_lookup_table(module_self):
            return hasattr(module_self, 'lookup_table')

        def module_can_add(module_self):
            return self.get('/module/%s/analog/fits' % to_path_name(moduleName)).moduleFits

        def module_analog(module_self):
            return self._as_pretty_dict(
                self.get('/module/%s/analog' % to_path_name(moduleName)).analogInfo)

        def module_str(module_self):
            s = m['type_name'] + ' {' + '\n'
            for field in ['parameters', 'options']:
                f = getattr(module_self, field)
                if f:
                    s += '  ' + field + ' {\n'
                    for foo in sorted(f):
                        s += ('    ' + foo + ': ' + str(getattr(module_self, foo)) + '\n')
                    s += '  }\n'

            for field in ['inputs', 'outputs']:
                f = getattr(module_self, field)
                if f:
                    s += '  ' + field + ' ' + str(sorted(f)) + '\n'
            s += '}'
            return s

        def module_repr(module_self):
            return '<%s from %s>' % (m['type_name'], repr(self))

        m['__init__'] = module_init
        m['__slots__'] = slots
        m['__getattribute__'] = module_getattribute
        m['__setattr__'] = module_setattr
        m['__str__'] = module_str
        m['__repr__'] = module_repr
        m['analog'] = module_analog
        m['can_add'] = module_can_add
        m['set_clock'] = module_set_clock
        m['set_secondary_clock'] = module_set_secondary_clock
        m['has_lookup_table'] = has_lookup_table
        m['get_clock_configuration'] = module_get_clock_configuration
        m['put_clock_configuration'] = module_put_clock_configuration
        return m

    def _enumerate_modules(self):
        response = self.get('/modules')

        for moduleType in response.module_types.module_type:
            moduleTypeName = zr.AnalogModule.Type.Name(moduleType)
            response = self.get('/module/%s' % to_path_name(moduleTypeName))
            module_class_name = to_class_name(moduleTypeName)
            setattr(self, module_class_name,
                    type(module_class_name, (object,),
                         self._get_module_dict(response.modules.module[0], moduleType, moduleTypeName)))

    def _sync(self):
        circuit = self.get('/circuit').circuit
        self.module_instances = []
        for m in list(circuit.modules):
            module = getattr(self, to_class_name(zr.AnalogModule.Type.Name(m.type)))()

            for p in m.parameters:
                setattr(module, to_field_name(zr.Parameter.Id.Name(p.id)),
                        p.requested)
            for o in m.options:
                try:
                    setattr(module, to_field_name(zr.Option.Id.Name(o.id)),
                            o.value)
                except AttributeError:
                    # ignore options not visible on public type
                    pass

            if hasattr(module, 'clock_configuration'):
                module.clock_configuration.CopyFrom(m.clock_configuration)
            self.module_instances.append(module)

    def _as_pretty_dict(self, message):
        d = MessageToDict(message, including_default_value_fields=True)
        return type('', (type(d),),
                    {'__str__': lambda d: pprint.pformat(d, indent=1)})(d)

    def _assert_phase_ok(self, output_phase, input_phase):
        if (output_phase != 'CONTINUOUS' and
            output_phase != input_phase):
            self._error(
                'phase mismatch - tried to connect %s output to %s input' % (
                    output_phase,
                    input_phase))

    def _add_net(self,
                 output_module_id, output_id,
                 input_module_id, input_id):
        if output_module_id is None:
            self._error("source module not yet added to circuit")
        if input_module_id is None:
            self._error("target module not yet added to circuit")
        n = zr.Net()
        n.output_address.module_id = output_module_id
        n.output_address.output_id = zr.OutputId.Value(output_id.upper())
        n.input_address.module_id = input_module_id
        n.input_address.input_id = zr.InputId.Value(input_id.upper())

        self.post('/circuit/nets', n)

    def _get_phase(self, module_id, io_id, input_or_output):
        if module_id is None:
            self._error("module not yet added to circuit")
        response = self.get(
            '/circuit/module/%d/%s/%s/phase' %
            (module_id, input_or_output, to_path_name(io_id)))
        return zr.Option.Value.Name(response.option_value)

    def _get_input_phase(self, module_id, input_id):
        return self._get_phase(module_id, input_id, 'inputs')

    def _get_output_phase(self, module_id, output_id):
        return self._get_phase(module_id, output_id, 'outputs')

    def _disconnect_input(self, module_id, input_id):
        self.post('/circuit/module/%d/inputs/%s/disconnect' % (module_id, to_path_name(input_id)))

    def _disconnect_output(self, module_id, output_id):
        self.post('/circuit/module/%d/outputs/%s/disconnect' % (module_id, to_path_name(output_id)))

    def connect(self, device_path=None, debug=False):
        self.connection = Connection(device_path=device_path, debug=debug)
        self._enumerate_modules()
        self._sync()
        self.pause()

    def default_divisors(self):
        self.post('/system/resource/analog/clock/default')

    def clocks(self):
        return self.get('/system/resource/analog/clock')

    def set_divisor(self, id, divisor):
        cc = zr.ProcessorClockConfiguration()
        sc = cc.sys_clock.add()
        sc.id = id
        sc.divisor = divisor
        self.patch('/system/resource/analog/clock', cc)

    def run(self):
        self._transition_to(zr.SystemState.Value('RUNNING'))

    def pause(self):
        self._transition_to(zr.SystemState.Value('PAUSED'))

    def hard_reset(self):
        self._transition_to(zr.SystemState.Value('RESETTING'))

    def clear(self):
        self.post('/circuit/default')
        self._sync()

    def free_analog_resources(self):
        return self._as_pretty_dict(self.get('/system/resource/analog'))

    def debug_analog_resources(self):
        return self._as_pretty_dict(self.get('/system/resource/analog/debug'))

    def load(self, circuit_name):
        self.post('/storage/circuit/%s/load' % circuit_name)
        self._sync()

    def store(self, circuit_name):
        if len(circuit_name) > 32:
            self._error('stored circuit names are limited to 32 characters')
        self.post('/storage/circuit/%s' % circuit_name)

    def set_startup_circuit(self, circuit_name):
        self.post('/storage/circuit/startup/%s' % circuit_name)

    def clear_startup_circuit(self):
        self.delete('/storage/circuit/startup')

    def delete_stored(self, circuit_name):
        self.delete('/storage/circuit/%s' % circuit_name)

    def stored_circuits(self):
        return self.get('/storage/circuits')

    def bytestream(self):
        return self.get('/circuit/bytestream')

    def update_bytestream(self):
        return self.get('/circuit/update-bytestream')

    def heap_usage(self):
        return self.get('/system/resource/heap')

    def storage_usage(self):
        return self.get('/system/resource/storage')

    def add(self, module):
        if module.id is not None:
            self._error("tried to add a module already present in circuit")
        module.id = self.module_instance_count()
        m = zr.AnalogModule()
        m.type = module.type
        for param in module.parameters:
            p = m.parameters.add()
            p.id = zr.Parameter.Id.Value(param.upper())
            p.requested = getattr(module, to_field_name(param))
        for option in module.options:
            o = m.options.add()
            o.id = zr.Option.Id.Value(option.upper())
            o.value = getattr(module, to_field_name(option))
        if hasattr(module, 'clock_configuration'):
            m.clock_configuration.CopyFrom(module.clock_configuration)

        self.post('/circuit/modules', m)
        self.module_instances.append(module)

        if hasattr(module, 'lookup_table'):
            module.lookup_table.push()

    def remove(self, module):
        if module.id is None or module not in self.module_instances:
            self._error("tried to remove a module not present in current circuit")
        self.delete('/circuit/module/%d' % module.id)
        self.module_instances.remove(module)
        module.id = None
        for i, module_instance in enumerate(self.module_instances):
            module_instance.id = i

    def module_instance_count(self):
        return self.get('/circuit/modules/count').module_count

    def nets(self):
        return self._as_pretty_dict(self.get('/circuit/nets'))

    def net_count(self):
        return self.get('/circuit/nets/count').net_count

    def endpoints(self):
        return self.get('/endpoints').endpoints

    def modules(self):
        return list(map(to_class_name, MessageToDict(self.get('/modules').module_types)['moduleType']))

    def ping(self):
        return self.get('/ping')

    def circuit(self):
        return self._as_pretty_dict(self.get('/circuit').circuit)

    def system_options(self):
        return self._as_pretty_dict(self.get('/system/options').system_options)

    @property
    def storage(self):
        return Storage(self)

    def midi_listeners(self):
        return self._as_pretty_dict(self.get('/circuit/midi/listeners').midi_listeners)
