import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freight_intel.extract import extract_signals, find_company, parse_quantity
from freight_intel.jalali import jalali_to_gregorian, parse_any_date
from freight_intel.models import Document
from freight_intel.normalize import normalize
from freight_intel.resolve import Registry, RegistryRecord, similarity
from freight_intel.scoring import Observation, i9_periodicity, score_company
from freight_intel.verify import detect_brokers, verify

TODAY = date(2026, 11, 16)


def doc(text, group="tenders", **kw):
    return Document(source="t", source_group=group, url="u", text=text, published_at=TODAY, **kw)


class TestNormalize(unittest.TestCase):
    def test_digits_and_letters(self):
        self.assertEqual(normalize("۱۲۳ كيك ٤٥"), "123 کیک 45")

    def test_zwnj_to_space(self):
        self.assertEqual(normalize("پلی\u200cاتیلن"), "پلی اتیلن")


class TestJalali(unittest.TestCase):
    def test_known_dates(self):
        self.assertEqual(jalali_to_gregorian(1403, 1, 1), date(2024, 3, 20))
        self.assertEqual(jalali_to_gregorian(1405, 8, 25), date(2026, 11, 16))
        self.assertEqual(parse_any_date("۱۴۰۵/۰۸/۲۵"), date(2026, 11, 16))


class TestExtract(unittest.TestCase):
    def test_tender(self):
        s = extract_signals(doc("استعلام بها حمل ۳٬۰۰۰ تن میلگرد از بندر شهید رجایی"))
        self.assertEqual([x.code for x in s], ["H1"])
        self.assertEqual((s[0].qty_value, s[0].qty_unit), (3000.0, "MT"))
        self.assertEqual((s[0].commodity, s[0].hs4, s[0].mode_hint), ("میلگرد", "7214", "sea"))

    def test_thousand_tons_and_containers(self):
        self.assertEqual(parse_quantity(normalize("۵۰ هزار تن")), (50000.0, "MT"))
        self.assertEqual(parse_quantity(normalize("۱۰ کانتینر ۴۰ فوت")), (20.0, "TEU"))

    def test_truck_size_is_not_cargo(self):
        self.assertEqual(parse_quantity(normalize("نیاز به تریلی ۲۴ تنی")), (None, None))

    def test_border_implies_country(self):
        s = extract_signals(doc("اعلام بار پسته به مرز دوغارون", "social"))
        self.assertEqual((s[0].exit_point, s[0].destination_country, s[0].mode_hint), ("دوغارون", "AF", "road"))

    def test_no_signal(self):
        self.assertEqual(extract_signals(doc("گزارش هواشناسی امروز")), [])

    def test_company_regex_stops_at_verb(self):
        self.assertEqual(find_company(normalize("شرکت آلفا اعلام کرد که")), "شرکت آلفا")


class TestScoring(unittest.TestCase):
    def test_formula_synergy_and_cap(self):
        obs = [Observation("I3", 1.0, TODAY, "codal"), Observation("I7", 1.0, TODAY, "jobs", 0.8)]
        r = score_company(obs, TODAY)
        self.assertAlmostEqual(r.demand_score, 15 + 8 * 0.8 + 10, places=1)
        self.assertFalse(r.diversity_capped)
        one = score_company([Observation(c, 1.0, TODAY, "codal") for c in ("I1", "I2", "I3", "I9")] +
                            [Observation("I5", 1.0, TODAY, "codal")], TODAY)
        self.assertTrue(one.diversity_capped)
        self.assertEqual(one.demand_score, 59.0)

    def test_definite_needs_hard_signal(self):
        obs = [Observation(c, 1.0, TODAY, g) for c, g in
               (("I1", "codal"), ("I2", "codal"), ("I3", "codal"), ("I9", "ime"), ("I5", "exhibitions"), ("I7", "jobs"))]
        self.assertEqual(score_company(obs, TODAY).demand_class, "high")
        self.assertEqual(score_company(obs, TODAY, hard_verified=True).demand_class, "definite")

    def test_decay(self):
        old = score_company([Observation("I7", 1.0, date(2026, 9, 17), "jobs", 1.0)], TODAY)
        self.assertAlmostEqual(old.contributions["I7"], 4.0, places=1)  # 60 days = one half-life

    def test_periodicity(self):
        ds = [date(2026, m, 1) for m in range(6, 12)]
        o = i9_periodicity(ds, TODAY)
        self.assertGreater(o.strength, 0.9)
        self.assertTrue(o.window[0] <= date(2026, 12, 1) <= o.window[1])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.rec = RegistryRecord("00000000001", "فولاد آلفا", prior_export=True, registered_at=date(2010, 1, 1))

    def test_levels(self):
        s = extract_signals(doc("استعلام بها حمل میلگرد", "tenders"))
        self.assertEqual(verify(s, None, "", set(), TODAY).level, "V0")
        self.assertEqual(verify(s, self.rec, "ref", set(), TODAY).level, "V3")

    def test_broker_detection(self):
        sigs = []
        for i in range(5):
            sigs += extract_signals(doc("اعلام بار پسته تماس 09120000000", "social", channel=f"c{i}"))
        hashes, phones = detect_brokers(sigs)
        v = verify(sigs, None, "", set(), TODAY, hashes, phones)
        self.assertTrue(v.suspected_broker)
        self.assertTrue(v.rejected)

    def test_registry_fuzzy(self):
        reg = Registry([self.rec])
        rec, sim = reg.match("شرکت فولاد آلفا (سهامی خاص)")
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(similarity("فولاد آلفا", "فولاد آلفا سهامی عام"), 0.99)


class TestDemo(unittest.TestCase):
    def test_end_to_end(self):
        import tempfile
        from freight_intel.demo import run_demo
        with tempfile.TemporaryDirectory() as tmp:
            leads = run_demo(TODAY, tmp)
        by = {L["shipper"]["company_name"]: L for L in leads}
        alpha, beta = by["فولاد نمونه آلفا"], by["پتروشیمی نمونه بتا"]
        self.assertEqual(alpha["demand"]["demand_type"], "immediate")
        self.assertEqual(alpha["verification"]["level"], "V3")
        self.assertEqual(alpha["demand"]["demand_class"], "definite")
        self.assertFalse(alpha["ready_for_sales"])  # sanctions not checked in demo
        self.assertEqual(beta["verification"]["level"], "V2")
        self.assertIn(None, by)  # broker-like telegram posts -> identification queue
        self.assertTrue(by[None]["verification"]["rejected"])


if __name__ == "__main__":
    unittest.main()
