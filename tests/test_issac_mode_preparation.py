"""Guard prepared reference identity and the live oral-component equivalence."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np

from integration.issac.common import AdmissionError,file_hash,write_json
from integration.issac.flashhead import Engine
from integration.issac.mouth import component


def original_component(mask):
    h,w=mask.shape;visited=np.zeros_like(mask);best=None;best_score=-1e9
    for y,x in np.argwhere(mask):
        if visited[y,x]:continue
        stack=[(int(y),int(x))];visited[y,x]=True;points=[]
        while stack:
            yy,xx=stack.pop();points.append((yy,xx))
            for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
                yn,xn=yy+dy,xx+dx
                if 0<=yn<h and 0<=xn<w and mask[yn,xn] and not visited[yn,xn]:
                    visited[yn,xn]=True;stack.append((yn,xn))
        if len(points)<45:continue
        points=np.asarray(points);y0,x0=points.min(axis=0);y1,x1=points.max(axis=0)
        width,height=x1-x0+1,y1-y0+1
        if width<15 or height<5 or width>120 or height>80:continue
        cx=(x0+x1)/2;cy=(y0+y1)/2
        if x0<10 or x1>w-10 or y0<24 or cy<40:continue
        score=len(points)-abs(cx-85)*15-abs(cy-58)*5
        if score>best_score:best_score=score;best=(x0,y0,x1+1,y1+1,len(points),points)
    return best


class PreparedReferenceTests(unittest.TestCase):
    def engine(self,root):
        rows={}
        for mode in ('M01','M02','M03'):
            path=root/(mode+'.png');path.write_bytes(mode.encode())
            rows[mode]={'engine_reference':path.name,'engine_reference_sha256':file_hash(path)}
        write_json(root/'state/issac-materials/runtime-bank.json',{'modes':rows})
        engine=object.__new__(Engine);engine.root=root;engine.frames=33;engine.overlap=9
        engine.conditioning={};engine.audio_history=np.ones(20);engine.calls=[]
        class Generator:
            def __init__(self,device):self.device=device
            def manual_seed(self,seed):self.seed=seed;return self
        engine.torch=SimpleNamespace(inference_mode=nullcontext,Generator=Generator)
        pipeline=SimpleNamespace(device='fixture-device')
        def prepare(path,*_):
            mode=Path(path).stem;engine.calls.append(mode)
            pipeline.person_name=mode
            pipeline.cond_image_dict={mode:'image-'+mode}
            pipeline.cond_image_tensor_dict={mode:'tensor-'+mode}
            pipeline.ref_img_latent_dict={mode:'latent-'+mode}
        def reset(person):
            pipeline.ref_img_latent=pipeline.ref_img_latent_dict[person]
            pipeline.original_color_reference=pipeline.cond_image_tensor_dict[person]
        pipeline.prepare_params=prepare;pipeline.reset_person_name=reset;engine.pipeline=pipeline
        return engine

    def test_repeated_mode_switches_restore_correct_prepared_conditioning_without_reencoding(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=self.engine(Path(directory))
            for mode in ('M01','M02','M03'):engine.configure(mode)
            for mode in ('M02','M01','M03','M02'):
                engine.audio_history[:]=99;engine.configure(mode)
                self.assertEqual(engine.pipeline.person_name,mode)
                self.assertEqual(engine.pipeline.ref_img_latent,'latent-'+mode)
                self.assertEqual(engine.pipeline.original_color_reference,'tensor-'+mode)
                self.assertEqual(engine.pipeline.generator.seed,42)
                self.assertFalse(engine.audio_history.any())
            self.assertEqual(engine.calls,['M01','M02','M03'])

    def test_cached_conditioning_does_not_bypass_reference_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine=self.engine(root);engine.configure('M01')
            (root/'M01.png').write_bytes(b'changed')
            with self.assertRaisesRegex(AdmissionError,'SAME_MODE_ENGINE_REFERENCE_CHANGED'):engine.configure('M01')

    def test_native_components_preserve_exact_original_selection_and_pixels(self):
        rng=np.random.default_rng(3104)
        masks=[np.zeros((126,170),bool)]
        for _ in range(40):
            mask=rng.random((126,170))<.03
            for _ in range(6):
                y=int(rng.integers(8,100));x=int(rng.integers(0,145))
                mask[y:min(126,y+int(rng.integers(3,32))),x:min(170,x+int(rng.integers(8,55)))]=True
            masks.append(mask)
        for mask in masks:
            expected=original_component(mask);actual=component(mask)
            if expected is None:self.assertIsNone(actual);continue
            self.assertEqual(expected[:5],actual[:5])
            self.assertEqual(set(map(tuple,expected[5])),set(map(tuple,actual[5])))


if __name__=='__main__':unittest.main()
