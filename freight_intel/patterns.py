"""Detection patterns and gazetteers. All literals are compared after normalize()."""
from __future__ import annotations

import re

from .normalize import normalize


def term_rx(term: str) -> str:
    """Regex for a term that tolerates space or ZWNJ between its tokens."""
    return r"\s*".join(re.escape(tok) for tok in normalize(term).split())


# ---- Hard (immediate-demand) signals, Section 2 ----------------------------
HARD_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    "H1": (re.compile(r"(مناقصه|استعلام\s*(?:بها|قیمت)|فراخوان)[^\n]{0,60}?"
                      r"(حمل|ترانزیت|باربری|کانتینر|فورواردر|لجستیک)"),
           "مناقصه یا استعلام حمل"),
    "H2": (re.compile(r"\b(FOB|FCA)\b|فوب|تحویل\s*(?:در\s*)?(?:بندر|مرز|گمرک)|"
                      r"رینگ\s*صادراتی|تالار\s*صادراتی", re.I),
           "معامله صادراتی با تحویل FOB یا مرزی"),
    "H3": (re.compile(r"انعقاد\s*قرارداد[^\n]{0,40}صادرات|فروش\s*صادراتی|"
                      r"بارگیری\s*محموله|صادرات\s*محموله"),
           "افشای قرارداد صادراتی یا بارگیری"),
    "H4": (re.compile(r"اعلام\s*بار|بار\s*آماده|نیاز(?:مند)?\s*به\s*(?:کامیون|تریلی|کانتینر|واگن)|"
                      r"\b(?:cargo|load)\s+(?:available|ready)\b", re.I),
           "اعلام بار در کانال یا بورس بار"),
    "H5": (re.compile(r"(?:نخستین|اولین)\s*محموله|صادرات[^\n]{0,30}آغاز\s*شد"),
           "خبر نخستین محموله یا آغاز صادرات"),
}
# H6 (foreign buying request for Iranian goods) needs two conditions together
H6_BUY_RX = re.compile(r"\b(buying\s+request|rfq|looking\s+for|we\s+need|request\s+for\s+quotation)\b", re.I)
H6_IRAN_RX = re.compile(r"\biran(?:ian)?\b|ایران", re.I)

# ---- Field extraction -------------------------------------------------------
QTY_RX = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(هزار\s*)?(تن|tonnes?|tons?|mt)\b", re.I)
CONTAINER_RX = re.compile(r"(\d+)\s*(?:دستگاه\s*|عدد\s*|x\s*)?(?:کانتینر|container)s?\s*(20|40)\s*(?:فوت|ft|feet|')?", re.I)
MOBILE_RX = re.compile(r"(?<!\d)(?:\+98|0098|0)?9\d{9}(?!\d)")
INCOTERM_RX = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b", re.I)
MODE_HINTS = {
    "sea": re.compile(r"کشتی|دریایی|بندر|bulk|فله\s*دریایی|کانتینر|vessel", re.I),
    "rail": re.compile(r"واگن|قطار|ریلی|راه\s*آهن|rail", re.I),
    "road": re.compile(r"کامیون|تریلی|جاده\s*ای|یخچال\s*دار|truck", re.I),
}

# Exit points: name -> (mode, neighbouring country ISO2 or None for sea)
EXIT_POINTS = {
    "بازرگان": ("road", "TR"),  # «رازی» و «سرو» عمدا حذف شده‌اند: با نام شرکت‌ها تداخل دارند
    "سرخس": ("rail", "TM"), "اینچه برون": ("rail", "TM"), "لطف آباد": ("road", "TM"),
    "باجگیران": ("road", "TM"), "آستارا": ("road", "AZ"), "جلفا": ("road", "AZ"),
    "نوردوز": ("road", "AM"), "میرجاوه": ("road", "PK"), "دوغارون": ("road", "AF"),
    "میلک": ("road", "AF"), "مهران": ("road", "IQ"), "پرویزخان": ("road", "IQ"),
    "باشماق": ("road", "IQ"), "تمرچین": ("road", "IQ"), "شلمچه": ("road", "IQ"),
    "چذابه": ("road", "IQ"), "شهید رجایی": ("sea", None), "بندرعباس": ("sea", None),
    "بندر عباس": ("sea", None), "بندر امام خمینی": ("sea", None), "بوشهر": ("sea", None),
    "چابهار": ("sea", None), "انزلی": ("sea", None), "امیرآباد": ("sea", None),
    "نوشهر": ("sea", None), "خرمشهر": ("sea", None), "عسلویه": ("sea", None),
}
DESTINATIONS = {
    "ترکیه": "TR", "مرسین": "TR", "استانبول": "TR", "عراق": "IQ", "بغداد": "IQ", "اربیل": "IQ",
    "سلیمانیه": "IQ", "بصره": "IQ", "ام القصر": "IQ", "افغانستان": "AF", "کابل": "AF", "هرات": "AF",
    "پاکستان": "PK", "کراچی": "PK", "روسیه": "RU", "مسکو": "RU", "آستراخان": "RU",
    "قزاقستان": "KZ", "آلماتی": "KZ", "ترکمنستان": "TM", "عشق آباد": "TM", "ازبکستان": "UZ",
    "تاشکند": "UZ", "تاجیکستان": "TJ", "قرقیزستان": "KG", "آذربایجان": "AZ", "باکو": "AZ",
    "ارمنستان": "AM", "گرجستان": "GE", "امارات": "AE", "دبی": "AE", "جبل علی": "AE",
    "عمان": "OM", "قطر": "QA", "کویت": "KW", "عربستان": "SA", "بحرین": "BH",
    "چین": "CN", "ارومچی": "CN", "ییوو": "CN", "هند": "IN", "سوریه": "SY", "لبنان": "LB",
}
# Commodity -> (HS4, industry). HS4 is the usual heading; confirm per product.
COMMODITIES = {
    "پلی اتیلن": ("3901", "petrochemical"), "پلی پروپیلن": ("3902", "petrochemical"),
    "متانول": ("2905", "petrochemical"), "اوره": ("3102", "petrochemical"),
    "آمونیاک": ("2814", "petrochemical"), "قیر": ("2715", "petrochemical"),
    "گوگرد": ("2503", "petrochemical"), "میلگرد": ("7214", "steel"),
    "شمش فولاد": ("7207", "steel"), "بیلت": ("7207", "steel"), "اسلب": ("7207", "steel"),
    "ورق فولادی": ("7208", "steel"), "آهن اسفنجی": ("7203", "steel"),
    "کنسانتره آهن": ("2601", "mining"), "گندله": ("2601", "mining"), "کاتد مس": ("7403", "mining"),
    "سیمان": ("2523", "construction"), "کلینکر": ("2523", "construction"),
    "کاشی": ("6907", "construction"), "سرامیک": ("6907", "construction"),
    "سنگ ساختمانی": ("6802", "construction"), "پسته": ("0802", "agri"),
    "خرما": ("0804", "agri"), "زعفران": ("0910", "agri"), "کشمش": ("0806", "agri"),
    "سیب زمینی": ("0701", "agri"), "پیاز": ("0703", "agri"), "هندوانه": ("0807", "agri"),
    "پرتقال": ("0805", "agri"), "مرکبات": ("0805", "agri"), "گوجه فرنگی": ("0702", "agri"),
    "لوله فولادی": ("7306", "industrial"), "کابل": ("8544", "industrial"),
}

COMPANY_PREFIX_RX = re.compile(
    r"(?:شرکت|پتروشیمی|فولاد|سیمان|صنایع|گروه\s*صنعتی|کشت\s*و\s*صنعت|معدنی|بازرگانی)\s+"
    r"[^\s،,.:؛!؟\d()]+(?:\s+[^\s،,.:؛!؟\d()]+){0,3}")
COMPANY_STOPWORDS = {"اعلام", "در", "به", "از", "با", "که", "برای", "جهت", "را", "و", "نیز",
                     "قصد", "اقدام", "تن", "محموله", "صادرات", "اعلام", "کرد", "شد", "است"}


def compile_gazetteer(d: dict) -> list[tuple[re.Pattern, str, object]]:
    items = sorted(d.items(), key=lambda kv: -len(kv[0]))
    return [(re.compile(r"(?<!\w)" + term_rx(k) + r"(?!\w)"), k, v) for k, v in items]


EXIT_GAZ = compile_gazetteer(EXIT_POINTS)
DEST_GAZ = compile_gazetteer(DESTINATIONS)
COMMODITY_GAZ = compile_gazetteer(COMMODITIES)
