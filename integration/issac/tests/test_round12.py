"""Initialization failures and official renderer arguments cannot relax safety."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from integration.issac.common import AdmissionError,write_json
from integration.issac.livehime import RENDER_ARGUMENTS,render_arguments
from integration.issac.mouth_loading import native_bf16_loaders,verify_loaded_precision


class LowCpuLoaderTests(unittest.TestCase):
    def test_original_descriptors_restore_after_a_failed_initialization(self):
        calls=[]
        class Base:
            @classmethod
            def from_pretrained(cls,path,**kwargs):
                calls.append((cls,kwargs));return kwargs
        class Diffusion(Base):pass
        class Vae(Base):pass
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);weights=root/'models/flashhead/SoulX-FlashHead-1_3B'
            with self.assertRaisesRegex(RuntimeError,'fixture initialization failed'):
                with native_bf16_loaders(root,SimpleNamespace(bfloat16='bf16'),Diffusion,Vae):
                    value=Diffusion.from_pretrained(weights/'Model_Lite')
                    self.assertEqual(value,{'torch_dtype':'bf16','low_cpu_mem_usage':True,'local_files_only':True})
                    self.assertEqual(Vae.from_pretrained(weights/'VAE_LTX'),{'torch_dtype':'bf16'})
                    with self.assertRaises(AdmissionError):Diffusion.from_pretrained(root/'foreign')
                    raise RuntimeError('fixture initialization failed')
            self.assertNotIn('from_pretrained',Diffusion.__dict__)
            self.assertNotIn('from_pretrained',Vae.__dict__)
            self.assertEqual(Diffusion.from_pretrained('original'),{})

    def test_unmaterialized_or_wrong_precision_weights_fail_before_compile(self):
        class Parameter:
            def __init__(self,dtype='bf16',meta=False):self.dtype=dtype;self.is_meta=meta
            def is_floating_point(self):return True
        def model(values):return SimpleNamespace(parameters=lambda:iter(values))
        torch=SimpleNamespace(bfloat16='bf16')
        for bad in ([],[Parameter('fp32')],[Parameter(meta=True)]):
            pipeline=SimpleNamespace(model=model(bad),vae=SimpleNamespace(model=model([Parameter()])))
            with self.assertRaises(AdmissionError):verify_loaded_precision(pipeline,torch)
        pipeline=SimpleNamespace(model=model([Parameter()]),vae=SimpleNamespace(model=model([Parameter()])))
        self.assertFalse(verify_loaded_precision(pipeline,torch)['audio_encoder_precision_changed'])


class OfficialGraphicsTests(unittest.TestCase):
    def test_only_bounded_render_modes_are_allowed_without_security_or_encoder_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            write_json(root/'configs/issac/official-rendering.json',{'default_mode':'software-ui'})
            mode,args=render_arguments(root)
            self.assertEqual(mode,'software-ui');self.assertIn('--disable-gpu-compositing',args)
            for bad in ('--no-sandbox','software-ui --ignore-certificate-errors','unknown'):
                with self.assertRaises(AdmissionError):render_arguments(root,bad)
            forbidden=('sandbox','certificate','web-security','capture','encoder','privacy')
            self.assertFalse(any(word in flag for flags in RENDER_ARGUMENTS.values() for flag in flags for word in forbidden))


if __name__=='__main__':unittest.main()
