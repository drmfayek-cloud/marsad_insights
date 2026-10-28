"""Screen text in English and Arabic. KPI names and definitions come from config/kpis.yaml."""
from flask import g

T = {
    "app": ("MARSAD Insights", "مرصد - لوحة المؤشرات"),
    "tagline": ("CNHI audit and approval of private-sector healthcare procurement",
                "مشروع تدقيق واعتماد مشتريات الخدمات الصحية من القطاع الخاص"),
    "period": ("Period", "الفترة"),
    "all_months": ("All months", "كل الأشهر"),
    "tpa": ("TPA", "شركة إدارة المطالبات"),
    "all_tpas": ("All TPAs", "كل الشركات"),
    "apply": ("Apply", "تطبيق"),
    "approved": ("Approved", "معتمد"),
    "provisional": ("Provisional", "أولي"),
    "approved_note": ("Figures frozen when CNHI approved this month's report.", "أرقام مثبتة منذ اعتماد المركز لتقرير هذا الشهر."),
    "provisional_note": ("Live figures; they become approved when the month is closed.",
                         "أرقام حية، وتصبح معتمدة عند إقفال الشهر."),
    "filtered_note": ("Filtered view: computed live from the published data.", "عرض مصفى: محسوب مباشرة من البيانات المنشورة."),
    "capture": ("Data capture in progress", "البيانات قيد الاستكمال"),
    "definition": ("Definition", "التعريف"),
    "source": ("Source", "المصدر"),
    "caveat": ("Read with care", "ملاحظة"),
    "as_of": ("Data as of", "البيانات حتى"),
    "headline": ("Headline", "المؤشرات الرئيسية"),
    "secondary": ("Also tracked", "مؤشرات مساندة"),
    "trend": ("Monthly trend", "الاتجاه الشهري"),
    "sign_in": ("Sign in", "تسجيل الدخول"),
    "sign_out": ("Sign out", "تسجيل الخروج"),
    "email": ("Email", "البريد الإلكتروني"),
    "password": ("Password", "كلمة المرور"),
    "code": ("Authenticator code", "رمز تطبيق المصادقة"),
    "account": ("Account", "الحساب"),
    "data": ("Data uploads", "تحميل البيانات"),
    "periods": ("Close a month", "إقفال شهر"),
    "users": ("Users", "المستخدمون"),
    "audit": ("Audit log", "سجل التدقيق"),
    "lang_switch": ("العربية", "English"),
    "no_data_yet": ("No published data yet. An administrator uploads the workbooks under Data uploads.",
                    "لا توجد بيانات منشورة بعد. يحمل المسؤول المصنفات من صفحة تحميل البيانات."),
    "not_split": ("Not split by TPA", "غير موزع حسب الشركة"),
    "quarter": ("Quarter", "الربع"),
    "encounters": ("Encounters reviewed", "الحالات المراجعة"),
    "received": ("Received", "المستلمة"),
    "reviewed": ("Reviewed", "المراجعة"),
    "flags": ("Confirmed flags", "الملاحظات المؤكدة"),
    "amount": ("Amount (SAR)", "القيمة (ريال)"),
    "count": ("Count", "العدد"),
    "per_day": ("per day", "يوميا"),
    "hours": ("hours", "ساعة"),
    "estimated": ("estimated", "تقديرية"),
    "of": ("of", "من"),
    "demo": ("Demo system with made-up data.", "نظام تجريبي ببيانات افتراضية."),
}


def lang():
    return getattr(g, "lang", "en")


def t(key):
    en, ar = T.get(key, (key, key))
    return ar if lang() == "ar" else en


def pick(en, ar):
    return ar if lang() == "ar" and ar else en
