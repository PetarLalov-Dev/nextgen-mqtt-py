from src.nextgen_mqtt.helix import parse_helix_message
from google.protobuf.json_format import MessageToDict
import json

ARMING_LEVEL = {0:'ARMING_NOT_SET',1:'ARMING_ALL_OFF',2:'ARMING_DISARM',3:'ARMING_STAY',
                4:'ARMING_NIGHT',5:'ARMING_AWAY',6:'ARMING_LEVEL6',7:'ARMING_LEVEL7',8:'ARMING_LEVEL8'}

# Inferred from cross-referencing ZoneStatusGetResp / PartitionStatusGetResp field numbers
ZONE_INFO_FIELDS = {
    1: 'zone_num', 2: 'signal', 3: 'open_violated', 4: 'tampered', 5: 'bypassed',
    6: 'entry_delay', 7: 'protest_arming', 8: 'low_battery', 9: 'supervision_failure',
    10: 'reset_needed', 20: 'concentration_ppm', 21: 'temperature', 100: 'error',
}
PARTITION_INFO_FIELDS = {
    1: 'partition_num', 2: 'arming_level', 3: 'alarm', 4: 'entry_delay_remaining_sec',
    5: 'exit_delay_remaining_sec', 6: 'alarm_memory', 7: 'ready_to_arm_all', 8: 'silent',
    9: 'quick_exit', 10: 'no_entry_delay', 11: 'protesting', 12: 'trouble_beeps',
    13: 'alarm_report_aborted', 14: 'alarm_report_canceled', 100: 'error',
}

def decode_varint(buf, pos):
    result, shift = 0, 0
    while True:
        b = buf[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def parse_wire(data):
    fields, pos = {}, 0
    while pos < len(data):
        tag, pos = decode_varint(data, pos)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            val, pos = decode_varint(data, pos)
            fields[fn] = val
        elif wt == 2:
            l, pos = decode_varint(data, pos)
            fields[fn] = data[pos:pos+l]
            pos += l
        else:
            break
    return fields

def verbose_decode(hex_str):
    data = bytes.fromhex(hex_str)
    meta = parse_helix_message(data)
    msg_name = meta.message_name

    # Get outer Helix wire fields
    outer = parse_wire(data)

    # Get the inner payload bytes for the oneof field
    inner_bytes = None
    for fn, val in outer.items():
        if isinstance(val, bytes):
            inner_bytes = val
            inner_fn = fn
            break

    result = {'message': msg_name, 'hex': hex_str, 'fields': {}}

    if inner_bytes:
        inner = parse_wire(inner_bytes)
        if msg_name == 'zone_info_get_resp':
            field_map = ZONE_INFO_FIELDS
        elif msg_name == 'partition_info_get_resp':
            field_map = PARTITION_INFO_FIELDS
        else:
            # Fall back to proto decode
            result['fields'] = MessageToDict(meta.message, preserving_proto_field_name=True).get(msg_name, {})
            return result

        for fn, val in sorted(inner.items()):
            name = field_map.get(fn, f'field_{fn}')
            if name == 'arming_level':
                result['fields'][name] = ARMING_LEVEL.get(val, val)
            elif name in ('open_violated','tampered','bypassed','entry_delay','low_battery',
                          'supervision_failure','reset_needed','protest_arming','alarm',
                          'alarm_memory','ready_to_arm_all','silent','quick_exit',
                          'no_entry_delay','protesting','trouble_beeps',
                          'alarm_report_aborted','alarm_report_canceled'):
                result['fields'][name] = bool(val)
            else:
                result['fields'][name] = val
    else:
        result['fields'] = MessageToDict(meta.message, preserving_proto_field_name=True).get(msg_name, {})

    return result

if __name__ == '__main__':
    import sys
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(json.dumps(verbose_decode(line)))
