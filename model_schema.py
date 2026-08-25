from __future__ import annotations


# Eğitim kodu, tahmin servisi ve Streamlit arayüzü aynı tekil şemayı kullanır.
MODEL_FEATURES = (
    "BORU_CAPI",
    "HAT_UZUNLUGU_KM",
    "HAT_VANASI_SAYISI",
    "PIG_ISTASYONU_SAYISI",
)

FEATURE_LABELS = {
    "BORU_CAPI": "BORU ÇAPI",
    "HAT_UZUNLUGU_KM": "HAT UZUNLUĞU (km)",
    "HAT_VANASI_SAYISI": "HAT VANASI SAYISI (ADET)",
    "PIG_ISTASYONU_SAYISI": "PİG İSTASYONU SAYISI (ADET)",
}
