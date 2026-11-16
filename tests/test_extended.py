import random
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freight_intel import calibration
from freight_intel.extract import extract_signals, indicator_observations
from freight_intel.jalali import jalali_to_gregorian
from freight_intel.leads import build_lead
from freight_intel.models import Document
from freight_intel.pipeline import Pipeline
from freight_intel.report_xlsx import export_xlsx
from freight_intel.resolve import Registry, RegistryRecord
from freight_intel.scoring import Observation
from freight_intel.sector import SectorObservation, sector_observations
from freight_intel.sources.codal_monthly import observations_from_history, parse_monthly_html
from freight_intel.sources.gazette_csv import read_notices
from freight_intel.sources.ime_download import gregorian_to_jalali
from freight_intel.storage import Store

TODAY = date(2026, 11, 16)
FIX = Path(__file__).resolve().parent / "fixtures"
CLEAN = {"result": "no_match", "hits": []}


def news(text, group="news"):
    return Document(source="n", source_group=group, url="u", text=text, published_at=TODAY)


class TestSector(unittest.TestCase):
    def test_polarity(self):
        pos = sector_observations(news("رفع ممنوعیت صادرات پیاز"), TODAY)
        neg = sector_observations(news("ممنوعیت صادرات پیاز"), TODAY)
        self.assertEqual({(x.polarity, x.scope_value) for x in pos}, {(1, "0703")})
        self.assertEqual({(x.polarity, x.scope_value) for x in neg}, {(-1, "0703")})

    def test_headwind_scales_score(self):
        reg = Registry([RegistryRecord("00000000009", "کشت و صنعت گاما", activity="تولید و صادرات پیاز")])
        obs = [Observation("I7", 1.0, TODAY, "jobs", 1.0), Observation("I3", 1.0, TODAY, "news", 0.8)]
        base = build_lead("k", "کشت و صنعت گاما", [], obs, reg, CLEAN, TODAY)
        so = sector_observations(news("ممنوعیت صادرات پیاز"), TODAY)
        hit = build_lead("k", "کشت و صنعت گاما", [], obs, reg, CLEAN, TODAY, sector_obs=so)
        self.assertAlmostEqual(hit["demand"]["demand_score"], round(base["demand"]["demand_score"] * 0.8, 1), places=1)
        self.assertEqual(len(hit["demand"]["score_breakdown"]["headwinds"]), 1)
        self.assertEqual(base["lead_id"], hit["lead_id"])  # stable id

    def test_h6_confirmed_by_trade_flow(self):
        reg = Registry([RegistryRecord("00000000008", "صنایع دلتا", activity="خرما")])
        s = extract_signals(Document(source="b2b", source_group="b2b", url="u", published_at=TODAY,
                                     company_hint="صنایع دلتا", text="Buying request: dates (خرما) from Iran to دبی"))
        self.assertEqual([x.code for x in s], ["H6"])
        no = build_lead("k", "صنایع دلتا", s, [], reg, CLEAN, TODAY)
        yes = build_lead("k", "صنایع دلتا", s, [], reg, CLEAN, TODAY, trade_flows={("0804", "AE")})
        self.assertEqual((no["verification"]["level"], yes["verification"]["level"]), ("V1", "V2"))


class TestCodalMonthly(unittest.TestCase):
    def test_parse(self):
        f = parse_monthly_html((FIX / "codal_monthly_sample.html").read_text(encoding="utf-8"))
        self.assertEqual((f.production, f.domestic_sales, f.export_sales, f.confidence), (12000, 8000, 3000, "high"))
        self.assertEqual(f.period_end, jalali_to_gregorian(1405, 7, 30))

    def test_observations(self):
        hist = [(date(2026, m, 28), 10000, 9000, 1000, "") for m in range(4, 10)]
        hist.append((date(2026, 10, 28), 12000, 7000, 3000, "ref"))
        codes = {o.code: o for o in observations_from_history(hist, TODAY)}
        self.assertIn("I1", codes)  # 12000 - 10000 sold = 2000 over avg 10000 -> 0.2/0.3
        self.assertAlmostEqual(codes["I1"].strength, 0.2 / 0.3, places=2)
        self.assertIn("I2", codes)  # export share 30% vs 10%


class TestGazetteAndI8(unittest.TestCase):
    def test_notice_to_i8(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("company,national_id,published_at,text,url\n")
            f.write("صنایع اپسیلون,00000000007,1405/08/20,موضوع فعالیت شرکت به صادرات و واردات کالا تغییر یافت,https://rrk.ir/x\n")
        docs = read_notices(f.name)
        self.assertEqual(docs[0].published_at, jalali_to_gregorian(1405, 8, 20))
        self.assertEqual([o.code for o in indicator_observations(docs[0], TODAY)], ["I8"])


class TestScheduler(unittest.TestCase):
    def test_due(self):
        st = Store()
        p = Pipeline({}, st, Registry())
        now = datetime(2026, 11, 16, 12)
        self.assertTrue(p._due("gnews:x", "news", None, now, True))
        st.record_run("gnews:x", "ok", 1, now - timedelta(hours=3))
        self.assertFalse(p._due("gnews:x", "news", None, now, True))
        self.assertTrue(p._due("gnews:x", "news", 2, now, True))
        st.record_run("jobs:x", "error: boom", 0, now)
        self.assertTrue(p._due("jobs:x", "jobs", None, now, True))  # failed runs are retried


class TestCalibration(unittest.TestCase):
    def test_fit_and_probability(self):
        rnd = random.Random(7)
        hist, outcomes = [], {}
        for i in range(300):
            i3, i9 = rnd.random(), rnd.random()
            lead = {"demand": {"score_breakdown": {"contributions": {"I3": 15 * i3, "I9": 15 * i9}, "hard_signal_bonus": 0}},
                    "verification": {"level": "V2"}, "confidence": {"score": 70}}
            hist.append((f"L{i}", TODAY, lead))
            outcomes[f"L{i}"] = int(rnd.random() < 0.1 + 0.7 * i3)
        m = calibration.fit(hist, outcomes, min_samples=200)
        self.assertLess(m["brier_cv"], m["brier_base_rate"])
        self.assertGreater(m["coef"][calibration.FEATURES.index("I3")], 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            calibration.save(m, Path(tmp) / "c.json")
            prob = calibration.load_probability_fn(Path(tmp) / "c.json")
        hi = {"demand": {"score_breakdown": {"contributions": {"I3": 15}, "hard_signal_bonus": 0}},
              "verification": {"level": "V2"}, "confidence": {"score": 70}}
        lo = {"demand": {"score_breakdown": {"contributions": {}, "hard_signal_bonus": 0}},
              "verification": {"level": "V2"}, "confidence": {"score": 70}}
        self.assertGreater(prob(hi), prob(lo))

    def test_not_enough_samples(self):
        with self.assertRaises(ValueError):
            calibration.fit([], {"a": 1}, 200)


class TestMisc(unittest.TestCase):
    def test_jalali_roundtrip(self):
        d = date(2020, 1, 1)
        for _ in range(0, 2600, 13):
            y, m, dd = map(int, gregorian_to_jalali(d).split("/"))
            self.assertEqual(jalali_to_gregorian(y, m, dd), d)
            d += timedelta(days=13)

    def test_xlsx(self):
        from freight_intel.demo import run_demo
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            leads = run_demo(TODAY, tmp)
            wb = load_workbook(export_xlsx(leads, Path(tmp) / "x.xlsx"))
            self.assertEqual(wb.sheetnames, ["سرنخ‌ها", "شواهد", "نیازمند استعلام"])
            self.assertEqual(wb["سرنخ‌ها"].max_row, len(leads) + 1)
            self.assertTrue(wb["سرنخ‌ها"].sheet_view.rightToLeft)


if __name__ == "__main__":
    unittest.main()
