"""The observed unlabelled icon must not admit a different window or action."""
import json
from pathlib import Path
import unittest

from PIL import Image
from integration.issac.common import AdmissionError
from integration.issac.official_record_control import geometry, verify_icon


ROOT=Path(__file__).resolve().parents[3]


class RecordIconBindingTests(unittest.TestCase):
    def setUp(self):
        self.binding=json.loads((ROOT/'configs/issac/official-record-control.json').read_text('utf8'))

    def test_only_reviewed_geometry_and_dpi_admit_the_separate_local_record_area(self):
        box,point=geometry([138,49,1782,990],96,self.binding)
        self.assertEqual(box,(943,909,967,933));self.assertEqual(point,(955,921))
        for rect,dpi in (([138,49,1783,990],96),([138,49,1782,990],120)):
            with self.assertRaises(AdmissionError):geometry(rect,dpi,self.binding)
        changed={**self.binding,'click_point':[1293,872]}
        with self.assertRaises(AdmissionError):geometry([138,49,1782,990],96,changed)

    def test_visible_start_and_stop_templates_cannot_substitute_for_each_other_or_a_blank(self):
        paths=self.binding['icons']
        with Image.open(ROOT/paths['record-start']['path']) as start,Image.open(ROOT/paths['record-stop']['path']) as stop:
            verify_icon(start,start);verify_icon(stop,stop)
            for actual,expected in ((start,stop),(stop,start),(Image.new('RGB',(24,24),(46,49,56)),start),
                                    (Image.new('RGB',(24,24),(22,24,29)),stop)):
                with self.assertRaises(AdmissionError):verify_icon(actual,expected)
            with self.assertRaises(AdmissionError):verify_icon(start.resize((25,24)),start)


if __name__=='__main__':unittest.main()
