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


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "sonuclar"


st.set_page_config(
    page_title="Güncel Sözleşme Bedeli Tahmini",
    page_icon="₺",
    layout="wide",
)

st.title("Güncel ihale sözleşme bedeli tahmini")
st.caption(
    "Dört teknik girdiden Temmuz 2026 Yİ-ÜFE fiyat bazında güncel sözleşme bedelini "
    "en iyi üç modelle tahmin eder. Para birimi TL'dir."
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

    predictions = predict_current_contract_values(values, manifest, models)
    st.subheader("En iyi 3 modelin tahmini")
    metric_columns = st.columns(3)
    for column, row in zip(metric_columns, predictions.to_dict("records")):
        with column:
            st.metric(
                label=f"{row['Sıra']}. {row['Model']}",
                value=format_tl(row["Tahmin (TL)"]),
                help=f"Nested CV RMSE: {format_tl(row['Nested CV RMSE (TL)'])}",
            )

    chart_data = predictions[["Model", "Tahmin (TL)"]].copy()
    chart_data["Tahmin (milyar TL)"] = chart_data["Tahmin (TL)"] / 1_000_000_000
    chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusEnd=5)
        .encode(
            x=alt.X("Tahmin (milyar TL):Q", title="Tahmin (milyar TL)"),
            y=alt.Y("Model:N", sort=None, title=None),
            color=alt.Color("Model:N", legend=None),
            tooltip=[
                alt.Tooltip("Model:N"),
                alt.Tooltip("Tahmin (TL):Q", format=",.2f"),
            ],
        )
        .properties(height=210, title="Model tahminlerinin karşılaştırılması")
    )
    st.altair_chart(chart, width="stretch")

    performance = predictions[
        ["Sıra", "Model", "Nested CV R²", "Nested CV RMSE (TL)", "Nested CV MAE (TL)"]
    ].copy()
    st.dataframe(
        performance.style.format(
            {
                "Nested CV R²": "{:.3f}",
                "Nested CV RMSE (TL)": lambda value: format_tl(value),
                "Nested CV MAE (TL)": lambda value: format_tl(value),
            }
        ),
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
- Tahminler karar desteği içindir; keşif, piyasa koşulları ve mühendislik değerlendirmesinin yerine geçmez.
"""
    )
