# Doğal gaz boru hattı ihale sözleşme bedeli modellemesi

Bu proje, `VERİLER_GÜNCELLENMİŞ.xlsx` içindeki dört girdiden Temmuz 2026 Yİ-ÜFE düzeyine güncellenmiş sözleşme bedelini tahmin eder:

- Boru çapı
- Hat uzunluğu (km)
- Hat vanası sayısı
- Pig istasyonu sayısı

`TAKE OFF VANA SAYISI` kaynak dosyada bulunsa da kullanıcı talimatı gereği modele alınmaz. Model hedefi `GÜNCEL DEĞER (Yİ ÜFE / TEMMUZ 2026)` ve para birimi TL'dir. Nominal `SÖZLEŞME BEDELİ` ile `SÖZLEŞME TARİHİ` fiyat güncelleme denetimi ve raporlama için korunur; model özelliği değildir.

`SIRA NO` yalnızca kayıt kimliğidir. Modelde özellik olarak kullanılmaz, satırlar kronolojik kabul edilmez ve zamansal train/test bölmesi yapılmaz. Dış ve iç çapraz doğrulama katları rastgele karıştırılır; bu bir zaman serisi çalışması değildir.

## Tez analizi

Ayrıntılı, sayfa referanslı inceleme ve bu veri üzerindeki yorumlar için [tez_analizi_ve_metodoloji.md](tez_analizi_ve_metodoloji.md) dosyasına bakın.

Coşkun Çakmak'ın Ocak 2025 tarihli doktora tezi 113 projeyi, beş bağımsız değişkeni ve güncellenmiş maliyet hedefini kullanır. Veri 90 eğitim / 23 test olacak şekilde `%20` test oranı ve `random_state=42` ile ayrılmıştır. Tezin modelleri:

1. Çoklu Doğrusal Regresyon (ÇDR)
2. ElasticNet Regresyon (ER)
3. K-En Yakın Komşu (KNN)
4. Rastgele Ormanlar (RF)
5. XGBoost (XGB)

Tezde R², RMSE, MAE ve MAPE hesaplanmış; yorum ağırlığı R² ve RMSE'ye verilmiştir. ER, KNN, RF ve XGB için 5 katlı `GridSearchCV` uygulanmış ve optimizasyon ölçütü R² seçilmiştir. Tezdeki en iyi test sonucu XGB için R²=0,89 ve RMSE=23.472.275,50 USD'dir. Bu sayı bu projede yeniden üretilmesi gereken bir eşik değildir: mevcut Excel 65 satır ve dört girdi kullanır; hedefi ise tezin Temmuz 2024 USD hedefinden farklı olarak Temmuz 2026 Yİ-ÜFE güncel TL değeridir.

Tezde kullanılan başlıca grafikler; değişken histogramları, korelasyon matrisi, çap-uzunluk-maliyet kabarcık grafiği, model bazında gerçek/tahmin çizgileri, kalıntı grafikleri, örnek ağaçlar ve bütün model tahminlerinin ortak karşılaştırmasıdır. Kod bunların veri ve model karşılaştırmasına yararlı olan karşılıklarını üretir.

## Daha sağlam metodoloji

İki değerlendirme birlikte raporlanır:

- **Sabit holdout:** Kullanıcı talebine göre verinin `%5`ine en yakın tam satır sayısı test için ayrılır. 65 kayıtta bu, 3 test satırı (`%4,62`) ve 62 eğitim satırıdır. Test satırları model seçimine girmez.
- **Birincil model seçimi:** 62 satırlık eğitim bölümünde dışta 5, içte 4 katlı iç içe çapraz doğrulama uygulanır. Her eğitim satırı tam bir kez dış-test tahmini (OOF) alır. Model sıralaması bu sızıntısız OOF tahminlerinin RMSE değerine dayanır. Değerlendirme bittikten sonra Streamlit modelleri 65 kaydın tamamıyla yeniden eğitilir.

KNN ve ElasticNet boru uzunluğunun sayısal ölçeğinin uzaklık/ceza hesabını domine etmemesi için eğitim katlarının içinde ölçeklenir. ElasticNet'in hedefi de eğitim katı içinde standartlaştırılıp tahminler TL ölçeğine geri çevrilir. Böylece ön işleme test verisine bilgi sızdırmaz.

Sözleşme bedeli fiziksel olarak negatif olamayacağı için bütün modellerin nihai tahminleri sıfır alt sınırında kırpılır. Bu kural tüm modeller için aynı uygulanır ve metrikler kırpılmış operasyonel tahminlerden hesaplanır.

### Modern ek yöntemler

- **CatBoost:** Küçük veri kümelerinde düzenlileştirilmiş boosting ve simetrik ağaç yapısıyla güçlü, kararlı bir doğrusal olmayan adaydır.
- **Histogram Gradient Boosting:** Sürekli değişkenleri histogram kutularıyla işleyen, düzenlileştirme ve erken durdurma sunan modern bir boosting yöntemidir.
- **Stacking Ensemble:** Ridge, Rastgele Orman ve Histogram Gradient Boosting taban modellerinin çapraz doğrulamalı tahminlerini bir meta modelle birleştirir; farklı model yanlılıklarını dengelemeyi amaçlar.

### Metrikler

Tez metriklerinin tamamı korunur: R², RMSE, MAE ve MAPE. RMSE/MAE hedef Temmuz 2026 TL olduğu için TL cinsindedir; okunabilir tabloda milyon TL gösterilir. Bunlara şu ölçütler eklenir:

- **MedAE:** Uç değerlere RMSE/MAE'den daha dayanıklı medyan mutlak hata.
- **NRMSE:** RMSE'yi ilgili kümenin ortalama hedef değerine bölerek yüzdeye çevirir; para biriminden bağımsız ölçek karşılaştırmasına yardım eder.
- **WAPE:** Toplam mutlak hatayı toplam gerçekleşen bedele oranlar; MAPE'nin düşük bedelli satırlara aşırı ağırlık vermesini azaltır.
- **RMSLE:** Sıfır alt sınırı uygulanmış operasyonel tahminlerin oransal sapmasını logaritmik ölçekte değerlendirir.
- **Bias:** Modelin sistematik fazla veya eksik tahmin yönünü gösterir (`tahmin - gerçek`).

OOF hatalarının mutlak değerlerinden yaklaşık `%90` çapraz-konformal aralık hesaplanır. Bu aralık küçük örneklem nedeniyle bir risk göstergesidir; sözleşmesel garanti değildir.

## Önerilen uygulama akışı

Doğrulanan geliştirme ortamı Python 3.10.11'dir. Modelleme `scikit-learn`, XGBoost ve CatBoost; görsel uygulama Streamlit 1.59.2 ve Altair 6.2.2 kullanır. Kesin bağımlılık sürümleri `requirements.txt` içindedir.

VS Code içinde proje klasörünü açın ve PowerShell terminalinde aşağıdaki aşamaları kullanın.

### 1. Bir defalık ortam kurulumu

Bu betik `.venv` yoksa oluşturur; varsa mevcut ortamı kullanır. `requirements.txt` içindeki kütüphanelerin eksik olanlarını kurar:

```powershell
.\01_kurulum.cmd
```

### 2. İstenildiğinde model eğitimi

Excel değiştiğinde veya bütün sonuçları yeniden üretmek istediğinizde:

```powershell
.\02_egitim.cmd
```

Bu adım tüm modelleri yeniden eğitir; metin/CSV/Excel raporlarını, bütün PNG grafiklerini, model manifestini ve nested CV OOF RMSE'ye göre en iyi üç final modeli `sonuclar` klasörüne yazar.

### 3. Eğitimden sonra tahmin uygulaması

Tahmin yapmak istediğinizde:

```powershell
.\03_uygulamayi_baslat.cmd
```

Başlatma betiği `sonuclar/model_manifest.json` ile `sonuclar/en_iyi_3_model.joblib` dosyalarını denetler. Üç eğitimli model yoksa Streamlit'i açmaz ve önce eğitim komutunu çalıştırmanızı ister. Modeller hazırsa tarayıcıda açılan uygulamaya boru çapı, hat uzunluğu, hat vanası sayısı ve PİG istasyonu sayısı girilir. Uygulama en iyi üç final modelin Temmuz 2026 Yİ-ÜFE bazlı güncel TL tahminlerini ayrı ayrı gösterir. Girdi eğitim aralığının dışındaysa tahmin yine üretilir ancak ekstrapolasyon uyarısı gösterilir.

İlk kurulumdan sonra günlük kullanım iki ayrı komuttan oluşur: yeniden sonuç üretmek için `02_egitim.cmd`, tahmin yapmak için `03_uygulamayi_baslat.cmd`. `.cmd` başlatıcıları Windows PowerShell betik çalıştırma kısıtlamasını yalnızca ilgili işlem için aşar; kalıcı Execution Policy değişikliği yapmaz. Streamlit açıkken terminal meşgul kalır; uygulamayı `Ctrl+C` ile kapatabilirsiniz.

Hızlı duman testi için modern boosting iterasyonlarını azaltan seçenek:

```powershell
.\.venv\Scripts\python.exe .\ihale_maliyet_modelleme.py --excel .\VERİLER_GÜNCELLENMİŞ.xlsx --output .\sonuclar_test --fast
```

## Üretilen temel çıktılar

- `sonuclar/model_performanslari.txt`: üç sabit test kaydındaki modeller × metrikler tablosu ve kısa metrik açıklamaları
- `sonuclar/model_performanslari.csv`: birincil OOF metrikleri ve yaklaşık güven aralıkları
- `sonuclar/yuzde5_holdout_metrikleri.csv`: `%5`e en yakın sabit test bölmesinin eğitim/test sonuçları
- `sonuclar/yuzde5_holdout_tahminleri.xlsx`: sabit test satırlarının gerçek ve model tahminleri
- `sonuclar/satir_bazli_tahminler.xlsx`: sıra no, proje adı, nominal/güncel TL bedeli, tarih, dört girdi ve tüm tahminler
- `sonuclar/fiyat_guncelleme_denetimi.xlsx`: nominal bedel, tarih, güncel bedel ve güncelleme katsayısı
- `sonuclar/en_iyi_model.joblib`: tüm veriyle yeniden eğitilmiş seçili model
- `sonuclar/en_iyi_3_model.joblib`: görsel uygulamanın kullandığı, tüm veriyle eğitilmiş ilk üç model
- `sonuclar/model_manifest.json`: özellik sırası, ilk üç modelin sıralaması/metrikleri, eğitim aralıkları, sürümler, belirsizlik yarıçapı ve parametreler
- `sonuclar/grafikler/`: tez tarzı ve modern tanı/karşılaştırma grafikleri

`*_DEGERLENDIRME_TAHMIN` sütunları 62 eğitim satırında OOF, 3 sabit test satırında tamamen dış-test tahminidir. `*_TAM_TAHMIN` sütunları aynı satırları görerek eğitilmiş final modellerin uyum değerleridir; bağımsız test performansı sayılmaz.
