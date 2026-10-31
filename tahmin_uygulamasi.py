from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from model_schema import FEATURE_LABELS
from tahmin_servisi import (
    format_tl,
    load_prediction_artifacts,
    predict_current_contract_values,
    training_range_warnings,
)
from yeniden_degerleme import (
    TUIK_PARASAL_GUNCELLEME,
    AylikDegisim,
    Donem,
    degerleme_katsayisi,
    kayit_ekle,
    kayitlari_oku,
    yeniden_degerleme_hazirla,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "sonuclar"


st.set_page_config(
    page_title="Güncel Sözleşme Bedeli Tahmini",
    page_icon="₺",
    layout="wide",
)

st.title("Güncel ihale sözleşme bedeli tahmini")
st.caption(
    "Dört teknik girdiden güncel sözleşme bedelini en iyi üç modelle tahmin eder. Modeller Temmuz 2026 "
    "Yİ-ÜFE fiyat bazında eğitilmiştir; her tahminden önce TÜİK sitesi kontrol edilerek sonuç en son "
    "yayımlanmış Yİ-ÜFE dönemine yeniden değerlenir. Para birimi TL'dir."
)


@st.cache_resource
def get_artifacts() -> tuple[dict, dict]:
    return load_prediction_artifacts(OUTPUT_DIR)


try:
    manifest, models = get_artifacts()
except (FileNotFoundError, ValueError) as exc:
    st.error(str(exc))
    st.code(
        r".\.venv\Scripts\python.exe .\ihale_maliyet_modelleme.py "
        r"--excel .\VERİLER_GÜNCELLENMİŞ.xlsx --output .\sonuclar",
        language="powershell",
    )
    st.stop()

ranges = manifest["egitim_verisi_ozellik_araliklari"]
base_period = Donem.metinden(manifest["fiyat_bazi"])

with st.sidebar:
    st.header("📅 Yİ-ÜFE yeniden değerleme")
    records = kayitlari_oku()
    _, applied, _ = degerleme_katsayisi(base_period, records)
    last_period = applied[-1].donem if applied else base_period
    st.caption(
        f"Model fiyat bazı: **{base_period.etiket}** · Kayıtlı son dönem: **{last_period.etiket}**. "
        "Uygulama her tahminde TÜİK sitesini kontrol eder; yeni veri okunursa kayda otomatik eklenir."
    )
    if records:
        st.dataframe(
            pd.DataFrame(
                [{"Dönem": r.donem.etiket, "Aylık %": r.yuzde, "Kaynak": r.kaynak} for r in records]
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander("➕ TÜİK oranını elle ekle"):
        st.caption(
            "TÜİK bülteni otomatik okunamadığında, Yİ-ÜFE'nin bir önceki aya göre değişim oranını TÜİK "
            f"haber bülteninden veya [Parasal Değeri Güncelleme Aracı]({TUIK_PARASAL_GUNCELLEME})'ndan "
            "alıp buraya girebilirsiniz."
        )
        with st.form("manual_index_form", clear_on_submit=True):
            next_period = last_period.sonraki()
            st.text_input("Dönem", value=next_period.etiket, disabled=True)
            monthly_change = st.number_input("Aylık değişim (%)", value=0.0, step=0.01, format="%.2f")
            source_note = st.text_input("Kaynak", value=f"TÜİK Yİ-ÜFE haber bülteni, {next_period.etiket}")
            if st.form_submit_button("Kayda ekle"):
                kayit_ekle(AylikDegisim(next_period, float(monthly_change), source_note + "; elle girildi"))
                st.rerun()
loaded_models = ", ".join(item["model_adi"] for item in manifest["en_iyi_3_model"])
st.caption(f"Yüklü model seti: {loaded_models} · Eğitim çıktısı: {manifest['olusturma_tarihi']}")

st.subheader("Proje girdileri")
with st.form("contract_prediction_form"):
    left, right = st.columns(2)
    with left:
        pipe_diameter = st.number_input(
            FEATURE_LABELS["BORU_CAPI"],
            min_value=0.0,
            value=float(ranges["BORU_CAPI"]["medyan"]),
            step=1.0,
            help="Eğitim verisinde boru çapı inç cinsindedir.",
        )
        line_length = st.number_input(
            FEATURE_LABELS["HAT_UZUNLUGU_KM"],
            min_value=0.0,
            value=float(ranges["HAT_UZUNLUGU_KM"]["medyan"]),
            step=0.1,
            format="%.2f",
        )
    with right:
        valve_count = st.number_input(
            FEATURE_LABELS["HAT_VANASI_SAYISI"],
            min_value=0,
            value=int(round(ranges["HAT_VANASI_SAYISI"]["medyan"])),
            step=1,
        )
        pig_station_count = st.number_input(
            FEATURE_LABELS["PIG_ISTASYONU_SAYISI"],
            min_value=0,
            value=int(round(ranges["PIG_ISTASYONU_SAYISI"]["medyan"])),
            step=1,
        )
    submitted = st.form_submit_button(
        "Güncel sözleşme bedelini tahmin et", type="primary", width="stretch"
    )

if submitted:
    values = {
        "BORU_CAPI": pipe_diameter,
        "HAT_UZUNLUGU_KM": line_length,
        "HAT_VANASI_SAYISI": valve_count,
        "PIG_ISTASYONU_SAYISI": pig_station_count,
    }

    extrapolation = training_range_warnings(values, manifest)
    if extrapolation:
        st.warning(
            "Bazı girdiler eğitim verisinin dışında; bu nedenle tahmin ekstrapolasyondur ve daha "
            "yüksek belirsizlik taşır:\n\n- " + "\n- ".join(extrapolation)
        )

    with st.status("🔎 TÜİK sitesinde güncel Yİ-ÜFE verisi aranıyor…", expanded=True) as status:
        revaluation = yeniden_degerleme_hazirla(base_period, ilerleme=st.write)
        tuik_state = revaluation.tuik.durum
        status.update(
            label={
                "yeni_veri_eklendi": "✅ TÜİK'te yeni Yİ-ÜFE verisi bulundu ve eklendi",
                "yeni_veri_yok": "✅ TÜİK kontrol edildi: yeni Yİ-ÜFE verisi yok",
                "okunamadi": "⚠️ TÜİK kontrol edildi: yeni veri okunamadı",
                "erisilemedi": "❌ TÜİK sitesine erişilemedi",
            }[tuik_state],
            state="error" if tuik_state == "erisilemedi" else "complete",
            expanded=False,
        )

    factor_text = f"{revaluation.katsayi:.4f}".replace(".", ",")
    chain_text = ", ".join(
        f"{item.donem.etiket} %{item.yuzde:.2f}".replace(".", ",") for item in revaluation.uygulanan_aylar
    )
    period_text = (
        f"Tahminler **{revaluation.baz_donem.etiket} → {revaluation.son_donem.etiket}** Yİ-ÜFE ile "
        f"yeniden değerlendi (katsayı **{factor_text}**; {chain_text})."
        if revaluation.guncellendi_mi
        else f"Tahminler modelin fiyat bazı olan **{revaluation.baz_donem.etiket}** Yİ-ÜFE düzeyindedir."
    )
    checked_at = f"TÜİK kontrol zamanı: {revaluation.tuik.kontrol_zamani}."
    if tuik_state == "yeni_veri_eklendi":
        added = ", ".join(item.donem.etiket for item in revaluation.tuik.eklenenler)
        st.success(f"TÜİK'ten yeni Yİ-ÜFE verisi eklendi: **{added}**. {period_text} {checked_at}")
    elif tuik_state == "yeni_veri_yok":
        st.info(
            f"TÜİK'te {revaluation.son_donem.etiket} sonrasına ait yeni Yİ-ÜFE verisi bulunamadı; yeni "
            f"değerleme eklenmedi. Son değerleme **{revaluation.son_donem.etiket}** dönemine aittir. "
            f"{period_text} {checked_at}"
        )
    else:
        st.warning(
            "TÜİK sitesinde yeni Yİ-ÜFE verisi bulunamadı veya okunamadı; yeni değerleme eklenmedi. "
            f"Tahmin, son kayıtlı değerleme olan **{revaluation.son_donem.etiket}** dönemine göre "
            f"yapılmıştır. {period_text} {checked_at}"
        )
    if revaluation.eksik_donem:
        st.warning(
            f"{revaluation.eksik_donem.etiket} Yİ-ÜFE oranı kayıtta eksik olduğu için sonraki aylar "
            "zincire eklenmedi."
        )

    predictions = predict_current_contract_values(values, manifest, models)
    predictions["Güncel Tahmin (TL)"] = predictions["Tahmin (TL)"] * revaluation.katsayi
    st.subheader(f"En iyi 3 modelin tahmini ({revaluation.son_donem.etiket} fiyatlarıyla)")
    metric_columns = st.columns(3)
    for column, row in zip(metric_columns, predictions.to_dict("records")):
        with column:
            st.metric(
                label=f"{row['Sıra']}. {row['Model']}",
                value=format_tl(row["Güncel Tahmin (TL)"]),
                help=(
                    f"{revaluation.baz_donem.etiket} bazlı model çıktısı: {format_tl(row['Tahmin (TL)'])} · "
                    f"Nested CV RMSE ({revaluation.baz_donem.etiket}): "
                    f"{format_tl(row['Nested CV RMSE (TL)'])}"
                ),
            )

    chart_data = predictions[["Model", "Güncel Tahmin (TL)"]].copy()
    chart_data["Tahmin (milyar TL)"] = chart_data["Güncel Tahmin (TL)"] / 1_000_000_000
    chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusEnd=5)
        .encode(
            x=alt.X("Tahmin (milyar TL):Q", title="Tahmin (milyar TL)"),
            y=alt.Y("Model:N", sort=None, title=None),
            color=alt.Color("Model:N", legend=None),
            tooltip=[
                alt.Tooltip("Model:N"),
                alt.Tooltip("Güncel Tahmin (TL):Q", format=",.2f"),
            ],
        )
        .properties(height=210, title="Model tahminlerinin karşılaştırılması")
    )
    st.altair_chart(chart, width="stretch")

    base_column = f"Tahmin – {revaluation.baz_donem.etiket} (TL)"
    current_column = f"Tahmin – {revaluation.son_donem.etiket} (TL)"
    prediction_columns = ["Tahmin (TL)", "Güncel Tahmin (TL)"] if revaluation.guncellendi_mi else ["Tahmin (TL)"]
    performance = predictions[
        ["Sıra", "Model", *prediction_columns, "Nested CV R²", "Nested CV RMSE (TL)", "Nested CV MAE (TL)"]
    ].rename(columns={"Tahmin (TL)": base_column, "Güncel Tahmin (TL)": current_column})
    formats = {
        column: (lambda value: format_tl(value))
        for column in performance.columns
        if column.endswith("(TL)")
    }
    formats["Nested CV R²"] = "{:.3f}"
    st.dataframe(
        performance.style.format(formats),
        hide_index=True,
        width="stretch",
    )

with st.expander("Model kapsamı ve kullanım notları"):
    st.markdown(
        f"""
- Sıralama ölçütü: **{manifest['secim_olcutu']}**.
- Hedef: **{manifest['hedef_aciklamasi']} ({manifest['para_birimi']})**.
- Eğitim örneği sayısı: **{manifest['egitim_satir_sayisi']}**.
- `SIRA NO`, proje adı, sözleşme tarihi, nominal sözleşme bedeli ve TAKE OFF vana sayısı model girdisi değildir.
- Bu çalışma zaman serisi analizi değildir; sıra numarası yalnızca kayıt kimliğidir.
- Yeniden değerleme: model çıktısı, {manifest['fiyat_bazi']} sonrasındaki aylık Yİ-ÜFE değişimleri zincirlenerek en son yayımlanmış döneme taşınır. Hata metrikleri (RMSE, MAE) model fiyat bazındadır.
- Tahminler karar desteği içindir; keşif, piyasa koşulları ve mühendislik değerlendirmesinin yerine geçmez.
"""
    )
