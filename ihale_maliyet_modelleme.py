from __future__ import annotations

import argparse
import json
import math
import platform
import re
import sys
import unicodedata
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from catboost import CatBoostRegressor
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    StackingRegressor,
)
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge, RidgeCV
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    median_absolute_error,
    r2_score,
    root_mean_squared_error,
    root_mean_squared_log_error,
)
from sklearn.model_selection import GridSearchCV, KFold, train_test_split
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.tree import plot_tree
from xgboost import XGBRegressor

from model_schema import MODEL_FEATURES


RANDOM_STATE = 42
HOLDOUT_TEST_RATIO = 0.05
FEATURES = list(MODEL_FEATURES)
TARGET = "GUNCEL_SOZLESME_BEDELI_TL_TEMMUZ_2026"
NOMINAL_TARGET = "SOZLESME_BEDELI_NOMINAL_TL"
IDENTITY_COLUMNS = [
    "SIRA_NO",
    "PROJE_ADI",
    NOMINAL_TARGET,
    "SOZLESME_TARIHI_KAYNAK",
    "FIYAT_GUNCELLEME_KATSAYISI",
]

DISPLAY_NAMES = {
    "CDR": "Çoklu Doğrusal Regresyon (ÇDR)",
    "ER": "ElasticNet (ER)",
    "KNN": "K-En Yakın Komşu (KNN)",
    "RF": "Rastgele Orman (RF)",
    "XGB": "XGBoost (XGB)",
    "CAT": "CatBoost (Modern)",
    "HGB": "Histogram Gradient Boosting (Modern)",
    "STACK": "Stacking Ensemble (Modern)",
}

MODEL_GROUP = {
    "CDR": "Tez-klasik",
    "ER": "Tez-klasik",
    "KNN": "Tez-klasik",
    "RF": "Tez-klasik",
    "XGB": "Tez-klasik",
    "CAT": "Modern ek",
    "HGB": "Modern ek",
    "STACK": "Modern ek",
}

METRIC_LABELS = {
    "R2": "R²",
    "RMSE": "RMSE",
    "NRMSE": "NRMSE (ortalama, %)",
    "MAE": "MAE",
    "MAPE": "MAPE (%)",
    "MedAE": "MedAE",
    "WAPE": "WAPE (%)",
    "RMSLE": "RMSLE",
    "Bias": "Bias (tahmin - gerçek)",
}


@dataclass
class ModelSpec:
    estimator: Any
    param_grid: dict[str, list[Any]] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="İhale sözleşme bedeli model karşılaştırması")
    parser.add_argument("--excel", type=Path, default=Path("VERİLER_GÜNCELLENMİŞ.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("sonuclar"))
    parser.add_argument("--fast", action="store_true", help="Daha küçük gridlerle hızlı duman testi")
    parser.add_argument("--bootstrap", type=int, default=1000, help="Metrik güven aralığı bootstrap sayısı")
    return parser.parse_args()


def normalize_header(value: Any) -> str:
    text = str(value).strip().upper().replace("İ", "I").replace("ı", "I")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", "_", text).strip("_")


def numeric_series(series: pd.Series, name: str) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        result = pd.to_numeric(series, errors="coerce")
    else:
        cleaned = series.astype(str).str.strip().str.replace('"', "", regex=False)
        cleaned = cleaned.str.replace(",", ".", regex=False)
        extracted = cleaned.str.extract(r"(-?\d+(?:\.\d+)?)", expand=False)
        result = pd.to_numeric(extracted, errors="coerce")
    if result.isna().any():
        rows = (result[result.isna()].index + 2).tolist()
        raise ValueError(f"{name} sütununda sayıya çevrilemeyen Excel satırları: {rows}")
    return result.astype(float)


def find_header_row(path: Path, sheet_name: int | str = 0) -> int:
    """Üstte boş/biçimlendirme satırları olsa da gerçek başlık satırını bulur."""
    preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=25, engine="openpyxl")
    required = {"BORU_CAPI", "HAT_UZUNLUGU_KM", "SOZLESME_BEDELI"}
    for index, row in preview.iterrows():
        normalized = {normalize_header(value) for value in row.dropna().tolist()}
        if required.issubset(normalized) and any(value.startswith("GUNCEL_DEGER") for value in normalized):
            return int(index)
    raise ValueError("Excel içinde beklenen başlık satırı bulunamadı.")


def date_source_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.notna(parsed):
        return parsed.strftime("%Y-%m-%d")
    return str(value).strip()


def load_data(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    header_row = find_header_row(path)
    raw = pd.read_excel(path, header=header_row, engine="openpyxl")
    raw = raw.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)
    normalized = {normalize_header(col): col for col in raw.columns}
    aliases = {
        "SIRA_NO": ["SIRA_NO"],
        "PROJE_ADI": ["PROJE_ADI"],
        "BORU_CAPI": ["BORU_CAPI"],
        "HAT_UZUNLUGU_KM": ["HAT_UZUNLUGU_KM", "HAT_UZUNLUGU"],
        "HAT_VANASI_SAYISI": ["HAT_VANASI_SAYISI_ADET", "HAT_VANASI_SAYISI"],
        "PIG_ISTASYONU_SAYISI": ["PIG_ISTASYONU_SAYISI_ADET", "PIG_ISTASYON_SAYISI_ADET"],
        NOMINAL_TARGET: ["SOZLESME_BEDELI"],
        "SOZLESME_TARIHI_HAM": ["SOZLESME_TARIHI"],
        TARGET: [
            "GUNCEL_DEGER_YI_UFE_TEMMUZ_2026",
            "GUNCEL_DEGER_YI_UFE_TEMMUZ2026",
        ],
    }

    sources: dict[str, Any] = {}
    for canonical, candidates in aliases.items():
        source = next((normalized[c] for c in candidates if c in normalized), None)
        if source is None:
            raise KeyError(
                f"Gerekli sütun bulunamadı: {canonical}. Mevcut sütunlar: {list(raw.columns)}"
            )
        sources[canonical] = source

    data = pd.DataFrame(
        {
            "SIRA_NO": numeric_series(raw[sources["SIRA_NO"]], sources["SIRA_NO"]).astype(int),
            "PROJE_ADI": raw[sources["PROJE_ADI"]].astype(str).str.strip(),
            "BORU_CAPI": numeric_series(raw[sources["BORU_CAPI"]], sources["BORU_CAPI"]),
            "HAT_UZUNLUGU_KM": numeric_series(
                raw[sources["HAT_UZUNLUGU_KM"]], sources["HAT_UZUNLUGU_KM"]
            ),
            "HAT_VANASI_SAYISI": numeric_series(
                raw[sources["HAT_VANASI_SAYISI"]], sources["HAT_VANASI_SAYISI"]
            ),
            "PIG_ISTASYONU_SAYISI": numeric_series(
                raw[sources["PIG_ISTASYONU_SAYISI"]], sources["PIG_ISTASYONU_SAYISI"]
            ),
            NOMINAL_TARGET: numeric_series(raw[sources[NOMINAL_TARGET]], sources[NOMINAL_TARGET]),
            "SOZLESME_TARIHI_KAYNAK": raw[sources["SOZLESME_TARIHI_HAM"]].map(date_source_text),
            TARGET: numeric_series(raw[sources[TARGET]], sources[TARGET]),
        }
    )
    data["SOZLESME_TARIHI"] = pd.to_datetime(
        data["SOZLESME_TARIHI_KAYNAK"], errors="coerce", format="mixed"
    )
    data["FIYAT_GUNCELLEME_KATSAYISI"] = data[TARGET] / data[NOMINAL_TARGET]
    data["EXCEL_SATIRI"] = np.arange(header_row + 2, header_row + 2 + len(data))
    if len(data) < 20:
        raise ValueError("Güvenilir karşılaştırma için en az 20 eksiksiz gözlem gereklidir.")
    if data["SIRA_NO"].duplicated().any():
        raise ValueError("SIRA NO alanında yinelenen kayıt bulundu.")
    if data["PROJE_ADI"].eq("").any():
        raise ValueError("PROJE ADI boş olan kayıt bulundu.")
    for column in (NOMINAL_TARGET, TARGET):
        if (data[column] <= 0).any():
            rows = data.loc[data[column] <= 0, "SIRA_NO"].tolist()
            raise ValueError(f"{column} pozitif olmalıdır. Sorunlu sıra numaraları: {rows}")
    return raw, data


def build_models(fast: bool = False) -> dict[str, ModelSpec]:
    elastic = TransformedTargetRegressor(
        regressor=Pipeline(
            [("scale", RobustScaler()), ("model", ElasticNet(max_iter=100_000, random_state=RANDOM_STATE))]
        ),
        transformer=StandardScaler(),
    )
    knn = Pipeline(
        [("scale", RobustScaler()), ("model", KNeighborsRegressor())]
    )

    xgb_estimators = [50, 150] if not fast else [50]
    cat_iterations = [300] if not fast else [100]
    hist_iterations = [250] if not fast else [100]

    ridge_base = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    rf_base = RandomForestRegressor(
        n_estimators=300 if not fast else 80,
        max_features=0.8,
        min_samples_leaf=2,
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    hist_base = HistGradientBoostingRegressor(
        max_iter=250 if not fast else 100,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=5,
        l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )

    return {
        "CDR": ModelSpec(LinearRegression(), None),
        "ER": ModelSpec(
            elastic,
            {
                "regressor__model__alpha": [0.001, 0.01, 0.1, 1.0] if not fast else [0.01, 0.1],
                "regressor__model__l1_ratio": [0.1, 0.5, 0.9],
            },
        ),
        "KNN": ModelSpec(
            knn,
            {
                "model__n_neighbors": [3, 4, 5, 7, 9] if not fast else [3, 5],
                "model__weights": ["uniform", "distance"],
                "model__p": [1, 2] if not fast else [2],
            },
        ),
        "RF": ModelSpec(
            RandomForestRegressor(random_state=RANDOM_STATE, n_jobs=1),
            {
                "n_estimators": [100, 300] if not fast else [100],
                "max_features": ["sqrt", 1.0],
                "min_samples_split": [2, 5],
                "min_samples_leaf": [1, 2] if not fast else [2],
            },
        ),
        "XGB": ModelSpec(
            XGBRegressor(
                objective="reg:squarederror",
                tree_method="hist",
                random_state=RANDOM_STATE,
                n_jobs=1,
                verbosity=0,
            ),
            {
                "n_estimators": xgb_estimators,
                "learning_rate": [0.05, 0.2],
                "max_depth": [2, 3],
                "subsample": [0.8, 1.0] if not fast else [1.0],
                "colsample_bytree": [0.8, 1.0] if not fast else [1.0],
                "reg_lambda": [1.0, 10.0] if not fast else [1.0],
            },
        ),
        "CAT": ModelSpec(
            CatBoostRegressor(
                loss_function="RMSE",
                verbose=False,
                allow_writing_files=False,
                random_seed=RANDOM_STATE,
                thread_count=1,
            ),
            {
                "iterations": cat_iterations,
                "depth": [3, 5],
                "learning_rate": [0.03, 0.1],
                "l2_leaf_reg": [3.0, 10.0] if not fast else [3.0],
            },
        ),
        "HGB": ModelSpec(
            HistGradientBoostingRegressor(random_state=RANDOM_STATE, early_stopping=False),
            {
                "max_iter": hist_iterations,
                "learning_rate": [0.03, 0.1],
                "max_leaf_nodes": [7, 15],
                "min_samples_leaf": [5, 10] if not fast else [5],
                "l2_regularization": [0.0, 1.0] if not fast else [1.0],
            },
        ),
        "STACK": ModelSpec(
            StackingRegressor(
                estimators=[("ridge", ridge_base), ("rf", rf_base), ("hist", hist_base)],
                final_estimator=make_pipeline(
                    StandardScaler(), RidgeCV(alphas=np.logspace(-3, 6, 19))
                ),
                cv=4,
                passthrough=False,
                n_jobs=-1,
            ),
            None,
        ),
    }


def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.clip(np.asarray(y_pred, dtype=float), 0, None)
    rmse = float(root_mean_squared_error(y_true, y_pred))
    mean_target = float(np.mean(np.abs(y_true)))
    return {
        "R2": float(r2_score(y_true, y_pred)),
        "RMSE": rmse,
        "NRMSE": float(rmse / mean_target * 100.0) if mean_target > 0 else float("nan"),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "MAPE": float(mean_absolute_percentage_error(y_true, y_pred) * 100.0),
        "MedAE": float(median_absolute_error(y_true, y_pred)),
        "WAPE": float(np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true)) * 100.0),
        "RMSLE": float(root_mean_squared_log_error(y_true, y_pred)),
        "Bias": float(np.mean(y_pred - y_true)),
    }


def predict_nonnegative(model: Any, x: pd.DataFrame) -> np.ndarray:
    """Sözleşme bedeli için ortak fiziksel alt sınırı uygular."""
    return np.clip(np.asarray(model.predict(x), dtype=float), 0, None)


def fit_with_search(
    spec: ModelSpec,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    inner_cv: KFold,
    scoring: str,
) -> tuple[Any, dict[str, Any]]:
    estimator = clone(spec.estimator)
    if not spec.param_grid:
        estimator.fit(x_train, y_train)
        return estimator, {}
    search = GridSearchCV(
        estimator,
        spec.param_grid,
        scoring=scoring,
        cv=inner_cv,
        n_jobs=-1,
        refit=True,
        error_score="raise",
    )
    search.fit(x_train, y_train)
    return search.best_estimator_, search.best_params_


def nested_oof_evaluation(
    models: dict[str, ModelSpec], x: pd.DataFrame, y: pd.Series
) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, list[tuple[Any, np.ndarray]]]]:
    outer = KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    oof = {code: np.full(len(y), np.nan, dtype=float) for code in models}
    params_rows: list[dict[str, Any]] = []
    fold_models: dict[str, list[tuple[Any, np.ndarray]]] = {code: [] for code in models}

    for code, spec in models.items():
        print(f"[Nested CV] {DISPLAY_NAMES[code]}", flush=True)
        for fold, (train_idx, test_idx) in enumerate(outer.split(x), start=1):
            inner = KFold(n_splits=4, shuffle=True, random_state=RANDOM_STATE + fold)
            fitted, best_params = fit_with_search(
                spec,
                x.iloc[train_idx],
                y.iloc[train_idx],
                inner,
                scoring="neg_root_mean_squared_error",
            )
            oof[code][test_idx] = predict_nonnegative(fitted, x.iloc[test_idx])
            fold_models[code].append((fitted, test_idx.copy()))
            params_rows.append(
                {
                    "MODEL_KODU": code,
                    "MODEL": DISPLAY_NAMES[code],
                    "DIS_KAT": fold,
                    "EN_IYI_PARAMETRELER": json.dumps(best_params, ensure_ascii=False, sort_keys=True),
                }
            )

    if any(np.isnan(pred).any() for pred in oof.values()):
        raise RuntimeError("OOF tahminlerinde beklenmeyen eksik değer oluştu.")
    return oof, pd.DataFrame(params_rows), fold_models


def holdout_evaluation(
    models: dict[str, ModelSpec],
    x: pd.DataFrame,
    y: pd.Series,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    predictions = pd.DataFrame(
        {"VERI_INDEX": test_idx, "GUNCEL_GERCEK_BEDEL_TL": y.iloc[test_idx].to_numpy()}
    )
    fitted_models: dict[str, Any] = {}
    inner = KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)

    for code, spec in models.items():
        print(f"[%5 sabit holdout] {DISPLAY_NAMES[code]}", flush=True)
        fitted, best_params = fit_with_search(
            spec,
            x.iloc[train_idx],
            y.iloc[train_idx],
            inner,
            scoring="r2",
        )
        fitted_models[code] = fitted
        for split_name, idx in (("Eğitim", train_idx), ("Test", test_idx)):
            metrics = calculate_metrics(y.iloc[idx].to_numpy(), predict_nonnegative(fitted, x.iloc[idx]))
            rows.append(
                {
                    "MODEL_KODU": code,
                    "MODEL": DISPLAY_NAMES[code],
                    "MODEL_GRUBU": MODEL_GROUP[code],
                    "KUME": split_name,
                    **metrics,
                    "EN_IYI_PARAMETRELER": json.dumps(best_params, ensure_ascii=False, sort_keys=True),
                }
            )
        predictions[f"{code}_TAHMIN"] = predict_nonnegative(fitted, x.iloc[test_idx])
    return pd.DataFrame(rows), predictions, fitted_models


def bootstrap_intervals(
    y: np.ndarray,
    predictions: dict[str, np.ndarray],
    repeats: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_STATE)
    n = len(y)
    metric_names = list(METRIC_LABELS)
    result_rows: list[dict[str, Any]] = []

    for code, pred in predictions.items():
        point = calculate_metrics(y, pred)
        samples = {metric: [] for metric in metric_names}
        for _ in range(repeats):
            idx = rng.integers(0, n, n)
            values = calculate_metrics(y[idx], pred[idx])
            for metric in metric_names:
                if np.isfinite(values[metric]):
                    samples[metric].append(values[metric])
        row: dict[str, Any] = {
            "MODEL_KODU": code,
            "MODEL": DISPLAY_NAMES[code],
            "MODEL_GRUBU": MODEL_GROUP[code],
        }
        for metric in metric_names:
            low, high = np.quantile(samples[metric], [0.025, 0.975])
            row[metric] = point[metric]
            row[f"{metric}_ALT95"] = float(low)
            row[f"{metric}_UST95"] = float(high)
        result_rows.append(row)
    return pd.DataFrame(result_rows).sort_values("RMSE").reset_index(drop=True)


def tune_full_models(
    models: dict[str, ModelSpec], x: pd.DataFrame, y: pd.Series
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fitted: dict[str, Any] = {}
    params: dict[str, dict[str, Any]] = {}
    inner = KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    for code, spec in models.items():
        print(f"[Tam veri final model] {DISPLAY_NAMES[code]}", flush=True)
        fitted[code], params[code] = fit_with_search(
            spec, x, y, inner, scoring="neg_root_mean_squared_error"
        )
    return fitted, params


def slugify(text: str) -> str:
    text = normalize_header(text).lower().replace("_", "-")
    return text or "grafik"


def setup_plot_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 180,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "legend.frameon": False,
        }
    )


def save_figure(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_data_diagnostics(data: pd.DataFrame, graph_dir: Path) -> None:
    labels = {
        "BORU_CAPI": "Boru çapı (inç)",
        "HAT_UZUNLUGU_KM": "Hat uzunluğu (km)",
        "HAT_VANASI_SAYISI": "Hat vanası (adet)",
        "PIG_ISTASYONU_SAYISI": "Pig istasyonu (adet)",
        TARGET: "Güncel sözleşme bedeli (milyon TL, Temmuz 2026 Yİ-ÜFE)",
    }
    plot_data = data[FEATURES + [TARGET]].copy()
    plot_data[TARGET] /= 1e6

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    for ax, column in zip(axes.flat, FEATURES + [TARGET]):
        sns.histplot(plot_data[column], kde=True, ax=ax, color="#2878B5")
        ax.set_title(labels[column])
        ax.set_xlabel(labels[column])
        ax.set_ylabel("Gözlem sayısı")
    axes.flat[-1].axis("off")
    fig.suptitle("Tez tarzı değişken histogramları", y=1.01)
    save_figure(fig, graph_dir / "01_veri_histogramlari.png")

    corr = data[FEATURES + [TARGET]].corr()
    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="vlag", center=0, square=True, ax=ax)
    ax.set_xticklabels(["Çap", "Uzunluk", "Hat vanası", "Pig", "Bedel"], rotation=25, ha="right")
    ax.set_yticklabels(["Çap", "Uzunluk", "Hat vanası", "Pig", "Bedel"], rotation=0)
    ax.set_title("Tez tarzı korelasyon matrisi")
    save_figure(fig, graph_dir / "02_korelasyon_matrisi.png")

    fig, ax = plt.subplots(figsize=(10, 7))
    sizes = 30 + 600 * (data[TARGET] - data[TARGET].min()) / (data[TARGET].max() - data[TARGET].min())
    scatter = ax.scatter(
        data["HAT_UZUNLUGU_KM"],
        data["BORU_CAPI"],
        s=sizes,
        c=data[TARGET] / 1e6,
        cmap="viridis",
        alpha=0.72,
        edgecolor="white",
        linewidth=0.6,
    )
    ax.set_xlabel("Hat uzunluğu (km)")
    ax.set_ylabel("Boru çapı (inç)")
    ax.set_title("Çap, hat uzunluğu ve sözleşme bedeli")
    colorbar = fig.colorbar(scatter, ax=ax)
    colorbar.set_label("Güncel bedel (milyon TL)")
    save_figure(fig, graph_dir / "03_cap_uzunluk_bedel_kabarcik.png")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    sns.histplot(data[TARGET] / 1e6, kde=True, ax=axes[0], color="#2878B5")
    axes[0].set_xlabel("Güncel bedel (milyon TL)")
    axes[0].set_title("Hedef dağılımı")
    sns.boxplot(x=data[TARGET] / 1e6, ax=axes[1], color="#78B7C5")
    axes[1].set_xlabel("Güncel bedel (milyon TL)")
    axes[1].set_title("Uç değer görünümü")
    save_figure(fig, graph_dir / "04_hedef_dagilimi_ve_uc_degerler.png")


def plot_price_adjustment_diagnostics(data: pd.DataFrame, graph_dir: Path) -> None:
    """Nominal/güncel TL ilişkisini denetler; tarih veya sıra üzerinden model kurmaz."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    dated = data["SOZLESME_TARIHI"].notna()
    axes[0].scatter(
        data.loc[dated, NOMINAL_TARGET] / 1e6,
        data.loc[dated, TARGET] / 1e6,
        alpha=0.72,
        label="Tarihli sözleşme",
        color="#2878B5",
    )
    axes[0].scatter(
        data.loc[~dated, NOMINAL_TARGET] / 1e6,
        data.loc[~dated, TARGET] / 1e6,
        marker="D",
        s=55,
        label="Kaynakta 'güncel'",
        color="#D95F02",
    )
    low = min(data[NOMINAL_TARGET].min(), data[TARGET].min()) / 1e6
    high = max(data[NOMINAL_TARGET].max(), data[TARGET].max()) / 1e6
    axes[0].plot([low, high], [low, high], "--", color="black", linewidth=1, label="Güncelleme yok")
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Nominal sözleşme bedeli (milyon TL, log)")
    axes[0].set_ylabel("Temmuz 2026 güncel değer (milyon TL, log)")
    axes[0].set_title("Nominal ve Yİ-ÜFE güncel TL değerleri")
    axes[0].legend()

    sns.histplot(data["FIYAT_GUNCELLEME_KATSAYISI"], bins=12, kde=True, ax=axes[1], color="#2878B5")
    axes[1].axvline(1.0, color="black", linestyle="--", linewidth=1)
    axes[1].set_xlabel("Güncelleme katsayısı (güncel / nominal)")
    axes[1].set_ylabel("Proje sayısı")
    axes[1].set_title("Yİ-ÜFE güncelleme katsayısı dağılımı")
    save_figure(fig, graph_dir / "05_nominal_guncel_tl_denetimi.png")


def plot_metric_bars(metrics: pd.DataFrame, graph_dir: Path) -> None:
    money_metrics = {"RMSE", "MAE", "MedAE", "Bias"}
    for order_no, metric in enumerate(METRIC_LABELS, start=20):
        frame = metrics.copy()
        sort_col = metric
        if metric == "R2":
            frame = frame.sort_values(sort_col, ascending=False)
        elif metric == "Bias":
            frame = frame.assign(_abs=frame[metric].abs()).sort_values("_abs")
        else:
            frame = frame.sort_values(sort_col)

        scale = 1e6 if metric in money_metrics else 1.0
        values = frame[metric] / scale
        low = frame[f"{metric}_ALT95"] / scale
        high = frame[f"{metric}_UST95"] / scale
        errors = np.vstack([values - low, high - values])

        fig, ax = plt.subplots(figsize=(11, 6))
        colors = ["#2878B5" if group == "Tez-klasik" else "#D95F02" for group in frame["MODEL_GRUBU"]]
        bars = ax.barh(frame["MODEL"], values, xerr=errors, color=colors, alpha=0.88, capsize=3)
        ax.invert_yaxis()
        if metric == "Bias":
            ax.axvline(0, color="black", linewidth=1)
        suffix = " (milyon TL)" if metric in money_metrics else ""
        ax.set_xlabel(f"{METRIC_LABELS[metric]}{suffix}")
        direction = "yüksek daha iyi" if metric == "R2" else ("sıfıra yakın daha iyi" if metric == "Bias" else "düşük daha iyi")
        ax.set_title(f"Modellerin {METRIC_LABELS[metric]} karşılaştırması ({direction})")
        ax.bar_label(bars, fmt="%.3g", padding=4, fontsize=8)
        ax.text(
            1,
            -0.12,
            "Hata çubukları: satır bootstrap yaklaşık %95 aralık",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
        )
        save_figure(fig, graph_dir / f"{order_no:02d}_metrik_{metric.lower()}.png")


def plot_model_diagnostics(
    data: pd.DataFrame,
    oof: dict[str, np.ndarray],
    graph_dir: Path,
) -> None:
    y = data[TARGET].to_numpy()
    order = np.argsort(y)
    x_axis = np.arange(len(y))

    fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(x_axis, y[order] / 1e6, color="black", linewidth=2.4, label="Gerçek")
    for code, pred in oof.items():
        ax.plot(x_axis, pred[order] / 1e6, linewidth=1.1, alpha=0.78, label=code)
    ax.set_xlabel("Gerçek bedele göre sıralı proje")
    ax.set_ylabel("Güncel sözleşme bedeli (milyon TL)")
    ax.set_title("Tüm modeller: gerçek ve iç içe CV OOF tahminleri")
    ax.legend(ncol=3)
    save_figure(fig, graph_dir / "10_tum_modeller_gercek_tahmin.png")

    fig, axes = plt.subplots(2, 4, figsize=(18, 9))
    lo = min(y.min(), *(pred.min() for pred in oof.values())) / 1e6
    hi = max(y.max(), *(pred.max() for pred in oof.values())) / 1e6
    for ax, (code, pred) in zip(axes.flat, oof.items()):
        ax.scatter(y / 1e6, pred / 1e6, alpha=0.72, s=30)
        ax.plot([lo, hi], [lo, hi], "--", color="black", linewidth=1)
        ax.set_title(DISPLAY_NAMES[code])
        ax.set_xlabel("Gerçek (milyon TL)")
        ax.set_ylabel("OOF tahmin (milyon TL)")
    fig.suptitle("Modern parite grafikleri: gerçek ve OOF tahmin", y=1.01)
    save_figure(fig, graph_dir / "11_parite_kucuk_coklular.png")

    fig, axes = plt.subplots(2, 4, figsize=(18, 9))
    for ax, (code, pred) in zip(axes.flat, oof.items()):
        residual = pred - y
        ax.scatter(pred / 1e6, residual / 1e6, alpha=0.72, s=30)
        ax.axhline(0, color="black", linewidth=1)
        ax.set_title(DISPLAY_NAMES[code])
        ax.set_xlabel("OOF tahmin (milyon TL)")
        ax.set_ylabel("Kalıntı: tahmin - gerçek (milyon TL)")
    fig.suptitle("Tez tarzı kalıntı grafikleri", y=1.01)
    save_figure(fig, graph_dir / "12_kalinti_kucuk_coklular.png")

    for i, (code, pred) in enumerate(oof.items(), start=30):
        fig, ax = plt.subplots(figsize=(12, 5.5))
        ax.plot(x_axis, y[order] / 1e6, color="#2878B5", linewidth=2, label="Gerçek")
        ax.plot(x_axis, pred[order] / 1e6, color="#D95F02", linestyle="--", linewidth=1.8, label="OOF tahmin")
        ax.set_xlabel("Gerçek bedele göre sıralı proje")
        ax.set_ylabel("Güncel sözleşme bedeli (milyon TL)")
        ax.set_title(f"{DISPLAY_NAMES[code]}: gerçek ve tahmin")
        ax.legend()
        save_figure(fig, graph_dir / f"{i:02d}_{code.lower()}_gercek_tahmin.png")

        fig, ax = plt.subplots(figsize=(9, 5.5))
        residual = pred - y
        ax.scatter(pred / 1e6, residual / 1e6, alpha=0.75)
        ax.axhline(0, color="black", linewidth=1)
        ax.set_xlabel("OOF tahmin (milyon TL)")
        ax.set_ylabel("Kalıntı (milyon TL)")
        ax.set_title(f"{DISPLAY_NAMES[code]}: kalıntı grafiği")
        save_figure(fig, graph_dir / f"{i:02d}_{code.lower()}_kalinti.png")


def plot_feature_importance(
    best_code: str,
    fold_models: list[tuple[Any, np.ndarray]],
    x: pd.DataFrame,
    y: pd.Series,
    graph_dir: Path,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fold, (model, test_idx) in enumerate(fold_models, start=1):
        importance = permutation_importance(
            model,
            x.iloc[test_idx],
            y.iloc[test_idx],
            scoring="neg_mean_absolute_error",
            n_repeats=30,
            random_state=RANDOM_STATE + fold,
            n_jobs=-1,
        )
        for feature, value in zip(FEATURES, importance.importances_mean):
            rows.append({"KAT": fold, "OZELLIK": feature, "ONEM_MAE_ARTISI": value})
    frame = pd.DataFrame(rows)
    summary = (
        frame.groupby("OZELLIK")["ONEM_MAE_ARTISI"]
        .agg(["mean", "std"])
        .sort_values("mean")
        .reset_index()
    )
    labels = {
        "BORU_CAPI": "Boru çapı",
        "HAT_UZUNLUGU_KM": "Hat uzunluğu",
        "HAT_VANASI_SAYISI": "Hat vanası",
        "PIG_ISTASYONU_SAYISI": "Pig istasyonu",
    }
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(
        summary["OZELLIK"].map(labels),
        summary["mean"] / 1e6,
        xerr=summary["std"].fillna(0) / 1e6,
        color="#D95F02" if MODEL_GROUP[best_code] == "Modern ek" else "#2878B5",
        alpha=0.85,
        capsize=3,
    )
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Özellik karıştırıldığında MAE artışı (milyon TL)")
    ax.set_title(f"{DISPLAY_NAMES[best_code]}: dış-test permütasyon önemi")
    save_figure(fig, graph_dir / "50_en_iyi_model_permutasyon_onemi.png")
    return summary


def plot_conformal_interval(
    data: pd.DataFrame,
    prediction: np.ndarray,
    best_code: str,
    alpha: float,
    graph_dir: Path,
) -> tuple[float, float]:
    y = data[TARGET].to_numpy()
    absolute_residual = np.abs(y - prediction)
    level = min(1.0, math.ceil((len(y) + 1) * (1 - alpha)) / len(y))
    try:
        radius = float(np.quantile(absolute_residual, level, method="higher"))
    except TypeError:
        radius = float(np.quantile(absolute_residual, level, interpolation="higher"))
    lower = np.clip(prediction - radius, 0, None)
    upper = prediction + radius
    coverage = float(np.mean((y >= lower) & (y <= upper)))
    order = np.argsort(prediction)

    fig, ax = plt.subplots(figsize=(14, 6))
    positions = np.arange(len(y))
    ax.fill_between(positions, lower[order] / 1e6, upper[order] / 1e6, alpha=0.25, label="Yaklaşık %90 aralık")
    ax.plot(positions, prediction[order] / 1e6, color="#D95F02", linewidth=1.5, label="OOF tahmin")
    ax.scatter(positions, y[order] / 1e6, s=18, color="#2878B5", label="Gerçek", zorder=3)
    ax.set_xlabel("OOF tahmine göre sıralı proje")
    ax.set_ylabel("Güncel sözleşme bedeli (milyon TL)")
    ax.set_title(f"{DISPLAY_NAMES[best_code]}: yaklaşık çapraz-konformal belirsizlik")
    ax.legend(ncol=3)
    save_figure(fig, graph_dir / "51_en_iyi_model_konformal_aralik.png")
    return radius, coverage


def plot_rf_tree(final_models: dict[str, Any], graph_dir: Path) -> None:
    rf = final_models.get("RF")
    if rf is None or not hasattr(rf, "estimators_"):
        return
    fig, ax = plt.subplots(figsize=(22, 10))
    plot_tree(
        rf.estimators_[0],
        feature_names=["Çap", "Uzunluk", "Hat vanası", "Pig"],
        filled=True,
        rounded=True,
        max_depth=3,
        fontsize=7,
        ax=ax,
    )
    ax.set_title("Tez tarzı örnek RF karar ağacı (ilk ağaç, ilk 3 seviye)")
    save_figure(fig, graph_dir / "52_rf_ornek_karar_agaci.png")


def describe_data(data: pd.DataFrame) -> dict[str, Any]:
    y = data[TARGET]
    nominal = data[NOMINAL_TARGET]
    factor = data["FIYAT_GUNCELLEME_KATSAYISI"]
    valid_dates = data["SOZLESME_TARIHI"].dropna()
    q1, q3 = y.quantile([0.25, 0.75])
    upper = q3 + 1.5 * (q3 - q1)
    return {
        "gozlem_sayisi": int(len(data)),
        "model_eksik_deger": int(data[FEATURES + [TARGET]].isna().sum().sum()),
        "tarih_yerine_guncel": int(data["SOZLESME_TARIHI"].isna().sum()),
        "tarih_min": valid_dates.min().strftime("%Y-%m-%d"),
        "tarih_max": valid_dates.max().strftime("%Y-%m-%d"),
        "yinelenen_satir": int(data[FEATURES + [TARGET]].duplicated().sum()),
        "yinelenen_sira_no": int(data["SIRA_NO"].duplicated().sum()),
        "yinelenen_proje_adi": int(data["PROJE_ADI"].duplicated().sum()),
        "nominal_min": float(nominal.min()),
        "nominal_medyan": float(nominal.median()),
        "nominal_ortalama": float(nominal.mean()),
        "nominal_max": float(nominal.max()),
        "hedef_min": float(y.min()),
        "hedef_medyan": float(y.median()),
        "hedef_ortalama": float(y.mean()),
        "hedef_max": float(y.max()),
        "guncelleme_katsayisi_min": float(factor.min()),
        "guncelleme_katsayisi_medyan": float(factor.median()),
        "guncelleme_katsayisi_max": float(factor.max()),
        "hedef_carpiklik": float(y.skew()),
        "iqr_ustu_uc_deger": int((y > upper).sum()),
        "uzunluk_hat_vanasi_korelasyonu": float(
            data[["HAT_UZUNLUGU_KM", "HAT_VANASI_SAYISI"]].corr().iloc[0, 1]
        ),
    }


def write_text_report(
    path: Path,
    holdout: pd.DataFrame,
) -> None:
    test = holdout.loc[holdout["KUME"] == "Test"].copy()
    test = test.sort_values("R2", ascending=False).reset_index(drop=True)

    common_models = {"CDR", "ER", "KNN", "RF", "XGB"}
    short_names = {
        "CDR": "Çoklu Doğrusal Regresyon",
        "ER": "ElasticNet",
        "KNN": "K-En Yakın Komşu",
        "RF": "Rastgele Orman",
        "XGB": "XGBoost",
        "CAT": "CatBoost",
        "HGB": "Histogram Gradient Boosting",
        "STACK": "Stacking Ensemble",
    }

    r2_stars = {
        code: "★" * rank
        for rank, code in enumerate(test.nlargest(3, "R2")["MODEL_KODU"], start=1)
    }
    mape_stars = {
        code: "★" * rank
        for rank, code in enumerate(test.nsmallest(3, "MAPE")["MODEL_KODU"], start=1)
    }

    rows: list[dict[str, str]] = []
    for _, result in test.iterrows():
        code = str(result["MODEL_KODU"])
        model_name = short_names[code] + (" (O)" if code in common_models else "")
        rows.append(
            {
                "Model": model_name,
                "R² (O)": f"{result['R2']:.4f} {r2_stars.get(code, '')}".rstrip(),
                "RMSE (M TL) (O)": f"{result['RMSE'] / 1e6:,.2f}",
                "NRMSE (%)": f"{result['NRMSE']:.2f}",
                "MAE (M TL) (O)": f"{result['MAE'] / 1e6:,.2f}",
                "MAPE (%) (O)": f"{result['MAPE']:.2f} {mape_stars.get(code, '')}".rstrip(),
                "MedAE (M TL)": f"{result['MedAE'] / 1e6:,.2f}",
                "WAPE (%)": f"{result['WAPE']:.2f}",
                "RMSLE": f"{result['RMSLE']:.4f}",
                "Bias (M TL)": f"{result['Bias'] / 1e6:,.2f}",
            }
        )

    table = pd.DataFrame(rows).to_string(index=False)
    lines = [
        table,
        "",
        "",
        "",
        "(O): Tez ile ortak model veya metrik.",
        "★: En iyi, ★★: ikinci en iyi, ★★★: üçüncü en iyi R² veya MAPE sonucu.",
        "R²: Modelin gerçek bedellerdeki değişimi açıklama gücünü gösterir. Büyük olması daha iyidir.",
        "RMSE: Büyük hataları daha fazla cezalandıran tipik hata büyüklüğüdür. Küçük olması daha iyidir.",
        "NRMSE: RMSE'yi hedef ortalamasına göre yüzdeleştirir. Küçük olması daha iyidir.",
        "MAE: Tahminlerin gerçek bedelden ortalama mutlak uzaklığını gösterir. Küçük olması daha iyidir.",
        "MAPE: Gerçek değerlerden ortalama mutlak yüzde sapmayı gösterir. Küçük olması daha iyidir; düşük gerçek değerlerde büyüyebilir.",
        "MedAE: Mutlak hataların medyanını gösterir ve uç değerlerden daha az etkilenir. Küçük olması daha iyidir.",
        "WAPE: Toplam mutlak hatanın toplam gerçek bedele oranını gösterir. Küçük olması daha iyidir.",
        "RMSLE: Oransal hataları logaritmik ölçekte gösterir. Küçük olması daha iyidir.",
        "Bias: Modelin sistematik fazla veya eksik tahmin yönünü gösterir. Sıfıra yakın olması daha iyidir.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def package_versions() -> dict[str, str]:
    import altair
    import catboost
    import matplotlib as mpl
    import sklearn
    import streamlit
    import xgboost

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "matplotlib": mpl.__version__,
        "xgboost": xgboost.__version__,
        "catboost": catboost.__version__,
        "streamlit": streamlit.__version__,
        "altair": altair.__version__,
    }


def main() -> int:
    args = parse_args()
    output_dir = args.output.resolve()
    graph_dir = output_dir / "grafikler"
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    for old_graph in graph_dir.glob("*.png"):
        old_graph.unlink()
    for legacy_name in (
        "tez_uyumlu_holdout_metrikleri.csv",
        "tez_uyumlu_holdout_tahminleri.xlsx",
    ):
        legacy_path = output_dir / legacy_name
        if legacy_path.exists():
            legacy_path.unlink()
    setup_plot_style()

    raw, data = load_data(args.excel.resolve())
    x = data[FEATURES]
    y = data[TARGET]
    if tuple(x.columns) != MODEL_FEATURES:
        raise RuntimeError(
            "Model özellikleri Streamlit girdi şemasıyla aynı değil: "
            f"beklenen={MODEL_FEATURES}, bulunan={tuple(x.columns)}"
        )

    requested_test_count = len(data) * HOLDOUT_TEST_RATIO
    test_count = max(2, int(round(requested_test_count)))
    indices = np.arange(len(data))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_count,
        random_state=RANDOM_STATE,
    )
    evaluation_data = data.iloc[train_idx].reset_index(drop=True)
    evaluation_x = x.iloc[train_idx].reset_index(drop=True)
    evaluation_y = y.iloc[train_idx].reset_index(drop=True)

    models = build_models(args.fast)

    plot_data_diagnostics(data, graph_dir)
    plot_price_adjustment_diagnostics(data, graph_dir)
    oof, nested_params, fold_models = nested_oof_evaluation(models, evaluation_x, evaluation_y)
    primary = bootstrap_intervals(evaluation_y.to_numpy(), oof, max(100, args.bootstrap))
    holdout, holdout_predictions, _ = holdout_evaluation(
        models, x, y, train_idx, test_idx
    )
    final_models, full_params = tune_full_models(models, x, y)

    top_three_codes = primary.head(3)["MODEL_KODU"].astype(str).tolist()
    best_code = top_three_codes[0]
    best_model = final_models[best_code]
    plot_metric_bars(primary, graph_dir)
    plot_model_diagnostics(evaluation_data, oof, graph_dir)
    importance = plot_feature_importance(
        best_code, fold_models[best_code], evaluation_x, evaluation_y, graph_dir
    )
    radius, coverage = plot_conformal_interval(
        evaluation_data, oof[best_code], best_code, 0.10, graph_dir
    )
    plot_rf_tree(final_models, graph_dir)

    primary.to_csv(output_dir / "model_performanslari.csv", index=False, encoding="utf-8-sig")
    holdout.to_csv(output_dir / "yuzde5_holdout_metrikleri.csv", index=False, encoding="utf-8-sig")
    nested_params.to_csv(output_dir / "nested_cv_en_iyi_parametreler.csv", index=False, encoding="utf-8-sig")
    importance.to_csv(output_dir / "en_iyi_model_ozellik_onemi.csv", index=False, encoding="utf-8-sig")

    predictions = data[[*IDENTITY_COLUMNS, *FEATURES, TARGET]].copy()
    predictions["DEGERLENDIRME_KUMESI"] = "Nested CV eğitim OOF"
    predictions.loc[test_idx, "DEGERLENDIRME_KUMESI"] = "%5 sabit test"
    for code in models:
        evaluation_prediction = np.full(len(data), np.nan, dtype=float)
        evaluation_prediction[train_idx] = oof[code]
        evaluation_prediction[test_idx] = holdout_predictions[f"{code}_TAHMIN"].to_numpy()
        predictions[f"{code}_DEGERLENDIRME_TAHMIN"] = evaluation_prediction
        predictions[f"{code}_TAM_TAHMIN"] = predict_nonnegative(final_models[code], x)
        predictions[f"{code}_DEGERLENDIRME_HATA"] = evaluation_prediction - y.to_numpy()
    best_evaluation_prediction = predictions[f"{best_code}_DEGERLENDIRME_TAHMIN"].to_numpy()
    predictions[f"{best_code}_ALT90_YAKLASIK"] = np.clip(
        best_evaluation_prediction - radius, 0, None
    )
    predictions[f"{best_code}_UST90_YAKLASIK"] = best_evaluation_prediction + radius
    predictions.to_csv(output_dir / "satir_bazli_tahminler.csv", index=False, encoding="utf-8-sig")
    predictions.to_excel(output_dir / "satir_bazli_tahminler.xlsx", index=False, engine="openpyxl")

    holdout_meta = data.iloc[holdout_predictions["VERI_INDEX"].to_numpy()][
        [*IDENTITY_COLUMNS, *FEATURES]
    ].reset_index(drop=True)
    holdout_predictions = pd.concat(
        [holdout_meta, holdout_predictions.drop(columns="VERI_INDEX").reset_index(drop=True)], axis=1
    )
    holdout_predictions.to_excel(
        output_dir / "yuzde5_holdout_tahminleri.xlsx", index=False, engine="openpyxl"
    )

    price_audit = data[
        ["SIRA_NO", "PROJE_ADI", NOMINAL_TARGET, "SOZLESME_TARIHI_KAYNAK", TARGET, "FIYAT_GUNCELLEME_KATSAYISI"]
    ].copy()
    price_audit.to_csv(output_dir / "fiyat_guncelleme_denetimi.csv", index=False, encoding="utf-8-sig")
    price_audit.to_excel(output_dir / "fiyat_guncelleme_denetimi.xlsx", index=False, engine="openpyxl")

    joblib.dump(best_model, output_dir / "en_iyi_model.joblib")
    joblib.dump(
        {code: final_models[code] for code in top_three_codes},
        output_dir / "en_iyi_3_model.joblib",
    )

    top_three_models: list[dict[str, Any]] = []
    for rank, code in enumerate(top_three_codes, start=1):
        metric_row = primary.loc[primary["MODEL_KODU"] == code].iloc[0]
        top_three_models.append(
            {
                "sira": rank,
                "model_kodu": code,
                "model_adi": DISPLAY_NAMES[code],
                "model_grubu": MODEL_GROUP[code],
                "R2": float(metric_row["R2"]),
                "RMSE_TL": float(metric_row["RMSE"]),
                "NRMSE_YUZDE": float(metric_row["NRMSE"]),
                "MAE_TL": float(metric_row["MAE"]),
                "MAPE_YUZDE": float(metric_row["MAPE"]),
                "WAPE_YUZDE": float(metric_row["WAPE"]),
                "tam_veri_parametreleri": full_params[code],
            }
        )

    feature_ranges = {
        feature: {
            "minimum": float(x[feature].min()),
            "medyan": float(x[feature].median()),
            "maksimum": float(x[feature].max()),
        }
        for feature in FEATURES
    }
    manifest = {
        "olusturma_tarihi": pd.Timestamp.now(tz="Europe/Istanbul").isoformat(),
        "kaynak_excel": str(args.excel.resolve()),
        "model_kodu": best_code,
        "model_adi": DISPLAY_NAMES[best_code],
        "secim_olcutu": "Nested 5x4 CV OOF RMSE (en düşük)",
        "ozellik_sirasi": FEATURES,
        "hedef": TARGET,
        "hedef_aciklamasi": "Yİ-ÜFE ile Temmuz 2026 değerine güncellenmiş sözleşme bedeli",
        "nominal_bedel_alani": NOMINAL_TARGET,
        "para_birimi": "TL",
        "fiyat_bazi": "Temmuz 2026 Yİ-ÜFE",
        "sira_no_model_girdisi_mi": False,
        "sozlesme_tarihi_model_girdisi_mi": False,
        "zaman_serisi_modeli_mi": False,
        "yalnizca_streamlit_girdileri_kullanildi_mi": True,
        "istenen_sabit_test_orani": HOLDOUT_TEST_RATIO,
        "gercek_sabit_test_orani": float(len(test_idx) / len(data)),
        "degerlendirme_egitim_satir_sayisi": int(len(train_idx)),
        "sabit_test_satir_sayisi": int(len(test_idx)),
        "dogrulama_duzeni": (
            "%5'e en yakın tam satır sayısıyla sabit test; kalan eğitim verisinde "
            "rastgele karıştırmalı nested KFold; zamansal bölme yok"
        ),
        "tam_veri_parametreleri": full_params[best_code],
        "en_iyi_3_model": top_three_models,
        "egitim_verisi_ozellik_araliklari": feature_ranges,
        "egitim_satir_sayisi": int(len(data)),
        "uygulama_model_dosyasi": "en_iyi_3_model.joblib",
        "tahmin_alt_siniri": 0.0,
        "yaklasik_konformal_seviye": 0.90,
        "yaklasik_konformal_yaricap": radius,
        "paket_surumu": package_versions(),
    }
    (output_dir / "model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_text_report(
        output_dir / "model_performanslari.txt",
        holdout,
    )

    print(f"\nTamamlandı. Seçilen model: {DISPLAY_NAMES[best_code]}")
    print(f"Sonuç klasörü: {output_dir}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning)
    sys.exit(main())
