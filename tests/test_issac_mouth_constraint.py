"""A feathered model tooth must not survive beside the two identity fangs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from PIL import Image,ImageDraw
from integration.issac.common import file_hash
from integration.issac.mouth import ConstrainedMouth


class TwoFangConstraint(unittest.TestCase):
    def test_one_aperture_retains_exactly_two_fangs_including_feathered_edge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);textures=[]
            for i in (1,2):
                image=Image.new('RGBA',(7,9));ImageDraw.Draw(image).polygon([(0,0),(6,0),(3,8)],fill=(250,244,235,255))
                path=root/('fang-'+str(i)+'.png');image.save(path)
                textures.append({'path':path.name,'sha256':file_hash(path)})
            mouth=ConstrainedMouth(root,constraints={'upper_fangs':textures})
            oral=np.full((35,80,3),(63,13,19),dtype=np.uint8)
            for left in (20,40,70):oral[7:17,left:left+5]=(255,255,255)
            alpha=np.full((35,80),255,dtype=np.uint8);alpha[:,68:]=100
            original=np.zeros((512,512,3),np.uint8);before=original.copy()
            plate=np.full((512,512,3),(240,170,70),dtype=np.uint8)
            aperture=(oral,(210,390,290,425),1500,Image.fromarray(alpha))
            with patch('integration.issac.mouth.oral_crop',return_value=aperture) as detect:
                output,record=mouth.project(plate,original,(260,258),1,False)
            self.assertTrue(record['open']);self.assertEqual(record['source_box'],[210,390,290,425])
            self.assertEqual(detect.call_count,1)
            white=(output[...,0]>160)&(output[...,1]>120)&(output[...,2]>110)&(output[...,2]>output[...,0]*.48)
            count,_labels,stats,_=cv2.connectedComponentsWithStats(white.astype(np.uint8),8)
            self.assertEqual(sum(int(stats[i,cv2.CC_STAT_AREA])>=3 for i in range(1,count)),2)
            np.testing.assert_array_equal(original,before)
            self.assertEqual(tuple(output[280,260]),(63,13,19)) # Actual dark cavity remains open.


if __name__=='__main__':unittest.main()
