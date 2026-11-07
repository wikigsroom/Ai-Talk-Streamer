"""Explicit v3 configuration for the existing, unchanged H264/PCM packet header.

v2 carries Annex-B video. v3 carries length-prefixed AVC with a real avcC
description, as required by WebCodecs when `description` is configured.
This module neither loads an avatar nor creates a video encoder.
"""
import base64
import re
import struct
import uuid


def annex_b_nalus(data):
    starts = list(re.finditer(b'\x00\x00(?:\x00)?\x01', data))
    if not starts or any(data[:starts[0].start()]):
        raise ValueError('H264_ANNEX_B_REQUIRED')
    units = [data[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(data)]
             for i, m in enumerate(starts)]
    if not all(units):
        raise ValueError('H264_EMPTY_NAL')
    return units


class MediaProfile:
    def __init__(self):
        self.sps = self.pps = None
        self.signature = None
        self.init = None

    def packet(self, encoded, width, height):
        if len(encoded) < 9 or encoded[:4] != b'AVC1':
            raise ValueError('H264_PACKET_INVALID')
        if not (64 <= width <= 4096 and 64 <= height <= 4096):
            raise ValueError('MEDIA_DIMENSIONS_INVALID')
        units = annex_b_nalus(encoded[8:])
        if self.signature and self.signature[:2] != (width, height) and not {7, 8}.issubset({u[0] & 31 for u in units}):
            raise ValueError('MEDIA_RESIZE_REQUIRES_PARAMETER_SETS')
        for unit in units:
            if unit[0] & 31 == 7:
                self.sps = unit
            elif unit[0] & 31 == 8:
                self.pps = unit
        if self.sps is None or self.pps is None or len(self.sps) < 4:
            raise ValueError('H264_PARAMETER_SETS_REQUIRED')
        if max(len(self.sps), len(self.pps)) > 65535:
            raise ValueError('H264_PARAMETER_SETS_TOO_LARGE')
        signature = (width, height, self.sps, self.pps)
        if signature != self.signature:
            if not struct.unpack_from('<I', encoded, 4)[0] or not any(u[0] & 31 == 5 for u in units):
                raise ValueError('MEDIA_PROFILE_CHANGE_REQUIRES_IDR')
            description = (b'\x01' + self.sps[1:4] + b'\xff\xe1' + struct.pack('>H', len(self.sps))
                           + self.sps + b'\x01' + struct.pack('>H', len(self.pps)) + self.pps)
            self.init = {
                'type': 'media.init', 'protocol_version': 3,
                'stream_id': 'media-' + uuid.uuid4().hex,
                'media_profile_id': f'source-{width}x{height}-25',
                'width': width, 'height': height, 'fps_num': 25, 'fps_den': 1,
                'codec': 'avc1.' + self.sps[1:4].hex(),
                'avc_description_base64': base64.b64encode(description).decode('ascii'),
                'audio': {'format': 's16le', 'sample_rate': 16000, 'channels': 1},
                'time_base_num': 1, 'time_base_den': 1000000, 'pts_origin_us': 0,
            }
            self.signature = signature
        avcc = b''.join(struct.pack('>I', len(unit)) + unit for unit in units)
        return encoded[:8] + avcc, self.init


def stream_request_error(query):
    if query.get('v', '2') not in ('2', '3'):
        return 'MEDIA_VERSION_UNSUPPORTED'
    if query.get('v') == '3' and query.get('codec') != 'h264':
        return 'MEDIA_V3_REQUIRES_H264'
    return None
