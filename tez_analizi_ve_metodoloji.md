# Tez analizi, geliştirilen metodoloji ve sonuç yorumu

## 1. Tezin veri tanımı ve hedefi

İncelenen çalışma Coşkun Çakmak'ın *Doğal Gaz Boru Hattı İnşaat Maliyetlerinin Ön Tahmini İçin Bir Yöntem Önerisi* başlıklı, Ocak 2025 tarihli doktora tezidir.

Tez, 1997-2024 arasında Türkiye'de başlanmış veya tamamlanmış 113 doğal gaz boru hattı projesini kullanır (tez s.27). Büyük su kütlelerinden geçen veya önemli kısmı ülke dışında kalan hatlar dışlanmıştır. Ana kaynak EKAP; erişilemeyen kayıtlar için yüklenici siteleri, TMMOB, TBMM tutanakları ve bölgesel kaynaklar kullanılmıştır.

Tezde hedef sıradan nominal sözleşme bedeli değildir. İhale bedelleri önce sözleşme tarihindeki TCMB döviz alış kuruyla USD'ye çevrilmiş, ardından ABD CPI oranıyla Temmuz 2024 alım gücüne güncellenmiştir (tez s.31-35):

```text
Sözleşme tarihindeki USD = TL ihale bedeli / sözleşme tarihindeki USD kuru
Temmuz 2024 USD = sözleşme tarihindeki USD × CPI_Temmuz_2024 / CPI_sözleşme_tarihi
```

Malzemesiz ihalelerde yapım işi ile çelik boru alımı ayrı ayrı güncellenip toplanmıştır. Güncellenen `VERİLER_GÜNCELLENMİŞ.xlsx` dosyasında nominal TL sözleşme bedeli, sözleşme tarihi ve Temmuz 2026 Yİ-ÜFE düzeyindeki güncel TL değer birlikte yer alır. Modelin hedefi bu son sütundur. Bu hedef tezin Temmuz 2024 USD hedefiyle aynı para birimi veya fiyat bazı değildir; tez sonuçlarıyla sayısal olarak doğrudan kıyaslanamaz.

Dosyada Yİ-ÜFE endeks değerlerinin kendisi bulunmadığı için kod fiyat güncellemesini yeniden hesaplamaz. Verilen `güncel / nominal` oranını denetim alanı olarak üretir ve kaynak değerleri olduğu gibi kullanır. İki kaydın tarih hücresinde tarih yerine `güncel` yazmakta ve bu satırların katsayısı 1,00'dır.

Tezdeki beş bağımsız değişken boru çapı, hat uzunluğu, hat vanası, take-off vanası ve pig istasyonu sayısıdır. Bir projede birden fazla çap varsa, hattın gaz hacmini koruyan eşdeğer çap hesaplanmıştır (tez s.28-30). Bu projede kullanıcı talimatıyla `TAKE OFF VANA SAYISI` dışarıda bırakılmış, kalan dört sütun kullanılmıştır.

## 2. Tezdeki keşifsel analiz ve grafikler

Tezin 113 satırlık verisinde hedef ortalaması 36,7 milyon USD, medyanı 12,9 milyon USD, maksimumu 636,9 milyon USD'dir (tez s.36). Özellikler ve hedef sağa çarpıktır; küçük/orta projeler çoğunlukta, çok büyük projeler azdır (tez s.40-43).

Tezde kullanılan ve bu projede karşılığı üretilen temel görseller:

- Bağımsız değişken histogramları ve hedef histogramı
- Hedefin maliyet dilimlerine göre pasta grafiği
- Çap, hat uzunluğu ve maliyet kabarcık grafiği
- Hat uzunluğuna göre çap dağılımı
- Km başına güncellenmiş maliyet histogramı ve maliyet dilimleri
- Hat uzunluğu/çap ile birim maliyet grafikleri
- Bütün değişkenlerin korelasyon matrisi
- Her model için gerçek-tahmin çizgisi ve kalıntı grafiği
- RF ve XGB için örnek karar ağacı
- Tüm model tahminlerinin ortak karşılaştırması

Bu projede pasta grafik yerine dağılımı daha doğru koruyan histogram + kutu grafiği kullanıldı. Birim maliyet grafikleri ana modele yeni bir hedef sokmamak için performans karşılaştırmasına dahil edilmedi. Tez tarzı gerçek/tahmin, kalıntı, korelasyon, histogram, kabarcık ve RF ağaç grafikleri üretildi. Ayrıca nominal TL ile Temmuz 2026 güncel TL değerini ve güncelleme katsayısı dağılımını gösteren bir fiyat denetim grafiği eklendi.

## 3. Tez algoritmaları ve doğrulama düzeni

Tez veriyi `%80` eğitim / `%20` test olarak `random_state=42` ile tek kez böler; 90 eğitim ve 23 test satırı oluşur (tez s.66-68). Hiperparametre araması eğitim bölümünde 5 katlı `GridSearchCV` ve `scoring='r2'` ile yapılır.

| Model | Tezde aranan başlıca değerler | Tezde seçilen değer |
|---|---|---|
| ÇDR | Ayar yok | `LinearRegression` |
| ElasticNet | `alpha=[0.01,0.1,1,10,100,1000]`, `l1_ratio=[0.1,0.5,0.7,0.9]` | `alpha=100`, `l1_ratio=0.7` |
| KNN | `n_neighbors=3..11`, `weights=[uniform,distance]` | `n_neighbors=4`, `weights=distance` |
| RF | `n_estimators=[10,50,100]`, `max_features=[sqrt]`, `min_samples_split=[5,10]`, `min_samples_leaf=[2,4]` | `100`, `sqrt`, `5`, `2` |
| XGB | `n_estimators=[10,50,100,200,500]`, `learning_rate=[0.01,0.05,0.1,0.2,0.3]`, `max_depth=[3,5,7,10]`, `subsample=[0.7,0.85,1]`, `colsample_bytree=[0.7,0.85,1]` | `50`, `0.2`, `3`, `1`, `1` |

Tezde hiperparametre sonrası test sonuçları (tez s.113):

| Model | R² | RMSE (USD) | MAE (USD) | MAPE |
|---|---:|---:|---:|---:|
| ÇDR | 0,61 | 43.370.642 | 30.486.682 | %335,94 |
| ElasticNet | 0,74 | 35.228.241 | 23.334.860 | %314,74 |
| KNN | 0,82 | 29.218.118 | 9.967.554 | %23,65 |
| RF | 0,83 | 28.318.045 | 12.536.326 | %41,24 |
| XGB | 0,89 | 23.472.276 | 10.240.110 | %34,95 |

Tezin kendi verisinde XGB, R² ve RMSE'ye göre birinci; RF ikinci; KNN üçüncüdür. KNN MAE ve MAPE'de daha iyi görünür. Bu, tek bir modelin bütün hata tanımlarında aynı sırada olmayabileceğini gösterir.

## 4. Tez protokolünün güçlü ve geliştirmeye açık yönleri

Güçlü yönler:

- Hedef farklı yıllardaki nominal bedeller yerine ortak Temmuz 2024 USD alım gücüne getirilmiştir.
- Doğrusal, uzaklık tabanlı, bagging ve boosting aileleri birlikte denenmiştir.
- Eğitim ve test metrikleri ayrı sunulmuş, gerçek/tahmin ve kalıntı grafikleriyle sayısal sonuçlar desteklenmiştir.
- Hiperparametre araması yalnızca eğitim verisi üzerinde yapılmıştır.

Geliştirmeye açık yönler:

- 113 gözlemde tek `%20` test bölmesi model sıralamasını bölünmeye duyarlı bırakır; dış çapraz doğrulama yoktur.
- GridSearchCV ile model seçimi yapıldıktan sonra aynı eğitim düzenine ait skorlar iyimser olabilir; nested CV bu seçme yanlılığını azaltır.
- Tez ekran görüntülerindeki KNN akışında özellik ölçekleme görünmez. Oysa kilometre sütunu uzaklık hesabını adet sütunlarına göre domine edebilir.
- ElasticNet katsayı cezası özellik ölçeğine duyarlıdır; ölçekleme olmadan `alpha` yorumlanması zorlaşır.
- R² küçük test katlarında oynaktır; RMSE de birkaç dev projeye güçlü ağırlık verir. Birden fazla mutlak/oransal/sağlam metrik birlikte değerlendirilmelidir.
- MAPE düşük bedelli projelerde çok büyüyebilir; tezde doğrusal modellerin `%300+` MAPE değerleri bunun açık örneğidir.
- Tezin güncel-USD hedefi ile nominal veya farklı dönemlere ait bir hedef aynı problem değildir.

## 5. Bu projede uygulanan daha sağlam düzen

İki protokol birlikte çalıştırıldı:

1. **Sabit holdout:** Kullanıcı talebine göre `%5`e en yakın tam satır sayısı ayrılmıştır. 65 kayıt tam olarak `%5`e bölünemediği için `random_state=42` ile 3 sabit test (`%4,62`) ve 62 eğitim satırı oluşur. Test satırları model seçimine girmez.
2. **Birincil nested CV:** 62 eğitim satırında dışta 5, içte 4 kat uygulanır. Her eğitim satırı tam bir OOF tahmini alır. İç arama RMSE'yi optimize eder ve nihai sıralama eğitim bölümündeki OOF RMSE ile yapılır. Değerlendirmeden sonra Streamlit modelleri 65 kaydın tamamıyla yeniden eğitilir.

Ön işleme `Pipeline`/`TransformedTargetRegressor` içinde olduğu için yalnızca eğitim katında öğrenilir. KNN girdileri `RobustScaler` ile ölçeklenir. ElasticNet'te hem girdiler dayanıklı ölçeklenir hem hedef eğitim katı içinde standartlaştırılıp tahmin özgün ölçeğe çevrilir. Bütün modellerde sözleşme bedeli için sıfır alt sınırı uygulanır.

`SIRA NO` yalnızca kayıt kimliğidir; model girdisi veya zaman ekseni değildir. `SÖZLEŞME TARİHİ` yalnızca fiyat güncelleme denetiminde ve raporda tutulur. Dış/iç KFold katları `shuffle=True` ile rastgele oluşturulur; kronolojik bölme, gecikme değişkeni, trend veya başka bir zaman serisi yöntemi kullanılmaz.

### Modern ek modeller

- **CatBoost:** Düzenlileştirilmiş boosting; küçük veri ve doğrusal olmayan etkileşimler için aday.
- **Histogram Gradient Boosting:** Histogram tabanlı modern gradyan artırma; yaprak sayısı, öğrenme oranı ve L2 ile kontrol edilir.
- **Stacking Ensemble:** Ridge, RF ve Histogram Gradient Boosting tahminlerini çapraz doğrulamalı meta Ridge ile birleştirir. Meta katman ayrıca ölçeklenir.

Modern bir yöntemin otomatik olarak daha iyi olması beklenmemelidir. Küçük örneklemde ek esneklik varyansı yükseltebilir; bu veri üzerinde modern eklerin hiçbiri nested OOF RMSE'de RF'yi geçmemiştir.

## 6. Metrikler

Tezdeki R², RMSE, MAE ve MAPE aynen korunmuştur. Ek olarak:

- **MedAE:** Uç projelerden daha az etkilenen tipik mutlak hata.
- **NRMSE:** RMSE'yi ilgili değerlendirme kümesinin ortalama hedef değerine bölerek yüzdeye çevirir; farklı para ölçeklerini yorumlamayı kolaylaştırır.
- **WAPE:** `sum(|hata|) / sum(gerçek) × 100`; MAPE'nin küçük hedeflere aşırı ağırlığını azaltır.
- **RMSLE:** Oransal hatayı log ölçekte değerlendirir.
- **Bias:** `mean(tahmin-gerçek)`; pozitif değer sistematik fazla, negatif değer eksik tahmindir.

Her metrik ayrı PNG grafikte ve 1.000 satır-bootstrap yaklaşık `%95` hata çubuğuyla karşılaştırılmıştır. Bootstrap satır bağımsızlığı varsayımı ve küçük örneklem nedeniyle bu aralıklar yaklaşık kabul edilmelidir.

## 7. Mevcut Excel'in veri tanısı

- 65 gözlem; model alanlarında 0 eksik değer; 0 yinelenen sıra no, proje adı veya veri satırı
- Nominal TL bedeli: minimum 2,20 milyon; medyan 37,85 milyon; ortalama 218,71 milyon; maksimum 3,00 milyar TL
- Temmuz 2026 Yİ-ÜFE güncel TL hedefi: minimum 30,10 milyon; medyan 190,02 milyon; ortalama 463,23 milyon; maksimum 5,487 milyar TL
- Güncelleme katsayısı: minimum 1,0000; medyan 2,5970; maksimum 19,2402
- Geçerli sözleşme tarihleri 2017-02-10 ile 2026-03-10 arasındadır; 2 satırda tarih yerine `güncel` bulunur
- Hedef çarpıklığı: 4,128
- IQR üst sınırının üzerinde 9 bedel
- Hat uzunluğu–hat vanası korelasyonu: 0,936; güçlü çoklu bağlantı riski
- Hedef korelasyonları: çap 0,706; uzunluk 0,659; hat vanası 0,537; pig istasyonu -0,009

En yüksek bedelli proje diğer bütün satırlardan belirgin biçimde ayrılır. Ayrıca 20 inç / 80,4 km satırının güncel bedeli yaklaşık 30,10 milyon TL ile benzer ölçekli projelere göre çok düşüktür. Bu iki satırdan hiçbiri otomatik hata kabul edilmemiş ve kullanıcı verisi değiştirilmemiştir; ihale kapsamı ayrıca doğrulanmalıdır.

## 8. Nihai sonuçların yorumu

Birincil nested CV OOF sıralaması:

| Sıra | Model | R² | RMSE (M TL) | MAE (M TL) | MAPE | WAPE | MedAE (M TL) |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Rastgele Orman | 0,5796 | 555,40 | 169,85 | %53,49 | %35,30 | 58,07 |
| 2 | Stacking | 0,5704 | 561,48 | 181,48 | %71,36 | %37,71 | 59,98 |
| 3 | XGBoost | 0,5406 | 580,60 | 175,96 | %54,12 | %36,57 | 59,01 |
| 4 | ElasticNet | 0,5301 | 587,22 | 222,45 | %99,48 | %46,23 | 75,68 |
| 5 | KNN | 0,5106 | 599,31 | 202,66 | %51,26 | %42,11 | 62,56 |
| 6 | CatBoost | 0,4628 | 627,87 | 195,29 | %51,55 | %40,58 | 59,29 |
| 7 | Histogram Gradient Boosting | 0,4152 | 655,12 | 246,15 | %72,48 | %51,15 | 62,86 |
| 8 | ÇDR | 0,3772 | 676,05 | 304,22 | %130,78 | %63,22 | 124,09 |

RMSE'ye göre Rastgele Orman seçildi; tam veride `n_estimators=300`, `max_features=sqrt`, `min_samples_split=5`, `min_samples_leaf=2` bulundu. Dış-test permütasyon öneminde boru çapı ve hat uzunluğu baskındır; hat vanası sınırlı, pig istasyonu ise bu veri üzerinde çok düşük katkı göstermiştir. Bu bir nedensellik sonucu değildir ve uzunluk–vana korelasyonundan etkilenir.

Üç satırlık sabit testte Histogram Gradient Boosting R²=0,8952 ile öne çıkmıştır. Bu kadar küçük test kümesindeki sıralama çok oynak olduğu için model seçimi bu tabloya değil 62 eğitim satırındaki nested CV OOF sonuçlarına dayandırılmıştır.

Seçilen RF için yaklaşık `%90` çapraz-konformal yarıçap `±408,38 milyon TL`dir. Aralığın geniş olması; az gözlem, 5,49 milyar TL'lik uç proje ve eksik maliyet sürücüleri nedeniyle belirsizliğin yüksek olduğunu gösterir. Model araştırma/ön bütçe desteği olarak kullanılabilir; mevcut haliyle bağlayıcı ihale tahmini için yeterince dar değildir.

## 9. En yüksek etkili veri iyileştirmeleri

1. Dosyada kullanılan aylık Yİ-ÜFE endeks değerlerini de saklayarak güncelleme hesabını kodla yeniden üretilebilir kılmak.
2. Malzemeli/malzemesiz ihale kapsamını, çelik boru bedelini ve mümkünse zemin/topografya/geçiş sayılarını eklemek.
3. En yüksek ve en düşük birim maliyetli satırların kaynak sözleşmelerini doğrulamak.
4. Yeni projeleri özellikle 30-48 inç ve yüksek maliyet bölgesinden toplamak.
5. Yeterli yeni proje oluştuğunda sıra veya tarihten bağımsız, ayrı bir dış doğrulama kümesi ayırmak.

Kullanıcı dört özellik şartı koyduğu için bu ek değişkenler mevcut modele alınmamıştır; öneriler sonraki veri sürümü içindir.

## 10. Görsel tahmin uygulaması

`tahmin_uygulamasi.py`, kullanıcının BORU ÇAPI, HAT UZUNLUĞU (km), HAT VANASI SAYISI (ADET) ve PİG İSTASYONU SAYISI (ADET) değerlerini girebildiği Streamlit arayüzüdür. Hedef doğrudan `GÜNCEL DEĞER (Yİ ÜFE / TEMMUZ 2026)` sütunudur ve sonuçlar TL olarak sunulur.

Uygulamanın gösterdiği üç model, üç satırlık holdout'a göre değil 62 eğitim satırındaki nested CV OOF RMSE sırasına göre seçilir. Güncel sıralama Rastgele Orman, Stacking Ensemble ve XGBoost'tur. Eğitim komutu bu üç modeli tüm 65 satırla yeniden eğitir, `en_iyi_3_model.joblib` içinde saklar ve model sırası, performans değerleri ile eğitim özelliği aralıklarını `model_manifest.json` dosyasına yazar. Arayüz bu iki artefaktı birlikte doğrulayarak yükler.

Her modelin tahmini ayrı kartta ve ortak yatay çubuk grafikte gösterilir. Ayrıca nested CV R², RMSE ve MAE değerleri tahmin ekranında referans olarak verilir. Bir girdi eğitim minimum-maksimum aralığının dışındaysa uygulama tahmini engellemez; bunun bir ekstrapolasyon olduğunu açıkça bildirir. `SIRA NO`, proje adı, sözleşme tarihi, nominal bedel ve TAKE OFF vana sayısı uygulama girdisi değildir; hiçbir zaman serisi değişkeni veya kronolojik bölme kullanılmaz.
