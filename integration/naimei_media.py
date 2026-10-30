"""Protocol conversion and speech accounting, independent of GPU libraries."""
from dataclasses import dataclass
import struct

NML1 = struct.Struct('<4sIIIdIII')
COMMON = struct.Struct('<III')
RATE = 16000
FRAME_SAMPLES = 640
SILENCE = bytes(FRAME_SAMPLES * 2)


@dataclass(frozen=True)
class SourceFrame:
    sequence: int
    jpeg: bytes
    pcm: bytes
    epoch: int
    flags: int
    sample_offset: int


def parse_source(data):
    if len(data) < NML1.size:
        raise ValueError('NML1_HEADER_TRUNCATED')
    magic, sequence, length, rate, _pts, epoch, flags, offset = NML1.unpack_from(data)
    if magic != b'NML1' or rate != RATE or length < 4 or length > 4 * 1024 * 1024:
        raise ValueError('NML1_HEADER_INVALID')
    if len(data) != NML1.size + length + len(SILENCE):
        raise ValueError('NML1_PAYLOAD_INVALID')
    return SourceFrame(sequence, data[NML1.size:NML1.size + length], data[NML1.size + length:], epoch, flags, offset)


def packet(sequence, jpeg, pcm=SILENCE):
    if len(pcm) != len(SILENCE):
        raise ValueError('COMMON_PCM_LENGTH_INVALID')
    return COMMON.pack(sequence, len(jpeg), RATE) + jpeg + pcm


class SpeechMapping:
    def __init__(self, command, source_epoch, total_samples):
        self.command = {key: command[key] for key in ('request_id', 'utterance_id', 'runtime_epoch', 'generation')}
        self.source_epoch = source_epoch
        self.total_samples = total_samples
        self.next_offset = 0

    def range_for(self, source, sequence, transport_id):
        if source.epoch != self.source_epoch or not source.flags & 3 or source.sample_offset == 0xFFFFFFFF:
            return None
        if source.sample_offset >= self.total_samples:
            return None
        if source.sample_offset != self.next_offset:
            raise ValueError('SOURCE_AUDIO_NOT_CONTIGUOUS')
        count = min(FRAME_SAMPLES, self.total_samples - source.sample_offset)
        self.next_offset += count
        return {**self.command, 'valid_sample_count': self.total_samples,
            'transport_instance_id': transport_id,
            'ranges': [{'packet_seq': sequence, 'packet_offset': 0,
                'sample_start': source.sample_offset, 'sample_count': count}],
            'final': self.next_offset == self.total_samples}


class CommandFence:
    def __init__(self):
        self.current = (0, 0)
        self.command_key = None

    def speak(self, command):
        incoming = (int(command['runtime_epoch']), int(command['generation']))
        key = (command['request_id'], command['utterance_id'], command['text'])
        if incoming < self.current:
            raise ValueError('STALE_GENERATION')
        if incoming == self.current:
            if key == self.command_key:
                return False
            raise ValueError('GENERATION_COMMAND_CONFLICT')
        self.current, self.command_key = incoming, key
        return True

    def cancel(self, command):
        incoming = (int(command['runtime_epoch']), int(command['new_generation']))
        if incoming <= self.current:
            return False
        self.current, self.command_key = incoming, None
        return True

    def matches(self, command):
        return self.current == (command['runtime_epoch'], command['generation'])
