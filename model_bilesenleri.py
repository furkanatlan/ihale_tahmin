from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone

from model_schema import MODEL_FEATURES


# Kaydedilen (joblib) modeller bu modüldeki fonksiyon ve sınıflara ada göre başvurur;
# eğitim ve tahmin uygulaması aynı tanımları buradan içe aktarır.
FIZIKSEL_OZELLIK_ADLARI = (
    "BORU_CAPI",
    "HAT_UZUNLUGU_KM",
    "HAT_VANASI_SAYISI",
    "PIG_ISTASYONU_SAYISI",
    "CAP_X_UZUNLUK",  # inç-km: boru hattı işinin klasik ölçeği
    "CAP2_X_UZUNLUK",  # çelik ağırlığı ≈ çap × et kalınlığı × uzunluk; et kalınlığı çapla artar
    "LOG_UZUNLUK",
    "KM_BASINA_VANA",
)


def fiziksel_ozellikler(x: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Dört girdiden maliyetle fiziksel ilişkisi olan türetilmiş özellikleri üretir."""
    frame = pd.DataFrame(x, columns=list(MODEL_FEATURES))
    cap, uzunluk, vana, pig = (frame[column].to_numpy(dtype=float) for column in MODEL_FEATURES)
    return np.column_stack(
        [
            cap,
            uzunluk,
            vana,
            pig,
            cap * uzunluk,
            cap * cap * uzunluk,
            np.log1p(uzunluk),
            vana / np.maximum(uzunluk, 1.0),
        ]
    )


MONOTON_OZELLIK_ADLARI = FIZIKSEL_OZELLIK_ADLARI[:-1]


def monoton_fiziksel_ozellikler(x: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Her biri dört girdinin artan fonksiyonu olan fiziksel özellikler.

    Ağaç modeli bu özelliklerin her birinde artan olmaya zorlanınca tahmin, çap, uzunluk,
    vana ve PİG istasyonu sayısında da artan olur (km başına vana bu yüzden çıkarılmıştır).
    """
    return fiziksel_ozellikler(x)[:, : len(MONOTON_OZELLIK_ADLARI)]


def log_ozellikler(x: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Güç yasası (log-log) maliyet ilişkileri için logaritmik girdiler."""
    frame = pd.DataFrame(x, columns=list(MODEL_FEATURES))
    cap, uzunluk, vana, pig = (frame[column].to_numpy(dtype=float) for column in MODEL_FEATURES)
    return np.column_stack(
        [np.log(np.maximum(cap, 1.0)), np.log(np.maximum(uzunluk, 0.1)), np.log1p(vana), np.log1p(pig)]
    )


class LogHedefRegresor(BaseEstimator, RegressorMixin):
    """Hedefin logaritması üzerinde öğrenir; Duan smearing ile TL ortalamasına geri çevirir."""

    def __init__(self, regressor: BaseEstimator | None = None, smearing: bool = True) -> None:
        self.regressor = regressor
        self.smearing = smearing

    def fit(self, x, y):
        log_y = np.log(np.asarray(y, dtype=float))
        self.regressor_ = clone(self.regressor).fit(x, log_y)
        residual = log_y - self.regressor_.predict(x)
        self.smearing_factor_ = float(np.mean(np.exp(residual))) if self.smearing else 1.0
        return self

    def predict(self, x):
        return np.exp(self.regressor_.predict(x)) * self.smearing_factor_
