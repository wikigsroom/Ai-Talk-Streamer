"""One low-delay NVENC video encoder shared by VPN receivers; PCM stays lossless."""
from fractions import Fraction
import struct


class H264Encoder:
    codec_string = 'avc1.42c01f'

    def __init__(self, width=720, height=1280, bitrate=3000000, codec_name='h264_nvenc'):
        import av
        self.av = av
        self.codec = av.CodecContext.create(codec_name, 'w')
        self.codec.width, self.codec.height = width, height
        self.codec.pix_fmt = 'yuv420p'
        self.codec.time_base = Fraction(1, 25)
        self.codec.framerate = Fraction(25)
        self.codec.bit_rate = bitrate
        self.codec.options = {'preset': 'p1', 'tune': 'ull', 'profile': 'baseline',
                              'level': '3.1', 'rc': 'cbr', 'bf': '0', 'g': '50',
                              'zerolatency': '1', 'delay': '0', 'forced-idr': '1'}

    def encode(self, image, sequence, keyframe=False):
        frame = self.av.VideoFrame.from_ndarray(image, format='bgr24')
        frame.pts, frame.time_base = sequence, Fraction(1, 25)
        if keyframe:
            frame.pict_type = self.av.video.frame.PictureType.I
        packets = self.codec.encode(frame)
        # Pair every encoded image with the PCM from exactly the same frame.
        # Buffered encoders cannot silently move the mouth ahead of its voice.
        if len(packets) != 1 or packets[0].pts != sequence:
            raise RuntimeError('The configured H264 encoder is buffering frames')
        packet = packets[0]
        return b'AVC1' + struct.pack('<I', int(packet.is_keyframe)) + bytes(packet), packet.is_keyframe
