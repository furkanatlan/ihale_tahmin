from __future__ import annotations

import csv
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests


# Model hedefi sabit bir Yİ-ÜFE dönemine (manifest: "fiyat_bazi") güncellenmiştir.
# Bu modül tahmini, TÜİK'te yayımlanmış en son Yİ-ÜFE dönemine taşır.
AY_ADLARI = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
AY_NUMARASI = {ad.casefold(): sira for sira, ad in enumerate(AY_ADLARI, start=1)}

BASE_DIR = Path(__file__).resolve().parent
KAYIT_DOSYASI = BASE_DIR / "veri" / "yi_ufe_aylik_degisim.csv"
KAYIT_ALANLARI = ("YIL", "AY", "DONEM", "AYLIK_DEGISIM_YUZDE", "KAYNAK", "KAYNAK_ADRESI", "KAYIT_TARIHI")

TUIK_ANA_SAYFA = "https://www.tuik.gov.tr/"
TUIK_PARASAL_GUNCELLEME = "https://ty.tuik.gov.tr/"
ISTEK_ZAMAN_ASIMI_SN = 10
ISTEK_BASLIKLARI = {"User-Agent": "ihale-tahmin-uygulamasi/1.0 (+https://github.com/furkanatlan/ihale_tahmin)"}

Ilerleme = Callable[[str], None]


@dataclass(frozen=True, order=True)
class Donem:
    yil: int
    ay: int

    @property
    def etiket(self) -> str:
        return f"{AY_ADLARI[self.ay - 1]} {self.yil}"

    def sonraki(self) -> "Donem":
        return Donem(self.yil + 1, 1) if self.ay == 12 else Donem(self.yil, self.ay + 1)

    @classmethod
    def metinden(cls, metin: str) -> "Donem":
        """'Temmuz 2026' veya 'Temmuz 2026 Yİ-ÜFE' biçimindeki metni döneme çevirir."""
        eslesme = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", metin)
        if not eslesme or eslesme.group(1).casefold() not in AY_NUMARASI:
            raise ValueError(f"Dönem okunamadı: {metin!r}")
        return cls(int(eslesme.group(2)), AY_NUMARASI[eslesme.group(1).casefold()])


@dataclass
class AylikDegisim:
    donem: Donem
    yuzde: float
    kaynak: str
    kaynak_adresi: str = ""
    kayit_tarihi: str = ""


@dataclass
class TuikKontrolSonucu:
    durum: str  # "yeni_veri_eklendi" | "yeni_veri_yok" | "okunamadi" | "erisilemedi"
    mesajlar: list[str] = field(default_factory=list)
    eklenenler: list[AylikDegisim] = field(default_factory=list)
    kontrol_zamani: str = ""


@dataclass
class DegerlemeSonucu:
    baz_donem: Donem
    son_donem: Donem
    katsayi: float
    uygulanan_aylar: list[AylikDegisim]
    tuik: TuikKontrolSonucu
    eksik_donem: Donem | None = None

    @property
    def guncellendi_mi(self) -> bool:
        return self.son_donem > self.baz_donem


# --------------------------------------------------------------------------- #
# Yerel kayıt: TÜİK'ten daha önce okunmuş/doğrulanmış aylık Yİ-ÜFE değişimleri
# --------------------------------------------------------------------------- #
def kayitlari_oku(dosya: Path = KAYIT_DOSYASI) -> list[AylikDegisim]:
    if not dosya.exists():
        return []
    kayitlar: dict[Donem, AylikDegisim] = {}
    with dosya.open(encoding="utf-8-sig", newline="") as akim:
        for satir in csv.DictReader(akim):
            donem = Donem(int(satir["YIL"]), int(satir["AY"]))
            kayitlar[donem] = AylikDegisim(
                donem=donem,
                yuzde=float(str(satir["AYLIK_DEGISIM_YUZDE"]).replace(",", ".")),
                kaynak=satir.get("KAYNAK", ""),
                kaynak_adresi=satir.get("KAYNAK_ADRESI", ""),
                kayit_tarihi=satir.get("KAYIT_TARIHI", ""),
            )
    return [kayitlar[donem] for donem in sorted(kayitlar)]


def kayit_ekle(degisim: AylikDegisim, dosya: Path = KAYIT_DOSYASI) -> None:
    """Yeni ayı ekler; aynı dönem zaten varsa günceller."""
    kayitlar = {kayit.donem: kayit for kayit in kayitlari_oku(dosya)}
    if not degisim.kayit_tarihi:
        degisim.kayit_tarihi = datetime.now().strftime("%Y-%m-%d %H:%M")
    kayitlar[degisim.donem] = degisim
    dosya.parent.mkdir(parents=True, exist_ok=True)
    with dosya.open("w", encoding="utf-8-sig", newline="") as akim:
        yazici = csv.DictWriter(akim, fieldnames=KAYIT_ALANLARI)
        yazici.writeheader()
        for donem in sorted(kayitlar):
            kayit = kayitlar[donem]
            yazici.writerow(
                {
                    "YIL": donem.yil,
                    "AY": donem.ay,
                    "DONEM": donem.etiket,
                    "AYLIK_DEGISIM_YUZDE": f"{kayit.yuzde:.2f}",
                    "KAYNAK": kayit.kaynak,
                    "KAYNAK_ADRESI": kayit.kaynak_adresi,
                    "KAYIT_TARIHI": kayit.kayit_tarihi,
                }
            )


# --------------------------------------------------------------------------- #
# TÜİK çevrimiçi kontrol
# --------------------------------------------------------------------------- #
_BULTEN_BAGLANTISI = re.compile(r"SliderUrl\('([^']+)'[^>]*>\s*([^<]+?)\s*<", re.IGNORECASE)
_YI_UFE_BASLIK = re.compile(
    r"(?:Yurt\s*İçi\s+)?Üretici\s+Fiyat\s+Endeks(?:i|leri)\s*,?\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})",
    re.IGNORECASE,
)
# TÜİK bülten cümlesi: "Yİ-ÜFE'de (2003=100) 2026 yılı Eylül ayında bir önceki aya göre %2,07 ... artış"
# veya başlık: "Yİ-ÜFE yıllık %27,38, aylık %2,07 arttı"
_AYLIK_DEGISIM = (
    re.compile(r"Yİ-ÜFE.{0,160}?bir\s+önceki\s+aya\s+göre\s+%\s*(-?\d+[,.]\d+)\s*(artış|azalış|düşüş)?", re.S),
    re.compile(r"Yİ-ÜFE.{0,80}?aylık\s+%\s*(-?\d+[,.]\d+)\s*(arttı|azaldı|düştü)?", re.S),
)


def _sayfa_metni(adres: str) -> str:
    yanit = requests.get(adres, headers=ISTEK_BASLIKLARI, timeout=ISTEK_ZAMAN_ASIMI_SN)
    yanit.raise_for_status()
    return html.unescape(yanit.text)


def _duz_metin(sayfa: str) -> str:
    sayfa = re.sub(r"<(script|style)\b.*?</\1>", " ", sayfa, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", sayfa))


def yi_ufe_bultenlerini_bul(ana_sayfa: str) -> dict[Donem, str]:
    """TÜİK ana sayfasındaki bülten listesinden Yİ-ÜFE bültenlerinin dönem ve adreslerini çıkarır."""
    bultenler: dict[Donem, str] = {}
    for adres, baslik in _BULTEN_BAGLANTISI.findall(ana_sayfa):
        if re.search(r"Hizmet|Yurt\s*Dışı|Tarım", baslik, re.I):
            continue
        eslesme = _YI_UFE_BASLIK.search(baslik)
        if eslesme and eslesme.group(1).casefold() in AY_NUMARASI:
            bultenler[Donem(int(eslesme.group(2)), AY_NUMARASI[eslesme.group(1).casefold()])] = adres
    return bultenler


def aylik_degisimi_oku(metin: str) -> float | None:
    """Bülten metninden Yİ-ÜFE'nin bir önceki aya göre değişimini (yüzde) okur."""
    for desen in _AYLIK_DEGISIM:
        eslesme = desen.search(metin)
        if eslesme:
            deger = float(eslesme.group(1).replace(",", "."))
            yon = (eslesme.group(2) or "").casefold()
            return -abs(deger) if yon.startswith(("azal", "düş")) else deger
    return None


def tuik_kontrol_et(son_bilinen: Donem, ilerleme: Ilerleme | None = None) -> TuikKontrolSonucu:
    """TÜİK sitesinde son bilinen dönemden daha yeni Yİ-ÜFE verisi arar ve bulunursa kaydeder."""
    bildir = ilerleme or (lambda _mesaj: None)
    sonuc = TuikKontrolSonucu(durum="yeni_veri_yok", kontrol_zamani=datetime.now().strftime("%d.%m.%Y %H:%M"))

    def kaydet(mesaj: str) -> None:
        sonuc.mesajlar.append(mesaj)
        bildir(mesaj)

    kaydet(f"🌐 TÜİK sitesine bağlanılıyor: {TUIK_ANA_SAYFA}")
    try:
        ana_sayfa = _sayfa_metni(TUIK_ANA_SAYFA)
    except requests.RequestException as hata:
        sonuc.durum = "erisilemedi"
        kaydet(f"❌ TÜİK sitesine erişilemedi ({type(hata).__name__}).")
        return sonuc

    kaydet("🔎 Yayımlanan haber bültenleri arasında Yurt İçi ÜFE (Yİ-ÜFE) bülteni aranıyor…")
    bultenler = yi_ufe_bultenlerini_bul(ana_sayfa)
    yeniler = {donem: adres for donem, adres in bultenler.items() if donem > son_bilinen}
    if bultenler:
        kaydet("📄 Bulunan Yİ-ÜFE bültenleri: " + ", ".join(d.etiket for d in sorted(bultenler)))
    else:
        kaydet("ℹ️ TÜİK ana sayfasındaki güncel bülten listesinde Yİ-ÜFE bülteni yer almıyor.")
    if not yeniler:
        kaydet(f"✅ {son_bilinen.etiket} sonrasına ait yeni bir Yİ-ÜFE verisi bulunamadı.")
        return sonuc

    beklenen = son_bilinen.sonraki()
    for donem in sorted(yeniler):
        if donem != beklenen:
            kaydet(f"⚠️ {beklenen.etiket} verisi eksik olduğu için {donem.etiket} zincire eklenemedi.")
            sonuc.durum = "okunamadi" if not sonuc.eklenenler else sonuc.durum
            break
        kaydet(f"📥 {donem.etiket} Yİ-ÜFE bülteni okunuyor…")
        try:
            oran = aylik_degisimi_oku(_duz_metin(_sayfa_metni(yeniler[donem])))
        except requests.RequestException:
            oran = None
        if oran is None:
            kaydet(
                f"⚠️ {donem.etiket} bülteni yayımlanmış ancak aylık değişim oranı sayfadan otomatik "
                "okunamadı. Oranı TÜİK'ten alıp kayda elle ekleyebilirsiniz."
            )
            if not sonuc.eklenenler:
                sonuc.durum = "okunamadi"
            break
        degisim = AylikDegisim(donem, oran, "TÜİK haber bülteni (otomatik okundu)", yeniler[donem])
        kayit_ekle(degisim)
        sonuc.eklenenler.append(degisim)
        sonuc.durum = "yeni_veri_eklendi"
        kaydet(f"✅ {donem.etiket}: aylık %{oran:.2f} değişim kayda eklendi.".replace(".", ",", 1))
        beklenen = donem.sonraki()
    return sonuc


# --------------------------------------------------------------------------- #
# Yeniden değerleme
# --------------------------------------------------------------------------- #
def degerleme_katsayisi(baz: Donem, kayitlar: list[AylikDegisim]) -> tuple[float, list[AylikDegisim], Donem | None]:
    """Baz dönemden sonraki kesintisiz aylık değişimleri zincirleyerek katsayı üretir."""
    harita = {kayit.donem: kayit for kayit in kayitlar}
    katsayi, uygulanan, donem = 1.0, [], baz.sonraki()
    while donem in harita:
        katsayi *= 1 + harita[donem].yuzde / 100
        uygulanan.append(harita[donem])
        donem = donem.sonraki()
    sonraki_kayitlar = [d for d in harita if d > donem]
    return katsayi, uygulanan, (donem if sonraki_kayitlar else None)


def yeniden_degerleme_hazirla(baz: Donem, ilerleme: Ilerleme | None = None) -> DegerlemeSonucu:
    """TÜİK'i kontrol eder, ardından baz dönemden en son kayıtlı döneme katsayı hesaplar."""
    mevcut = kayitlari_oku()
    _, uygulanan, _ = degerleme_katsayisi(baz, mevcut)
    son_bilinen = uygulanan[-1].donem if uygulanan else baz
    tuik = tuik_kontrol_et(son_bilinen, ilerleme)

    katsayi, uygulanan, eksik = degerleme_katsayisi(baz, kayitlari_oku())
    son_donem = uygulanan[-1].donem if uygulanan else baz
    return DegerlemeSonucu(baz, son_donem, katsayi, uygulanan, tuik, eksik)
