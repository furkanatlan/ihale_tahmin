# 🔬 Model geliştirme raporu (01.11.2026)

**Amaç:** Dört girdiden (boru çapı, hat uzunluğu, hat vanası, PİG istasyonu) gerçek ihale bedeline en yakın tahmini üreten modeli bulmak.

## 1. Veri kararı: MAGA FAZ 2 hariç

| Proje | Çap | Uzunluk | Güncel bedel | km başına |
|---|---|---|---|---|
| **MAGA FAZ 2** | 40" | 133,5 km | 5,49 mr TL | **41,1 mn TL** |
| Mut–Mersin | 40" | 168,0 km | 3,10 mr TL | 18,5 mn TL |
| MAGA FAZ 1 | 40" | 158,8 km | 2,16 mr TL | 13,6 mn TL |

- MAGA FAZ 2'nin girdileri olağan, maliyeti ise benzerlerinin 2–3 katıydı. Model bu projeyi, eğitim verisinde yer aldığında bile ~1,5 mr TL tahmin ediyordu.
- Proje eğitimdeyken, komşu büyük projelerin tahminleri de yukarı çekiliyordu.
- Proje, kurum içi teyitle olağan kapsam dışı olduğu doğrulandıktan sonra eğitimden çıkarıldı.
- Hariç tutma, `HARIC_TUTULAN_PROJELER` sözlüğünde gerekçesiyle kayıtlıdır ve geri alınabilir: `--haric-tutma-yok`.

## 2. Tarama: 10 × 5 katlı çapraz doğrulama (64 proje, sabit parametreler)

Aynı projeler; değerler 10 tekrarın ortalamasıdır. ±%30 içinde: tahminin gerçek bedelin ±%30 bandında olduğu projelerin oranı.

| Yaklaşım | RMSE (mn TL) | MAE (mn TL) | ±%30 içinde | Sonuç |
|---|---:|---:|---:|---|
| Extra Trees + fiziksel özellikler | 188,3 | 95,2 | %64 | ✅ özellik mühendisliği işe yarıyor |
| CatBoost + fiziksel özellikler | 191,8 | 94,7 | %66 | ✅ |
| XGBoost | 192,8 | 97,9 | %62 | ⚠️ bir projede 0 TL tahmin etti |
| Monoton XGBoost | 197,7 | 99,0 | %62 | ✅ saçma tahmin yok, daha kararlı |
| Rastgele Orman (önceki 1. model) | 241,4 | 114,8 | %58 | |
| Stacking (önceki 2. model) | 255,6 | 125,7 | %50 | |
| Log hedef (RF/XGB/CAT) | 229–292 | 116–139 | %51–58 | ❌ TL hatasını artırdı |
| Güç yasası (log-log Ridge) | 294,0 | 129,9 | %61 | ❌ |
| Gauss süreci (log) | 231,8 | 118,3 | %60 | ❌ |
| TabPFN v2 (5 tekrar) | 225,7 | 105,3 | %66 | ❌ geride kaldı; ~1 GB PyTorch bağımlılığı |

**Monoton kısıt taraması**

Monoton kısıt şu kuralı zorlar: çap, uzunluk, vana veya PİG sayısı arttığında tahmin azalamaz. Fiziksel ihlal, bu kuralın çiğnendiği durumların oranıdır.

| Yaklaşım | RMSE | MAE | ±%30 içinde | RMSE oynaklığı | Fiziksel ihlal |
|---|---:|---:|---:|---:|---:|
| **Monoton harman (ET, CAT, XGB)** | 184,6 | **86,4** | **%68** | **4,6** | %0 |
| Extra Trees + FÖ (kısıtsız) | 188,3 | 95,2 | %64 | 14,6 | %11,7 |
| Monoton ET + FÖ | 195,7 | 92,3 | %67 | 15,3 | %0 |
| Monoton CatBoost + FÖ | 199,6 | 96,3 | %67 | 13,2 | %0 |

## 3. Nihai eğitim: nested 5×4 CV, 15 model, 61 proje

Bu adımda hiperparametreler iç döngüde seçildi ve uygulamaya alınacak modeller fiziksel tutarlılık süzgecinden geçirildi. Sonuç:

| Sıra | Model | R² | RMSE | MAE | MedAE | WAPE |
|---:|---|---:|---:|---:|---:|---:|
| 🥇 | Monoton Extra Trees + FÖ | 0,907 | 175,3 | 89,6 | 34,0 | %22,5 |
| 🥈 | Monoton CatBoost + FÖ | 0,902 | 179,3 | 90,6 | 46,8 | %22,8 |
| 🥉 | Monoton XGBoost | 0,901 | 180,9 | 93,9 | 45,0 | %23,6 |
| 4 | Monoton harman | 0,889 | 191,4 | 90,4 | 37,9 | %22,7 |

- Monoton kısıt doğruluktan ödün verdirmedi; nested CV'de Monoton ET + FÖ, kısıtsız halinden (RMSE 177,1) daha iyi çıktı.
- Taramada birinci olan harman, nested CV'de dördüncü oldu. İlk dört model arasındaki farklar tekrarlar arası oynaklık içinde kalıyor. Uygulama zaten ilk üç modeli yan yana gösterdiği için kullanıcı fiilen bir harman görüyor.

## 4. Önceki kurulumla adil kıyas

İki kurulum aynı 61 proje ve aynı dış katlar üzerinde sınandı. Önceki kurulumda modeller MAGA FAZ 2 dahil eğitilmişti.

| Kurulum | R² | RMSE | MAE | MedAE | ±%30 içinde |
|---|---:|---:|---:|---:|---:|
| Önceki 🥇 RF | 0,72 | 304,9 | 157,6 | 55,6 | %52 |
| Önceki 🥈 Stacking | 0,73 | 298,5 | 170,5 | 73,6 | %44 |
| Önceki 🥉 XGBoost | 0,86 | 218,0 | 125,5 | 65,4 | %56 |
| **Yeni 🥇 Monoton ET + FÖ** | **0,91** | **175,3** | **89,6** | **34,0** | **%66** |

## 5. Dikkat edilecekler

- **İyimserlik payı:** Pek çok aday aynı 64 projede denendiği için sonuçlarda küçük bir iyimserlik payı olabilir. Nested CV hiperparametre seçimini dürüst tutar, ancak yöntem seçimini kapsamaz. Gerçek performans, yeni ihaleler geldikçe izlenmelidir.
- **Sabit test:** 3 küçük projelik sabit testte en iyi sonucu Monoton XGBoost verdi (R² 0,88). 3 satır sıralama için yeterli değildir.
- **Doğrulanması önerilen kayıt:** **MUT DGBH** (20", 80,4 km, 30,1 mn TL), benzer projelere göre çok düşük bedelli. En büyük göreli hata bu projede oluşuyor (tahmin ~549 mn TL). Kapsamı teyit edilmeli: eksik kapsam, kısmi iş ya da veri giriş hatası olabilir.
