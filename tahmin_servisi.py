from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import joblib
import pandas as pd

from model_schema import FEATURE_LABELS, MODEL_FEATURES


def load_prediction_artifacts(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Tahmin uygulamasının manifestini ve sıralı üç model paketini yükler."""
    manifest_path = output_dir / "model_manifest.json"
    model_path = output_dir / "en_iyi_3_model.joblib"
    if not manifest_path.exists() or not model_path.exists():
        raise FileNotFoundError(
            "Tahmin artefaktları bulunamadı. Önce ihale_maliyet_modelleme.py dosyasını çalıştırın."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = joblib.load(model_path)
    features = manifest.get("ozellik_sirasi", [])
    ranking = manifest.get("en_iyi_3_model", [])
    if features != list(MODEL_FEATURES):
        raise ValueError(f"Beklenmeyen özellik şeması: {features}")
    if len(ranking) != 3:
        raise ValueError("Manifest içinde tam olarak üç sıralı model bulunmalıdır.")
    missing = [item["model_kodu"] for item in ranking if item["model_kodu"] not in models]
    if missing:
        raise ValueError(f"Model paketinde eksik modeller var: {missing}")
    return manifest, models


def validate_inputs(values: Mapping[str, float], features: list[str]) -> dict[str, float]:
    """Girdileri sonlu, negatif olmayan sayılara dönüştürür."""
    clean: dict[str, float] = {}
    for feature in features:
        if feature not in values:
            raise ValueError(f"Eksik girdi: {FEATURE_LABELS.get(feature, feature)}")
        value = float(values[feature])
        if not math.isfinite(value):
            raise ValueError(f"Sonlu olmayan girdi: {FEATURE_LABELS.get(feature, feature)}")
        if value < 0:
            raise ValueError(f"Negatif girdi kullanılamaz: {FEATURE_LABELS.get(feature, feature)}")
        clean[feature] = value
    return clean


def training_range_warnings(values: Mapping[str, float], manifest: Mapping[str, Any]) -> list[str]:
    """Modeli durdurmadan eğitim aralığı dışındaki girdileri bildirir."""
    warnings: list[str] = []
    ranges = manifest["egitim_verisi_ozellik_araliklari"]
    for feature in manifest["ozellik_sirasi"]:
        value = float(values[feature])
        minimum = float(ranges[feature]["minimum"])
        maximum = float(ranges[feature]["maksimum"])
        if value < minimum or value > maximum:
            warnings.append(
                f"{FEATURE_LABELS[feature]} = {value:g}; eğitim aralığı {minimum:g}–{maximum:g}."
            )
    return warnings


def predict_current_contract_values(
    values: Mapping[str, float], manifest: Mapping[str, Any], models: Mapping[str, Any]
) -> pd.DataFrame:
    """Nested-CV RMSE sıralamasındaki en iyi üç modelin güncel TL tahminini döndürür."""
    features = list(manifest["ozellik_sirasi"])
    clean = validate_inputs(values, features)
    row = pd.DataFrame([[clean[feature] for feature in features]], columns=features)

    records: list[dict[str, Any]] = []
    for item in manifest["en_iyi_3_model"]:
        code = item["model_kodu"]
        raw_prediction = float(models[code].predict(row)[0])
        records.append(
            {
                "Sıra": int(item["sira"]),
                "Model Kodu": code,
                "Model": item["model_adi"],
                "Tahmin (TL)": max(0.0, raw_prediction),
                "Nested CV R²": float(item["R2"]),
                "Nested CV RMSE (TL)": float(item["RMSE_TL"]),
                "Nested CV MAE (TL)": float(item["MAE_TL"]),
                "Nested CV MAPE (%)": float(item["MAPE_YUZDE"]),
                "Nested CV WAPE (%)": float(item["WAPE_YUZDE"]),
            }
        )
    return pd.DataFrame(records).sort_values("Sıra").reset_index(drop=True)


def format_tl(value: float, decimals: int = 2) -> str:
    """Sayıyı Türkçe ayraçlarla TL metnine dönüştürür."""
    formatted = f"{value:,.{decimals}f}"
    return formatted.translate(str.maketrans({",": ".", ".": ","})) + " TL"
