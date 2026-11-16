import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freight_intel.demo import run_demo
from freight_intel.monday_export import GROUPS, T, format_value, lead_group, push_leads


class FakeClient:
    """Records GraphQL calls; pretends the board has every column and group."""
    types = {"نوع نیاز": "status", "طبقه تقاضا": "status", "شیوه حمل": "status", "سطح راستی‌آزمایی": "status",
             "غربالگری تحریمی": "status", "وضعیت پیگیری": "status", "صنعت": "dropdown", "واحد": "dropdown",
             "امتیاز تقاضا": "numbers", "امتیاز اطمینان": "numbers", "تناژ یا حجم": "numbers", "بازه حمل": "timeline",
             "دلایل کسر امتیاز": "long_text", "شواهد و منابع": "long_text", "نیازمند استعلام": "long_text"}

    def __init__(self, existing=()):
        self.calls, self.existing = [], set(existing)

    def gql(self, q, v=None):
        self.calls.append((q, v))
        if q.startswith("query($b:[ID!])"):
            return {"boards": [{"columns": [{"id": f"c{i}", "title": t, "type": self.types.get(t, "text")}
                                            for i, t in enumerate(T.values())],
                                "groups": [{"id": f"g{i}", "title": t} for i, t in enumerate(GROUPS.values())]}]}
        if "items_page_by_column_values" in q:
            return {"items_page_by_column_values": {"items": [{"id": "1"}] if v["v"] in self.existing else []}}
        return {"x": {"id": "1"}}


class TestMondayExport(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.leads = run_demo(date(2026, 11, 16), tmp)

    def test_formats(self):
        self.assertEqual(format_value("status", "قطعی"), {"label": "قطعی"})
        self.assertEqual(format_value("timeline", ("2026-11-16", "2026-12-31")), {"from": "2026-11-16", "to": "2026-12-31"})
        self.assertIsNone(format_value("text", None))

    def test_create_then_update_keeps_sales_columns(self):
        c = FakeClient()
        self.assertEqual(push_leads(self.leads, 1, c)["created"], len(self.leads))
        created = [json.loads(v["v"]) for q, v in c.calls if q.startswith("mutation") and "create_item" in q]
        follow_col = f"c{list(T).index('follow_up')}"
        self.assertTrue(all(follow_col in vals for vals in created))
        c2 = FakeClient(existing={L["lead_id"] for L in self.leads})
        self.assertEqual(push_leads(self.leads, 1, c2)["updated"], len(self.leads))
        updated = [json.loads(v["v"]) for q, v in c2.calls if "change_multiple_column_values" in q]
        self.assertTrue(all(follow_col not in vals for vals in updated))

    def test_groups(self):
        self.assertEqual({lead_group(L) for L in self.leads},
                         {GROUPS["review"], GROUPS["rejected"]})  # nothing ready: sanctions not checked


if __name__ == "__main__":
    unittest.main()
